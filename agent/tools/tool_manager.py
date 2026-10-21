import importlib
import copy
import importlib.util
import threading
from pathlib import Path
from typing import Dict
from agent.tools.base_tool import BaseTool
from common.log import logger
from config import conf


def _normalize_mcp_configs(raw) -> list:
    """
    Convert MCP server config to internal list format.
    Supports:
      - list format (mcp_servers):  [{"name": "x", "type": "stdio", ...}]
      - dict format (mcpServers):   {"x": {"command": "npx", ...}}
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        result = []
        for name, cfg in raw.items():
            entry = {"name": name, **cfg}
            if "type" not in entry:
                entry["type"] = "sse" if "url" in entry else "stdio"
            result.append(entry)
        return result
    return []


class ToolManager:
    """
    Tool manager for managing tools.

    One instance per Agent workspace. Not a plain singleton: the instance
    caches booted MCP subprocesses so that per-session agent init does not
    re-fork them, and each workspace has its own ``mcp.json``. A single
    process-wide instance would let the first Agent to start decide which MCP
    servers exist, hand its tools (and their credentials) to every other
    Agent, and leave their own servers permanently unloaded.
    """
    _instances: Dict[str, "ToolManager"] = {}
    _instances_lock = threading.Lock()

    def __new__(cls):
        from common.state_dir import real_state_root
        from common.runtime_identity import current_identity

        workspace_root = real_state_root()
        key = (workspace_root, current_identity().user_id or 'local-default')
        instance = cls._instances.get(key)
        if instance is not None:
            return instance
        with cls._instances_lock:
            instance = cls._instances.get(key)
            if instance is None:
                instance = super(ToolManager, cls).__new__(cls)
                instance.workspace_root = workspace_root
                instance.tool_classes = {}  # Store tool classes instead of instances
                instance._initialized = False
                cls._instances[key] = instance
            return instance

    @classmethod
    def instances(cls) -> list:
        """Every ToolManager built so far, for process-wide operations."""
        with cls._instances_lock:
            return list(cls._instances.values())

    @classmethod
    def reset_instances(cls) -> None:
        """Drop every cached instance. For tests."""
        with cls._instances_lock:
            cls._instances.clear()

    def __init__(self):
        # Runs on every ToolManager() call, including the ones that get a
        # cached instance back, so every field is guarded.
        if not hasattr(self, 'capability_settings'):
            from common.runtime_identity import current_identity
            from agent.tools.capability_settings import CapabilitySettings
            self.identity = current_identity()
            self.capability_settings = CapabilitySettings(getattr(self, 'workspace_root', None), user_id=self.identity.user_id)
            self.workspace_root = self.capability_settings.workspace_root
        if not hasattr(self, 'tool_classes'):
            self.tool_classes = {}  # Dictionary to store tool classes
        if not hasattr(self, '_mcp_registry'):
            self._mcp_registry = None  # Lazy init: only created when MCP servers are configured
        if not hasattr(self, '_mcp_tool_instances'):
            self._mcp_tool_instances: dict = {}  # tool_name -> McpTool instance
        if not hasattr(self, '_mcp_lock'):
            # Guards _mcp_loaded check-then-set so concurrent callers
            # don't trigger duplicate background loaders.
            self._mcp_lock = threading.RLock()
        if not hasattr(self, '_mcp_pending_clients'):
            self._mcp_pending_clients = {}
        if not hasattr(self, '_mcp_generations'):
            self._mcp_generations = {}
        if not hasattr(self, '_mcp_loaded'):
            # Idempotency flag. Flipped to True the moment the first loader
            # is dispatched (synchronously, inside _mcp_lock). Subsequent
            # _load_mcp_tools() calls become no-ops, so per-session agent
            # initialization never re-forks MCP subprocesses.
            self._mcp_loaded = False
        if not hasattr(self, '_mcp_status'):
            # server_name -> "pending" / "ready" / "failed"
            # Useful for UI / introspection while async loading is in progress.
            self._mcp_status: dict = {}
        if not hasattr(self, '_mcp_signature'):
            # (mtime, sha256) of mcp.json the last time we loaded.
            # Used by refresh_mcp_if_changed() to skip re-parsing when nothing changed.
            self._mcp_signature: tuple = (None, None)
        if not hasattr(self, '_mcp_active_configs'):
            # server_name -> normalized config dict, for diff-based reload.
            self._mcp_active_configs: dict = {}
        if not hasattr(self, '_mcp_tool_vectors'):
            # mcp_tool_name -> embedding vector, used by on-demand tool
            # retrieval. Populated lazily on first retrieval so users who
            # never enable the feature pay zero embedding cost.
            self._mcp_tool_vectors: dict = {}
        if not hasattr(self, '_mcp_vector_lock'):
            # Guards incremental index builds so concurrent turns don't
            # double-embed the same newly-loaded MCP tools.
            self._mcp_vector_lock = threading.Lock()
        if not hasattr(self, '_embedding_provider_initialized'):
            # The embedding provider is created once, lazily, and reused for
            # both tool-index and per-query embeddings. None means keyword-only
            # mode (no provider configured) — retrieval then falls back to full
            # injection at the caller.
            self._embedding_provider_initialized = False
            self._embedding_provider = None

    def load_tools(self, tools_dir: str = "", config_dict=None, *, load_mcp=True):
        """
        Load tools from both directory and configuration.

        :param tools_dir: Directory to scan for tool modules
        """
        if tools_dir:
            self._load_tools_from_directory(tools_dir)
            self._configure_tools_from_config()
        else:
            self._load_tools_from_init()
            self._configure_tools_from_config(config_dict)

        if load_mcp:
            self._load_mcp_tools()

    def _load_tools_from_init(self) -> bool:
        """
        Load tool classes from tools.__init__.__all__

        :return: True if tools were loaded, False otherwise
        """
        try:
            # Try to import the tools package
            tools_package = importlib.import_module("agent.tools")

            # Check if __all__ is defined
            if hasattr(tools_package, "__all__"):
                tool_classes = tools_package.__all__

                # Import each tool class directly from the tools package
                for class_name in tool_classes:
                    try:
                        # Skip base classes
                        if class_name in ["BaseTool", "ToolManager"]:
                            continue

                        # Get the class directly from the tools package
                        if hasattr(tools_package, class_name):
                            cls = getattr(tools_package, class_name)

                            if (
                                    isinstance(cls, type)
                                    and issubclass(cls, BaseTool)
                                    and cls != BaseTool
                            ):
                                try:
                                    # Skip tools that need special initialization
                                    if class_name in ["MemorySearchTool", "MemoryGetTool"]:
                                        logger.debug(f"Skipped tool {class_name} (requires memory_manager)")
                                        continue
                                    # McpTool instances are registered dynamically via _load_mcp_tools()
                                    if class_name == "McpTool":
                                        logger.debug(f"Skipped tool {class_name} (registered dynamically via mcp_servers config)")
                                        continue
                                    
                                    # Create a temporary instance to get the name
                                    temp_instance = cls()
                                    tool_name = temp_instance.name
                                    # Store the class, not the instance
                                    self.tool_classes[tool_name] = cls
                                    logger.debug(f"Loaded tool: {tool_name} from class {class_name}")
                                except ImportError as e:
                                    # Handle missing dependencies with helpful messages
                                    error_msg = str(e)
                                    if "markdownify" in error_msg:
                                        logger.warning(
                                            f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                            f"  Install with: pip install markdownify"
                                        )
                                    else:
                                        logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                                except Exception as e:
                                    logger.error(f"Error initializing tool class {cls.__name__}: {e}")
                    except Exception as e:
                        logger.error(f"Error importing class {class_name}: {e}")

                return len(self.tool_classes) > 0
            return False
        except ImportError:
            logger.warning("Could not import agent.tools package")
            return False
        except Exception as e:
            logger.error(f"Error loading tools from __init__.__all__: {e}")
            return False

    def _load_tools_from_directory(self, tools_dir: str):
        """Dynamically load tool classes from directory"""
        tools_path = Path(tools_dir)

        # Traverse all .py files
        for py_file in tools_path.rglob("*.py"):
            # Skip initialization files and base tool files
            if py_file.name in ["__init__.py", "base_tool.py", "tool_manager.py"]:
                continue

            # Get module name
            module_name = py_file.stem

            try:
                # Load module directly from file
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Find tool classes in the module
                    for attr_name in dir(module):
                        cls = getattr(module, attr_name)
                        if (
                                isinstance(cls, type)
                                and issubclass(cls, BaseTool)
                                and cls != BaseTool
                        ):
                            try:
                                # Skip memory tools (they need special initialization with memory_manager)
                                if attr_name in ["MemorySearchTool", "MemoryGetTool"]:
                                    logger.debug(f"Skipped tool {attr_name} (requires memory_manager)")
                                    continue
                                
                                # Create a temporary instance to get the name
                                temp_instance = cls()
                                tool_name = temp_instance.name
                                # Store the class, not the instance
                                self.tool_classes[tool_name] = cls
                            except ImportError as e:
                                # Handle missing dependencies with helpful messages
                                error_msg = str(e)
                                if "markdownify" in error_msg:
                                    logger.warning(
                                        f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                        f"  Install with: pip install markdownify"
                                    )
                                else:
                                    logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                            except Exception as e:
                                logger.error(f"Error initializing tool class {cls.__name__}: {e}")
            except Exception as e:
                print(f"Error importing module {py_file}: {e}")

    def _configure_tools_from_config(self, config_dict=None):
        """Configure tool classes based on configuration file"""
        try:
            # Get tools configuration
            tools_config = config_dict or conf().get("tools", {})

            # Record tools that are configured but not loaded
            missing_tools = []

            # Store configurations for later use when instantiating
            self.tool_configs = tools_config

            # Check which configured tools are missing
            for tool_name in tools_config:
                if tool_name not in self.tool_classes:
                    missing_tools.append(tool_name)

            # If there are missing tools, record warnings
            if missing_tools:
                for tool_name in missing_tools:
                    if tool_name == "google_search":
                        logger.warning(
                            "[ToolManager] Google Search tool is configured but may need API key.\n"
                            "  Get API key from: https://serper.dev\n"
                            "  Configure in config.json: tools.google_search.api_key"
                        )
                    else:
                        logger.warning(f"[ToolManager] Tool '{tool_name}' is configured but could not be loaded.")

        except Exception as e:
            logger.error(f"Error configuring tools from config: {e}")

    def _mcp_json_path(self) -> str:
        # Anchored to the workspace this instance was built for, not to the
        # ambient identity: the MCP loader and refresh run on background
        # threads that carry no identity and would otherwise read the default
        # Agent's mcp.json.
        from common.state_dir import mcp_config_file
        return str(mcp_config_file(base=self.workspace_root))

    def _read_mcp_json_signature(self):
        """
        Return (mtime, sha256_of_bytes) for ~/stella/mcp.json without parsing.
        Returns (None, None) if the file doesn't exist or is unreadable.
        Cheap enough (one stat + one small read) to call on every agent init.
        """
        import os
        import hashlib
        path = self._mcp_json_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return (None, None, self.capability_settings.revision('mcp'))
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return (mtime, None)
        return (mtime, digest, self.capability_settings.revision('mcp'))

    def _load_mcp_configs(self) -> list:
        from core.mcp.managed import configurations
        managed = configurations(self)
        reserved = {row['name'] for row in managed}
        user = self._load_user_mcp_configs()
        if any(row.get('name') in reserved for row in user):
            raise ValueError('Managed MCP server names are reserved; configure their installation paths instead')
        # Internal metadata cannot be asserted by a user-supplied server.
        for row in user:
            row.pop('settingsUrl', None)
        return user + managed

    def _load_user_mcp_configs(self) -> list:
        """
        Load MCP server configs with priority:
          1. ~/stella/mcp.json  (supports both mcpServers and mcp_servers keys)
          2. config.json mcp_servers field (fallback)
        """
        import os
        import json as _json

        mcp_json_path = self._mcp_json_path()

        if os.path.exists(mcp_json_path):
            try:
                with open(mcp_json_path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                raw = data.get("mcpServers") or data.get("mcp_servers") or data
                logger.info(f"[ToolManager] Loading MCP config from {mcp_json_path}")
                return _normalize_mcp_configs(raw)
            except Exception as e:
                logger.warning(f"[ToolManager] Failed to read {mcp_json_path}: {e}, falling back to config.json")

        raw = conf().get("mcp_servers", [])
        return _normalize_mcp_configs(raw)

    def _mcp_enabled(self, config):
        default = config.get('enabled', not config.get('disabled', False)) is not False
        return self.capability_settings.enabled('mcp', config.get('name', '<unnamed>'), default=default)

    def _mcp_admitted(self, name, generation):
        with self._mcp_lock:
            config = self._mcp_active_configs.get(name)
            return bool(config is not None and self._mcp_generations.get(name) == generation
                        and self._mcp_enabled(config))

    def _queue_mcp_servers(self, configs):
        """Called under the manager lock; each queued load owns one generation."""
        pending = []
        generations = {}
        for config in configs:
            name = config.get('name', '<unnamed>')
            if not self._mcp_enabled(config):
                continue
            if (self._mcp_active_configs.get(name) == config and
                    self._mcp_status.get(name) in {'pending', 'ready', 'needs_auth'}):
                continue
            if name in self._mcp_active_configs:
                self._teardown_mcp_server(name)
            generation = self._mcp_generations.get(name, 0) + 1
            self._mcp_generations[name] = generation
            self._mcp_active_configs[name] = config
            self._mcp_status[name] = 'pending'
            generations[name] = generation
            pending.append(config)
        if pending:
            threading.Thread(target=self._run_mcp_loader, args=(pending, generations),
                             daemon=True, name='mcp-loader').start()

    def _run_mcp_loader(self, configs, generations):
        from common.runtime_identity import use_identity
        with use_identity(self.identity):
            self._load_mcp_tools_async(configs, generations)

    def _load_mcp_tools(self):
        with self._mcp_lock:
            if self._mcp_loaded:
                return
            configs = self._load_mcp_configs()
            self._mcp_signature = self._read_mcp_json_signature()
            self._queue_mcp_servers(configs)
            self._mcp_loaded = True

    def refresh_mcp_if_changed(self):
        with self._mcp_lock:
            signature = self._read_mcp_json_signature()
            if signature == self._mcp_signature:
                return
            configs = self._load_mcp_configs()
            desired = {cfg.get('name', '<unnamed>'): cfg for cfg in configs if self._mcp_enabled(cfg)}
            old = dict(self._mcp_active_configs)
            for name, cfg in old.items():
                if name not in desired or desired[name] != cfg:
                    self._teardown_mcp_server(name)
            self._queue_mcp_servers([cfg for name, cfg in desired.items() if name not in old or old[name] != cfg])
            self._mcp_signature = signature

    def set_mcp_enabled(self, name, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        with self._mcp_lock:
            configs = {cfg.get('name', '<unnamed>'): cfg for cfg in self._load_mcp_configs()}
            if name not in configs:
                raise ValueError('MCP server is not configured')
            self.capability_settings.set_enabled('mcp', name, enabled)
            if enabled:
                self._queue_mcp_servers([configs[name]])
            else:
                self._teardown_mcp_server(name)
        return enabled

    def call_mcp_tool(
        self, server_name, method, arguments, *, host=False, cancel_event=None, purpose=None
    ):
        import time
        from common.runtime_identity import current_identity

        current = current_identity()
        if (current.user_id or "local-default") != (
            self.identity.user_id or "local-default"
        ):
            raise PermissionError("MCP manager belongs to another user")
        configs = {c["name"]: c for c in self._load_mcp_configs()}
        cfg = configs.get(server_name)
        if cfg is None or not self._mcp_enabled(cfg):
            raise PermissionError("MCP server is disabled or not configured")
        public = cfg.get("agentTools")
        if not host and public is not None and method not in public:
            raise PermissionError("MCP management tool is not available to agents")
        with self._mcp_lock:
            self._queue_mcp_servers([cfg])
        deadline = time.monotonic() + 30
        while True:
            if cancel_event is not None and cancel_event.is_set():
                from agent.protocol.cancel import AgentCancelledError

                raise AgentCancelledError("MCP call cancelled")
            with self._mcp_lock:
                if (
                    not self._mcp_enabled(cfg)
                    or server_name not in self._mcp_active_configs
                ):
                    raise PermissionError("MCP server was disabled")
                status = self._mcp_status.get(server_name)
                if status == "ready":
                    client = self._mcp_registry._clients[server_name]
                    generation = self._mcp_generations[server_name]
                    schema = (
                        getattr(self, "_mcp_schemas", {}).get(server_name, {}).get(method)
                    )
                    break
                if status in ("failed", "needs_auth") or time.monotonic() >= deadline:
                    raise RuntimeError(
                        "MCP server is unavailable; check its installation and connection"
                    )
            threading.Event().wait(0.02)
        if schema is None:
            raise ValueError("MCP tool is not provided by this server")
        tool = next(
            (
                t
                for t in self._mcp_tool_instances.values()
                if t.server_name == server_name and t.remote_name == method
            ),
            None,
        )
        if tool is None:
            from agent.tools.mcp.mcp_tool import McpTool
            from agent.permission.gateway import Capability, register_tool

            tool = McpTool(client, schema, server_name)
            tool._capability_settings = self.capability_settings
            from core.mcp.managed import LOCAL_READS
            local_read = cfg.get("settingsUrl") == "/" + server_name and method in LOCAL_READS
            register_tool(
                tool.name,
                Capability.READ if local_read else Capability.EXTERNAL,
                connection=f"mcp:{server_name}",
                read_only=tool.read_only,
            )
        from agent.runtime.tool_invocation import permission_denial
        from core.mcp.managed import native_user_action

        denial = permission_denial(
            tool.name,
            arguments,
            tool=tool,
            noninteractive=True,
            user_action=native_user_action(host,method,purpose),
        )
        if denial:
            raise PermissionError(denial)
        if not self._mcp_admitted(server_name, generation):
            raise PermissionError("MCP connection was replaced")
        meta = None
        if cfg.get("settingsUrl") == "/" + server_name:
            from core.mcp.authorization import check

            def metadata(name, values):
                reply = client.call_tool_result(name, values, cancel_event=cancel_event)
                return reply["structuredContent"]["value"]

            meta = check(
                server_name,
                method,
                arguments,
                current.user_id or "local-default",
                metadata,
                purpose,
            )
        if not self._mcp_admitted(server_name, generation):
            raise PermissionError("MCP connection was replaced")
        result = client.call_tool_result(
            method, arguments, cancel_event=cancel_event, meta=meta
        )
        import json

        structured = result.get("structuredContent")
        if structured is None:
            structured = json.loads(
                "".join(
                    row.get("text", "")
                    for row in result.get("content", [])
                    if row.get("type") == "text"
                )
            )
        return structured["value"]

    def _teardown_mcp_server(self, server_name):
        with self._mcp_lock:
            self._mcp_generations[server_name] = self._mcp_generations.get(server_name, 0) + 1
            self._mcp_active_configs.pop(server_name, None)
            getattr(self,'_mcp_schemas',{}).pop(server_name,None)
            client = None
            if self._mcp_registry is not None:
                with self._mcp_registry._registry_lock:
                    client = self._mcp_registry._clients.pop(server_name, None)
            for name, tool in list(self._mcp_tool_instances.items()):
                if tool.server_name == server_name:
                    self._mcp_tool_instances.pop(name, None)
                    self._mcp_tool_vectors.pop(name, None)
            self._mcp_status.pop(server_name, None)
            for key, pending in list(self._mcp_pending_clients.items()):
                if key[0] == server_name:
                    self._mcp_pending_clients.pop(key, None)
                    try:
                        pending.shutdown()
                    except Exception:
                        logger.warning('[MCP] Failed to close initializing server %s', server_name)
            if client:
                try:
                    client.shutdown()
                except Exception:
                    logger.warning('[MCP] Failed to close server %s', server_name)

    def _load_mcp_tools_async(self, configs, generations=None):
        from agent.tools.mcp.mcp_client import McpClient, McpClientRegistry
        from agent.tools.mcp.mcp_tool import McpTool
        with self._mcp_lock:
            if self._mcp_registry is None:
                self._mcp_registry = McpClientRegistry()
            registry = self._mcp_registry
            if generations is None:
                generations = {}
                for cfg in configs:
                    name = cfg.get('name', '<unnamed>')
                    self._mcp_active_configs[name] = cfg
                    self._mcp_generations[name] = self._mcp_generations.get(name, 0) + 1
                    generations[name] = self._mcp_generations[name]
        for cfg in configs:
            name = cfg.get('name', '<unnamed>')
            generation = generations[name]
            client = None
            published = False
            try:
                if not self._mcp_admitted(name, generation):
                    continue
                client = McpClient(cfg)
                client.on_authorized = lambda n=name, g=generation: self.reload_mcp_server(n, generation=g)
                with self._mcp_lock:
                    if not self._mcp_admitted(name, generation):
                        continue
                    self._mcp_pending_clients[(name, generation)] = client
                if not client.initialize():
                    with self._mcp_lock:
                        if self._mcp_admitted(name, generation):
                            self._mcp_status[name] = 'needs_auth' if getattr(client, 'needs_auth', False) else 'failed'
                    continue
                schemas = client.list_tools()
                agent_tools = cfg.get('agentTools')
                tools = []
                from agent.permission.gateway import Capability, register_tool
                for schema in schemas:
                    if not schema.get('name') or (agent_tools is not None and schema['name'] not in agent_tools):
                        continue
                    tool = McpTool(client, schema, name)
                    tool._capability_settings = self.capability_settings
                    tool._admission_check = lambda n=name, g=generation: self._mcp_admitted(n, g)
                    if cfg.get('settingsUrl') == '/' + name:
                        tool._managed_invoke = lambda method, arguments, cancel, n=name: self.call_mcp_tool(
                            n, method, arguments, cancel_event=cancel)
                    try:
                        from core.mcp.managed import LOCAL_READS
                        local_read = cfg.get('settingsUrl')=='/'+name and schema['name'] in LOCAL_READS
                        register_tool(tool.name, Capability.READ if local_read else Capability.EXTERNAL, connection=f'mcp:{name}', read_only=tool.read_only,
                                      filesystem_write=name=='elearning' and schema['name']=='sync_files' and cfg.get('settingsUrl')=='/elearning')
                    except ValueError:
                        continue
                    tools.append(tool)
                with self._mcp_lock:
                    if not self._mcp_admitted(name, generation):
                        continue
                    for tool in tools:
                        self._mcp_tool_instances[tool.name] = tool
                    with registry._registry_lock:
                        registry._clients[name] = client
                    if not hasattr(self, '_mcp_schemas'):
                        self._mcp_schemas = {}
                    self._mcp_schemas[name] = {row['name']:row for row in schemas}
                    self._mcp_status[name] = 'ready'
                    published = True
            except Exception:
                with self._mcp_lock:
                    if self._mcp_admitted(name, generation):
                        self._mcp_status[name] = 'failed'
                logger.warning('[MCP] Failed to load server %s', name)
            finally:
                with self._mcp_lock:
                    self._mcp_pending_clients.pop((name, generation), None)
                if client is not None and not published:
                    try:
                        client.shutdown()
                    except Exception:
                        logger.warning('[MCP] Failed to close unselected server %s', name)

    def reload_mcp_server(self, server_name, *, generation=None):
        with self._mcp_lock:
            if generation is not None and not self._mcp_admitted(server_name, generation):
                return
            config = self._mcp_active_configs.get(server_name)
            if config is None or not self._mcp_enabled(config):
                return
            self._teardown_mcp_server(server_name)
            self._queue_mcp_servers([config])

    def list_mcp_status(self):
        return dict(self._mcp_status)

    def mcp_catalog(self):
        """Inventory reads never connect servers or expose connection secrets."""
        with self._mcp_lock:
            configs = {cfg.get('name', '<unnamed>'): cfg for cfg in self._load_mcp_configs()}
            configs = {**self._mcp_active_configs, **configs}
            statuses = self.list_mcp_status()
            tools = list(self._mcp_tool_instances.values())
            result = []
            for name in sorted(set(configs) | set(statuses) | {tool.server_name for tool in tools}):
                config = configs.get(name, {'name': name})
                enabled = self._mcp_enabled(config)
                state = statuses.get(name, 'not_started') if enabled else 'disabled'
                result.append({'name': name, 'transport': str(config.get('type', 'stdio')),
                    'enabled': enabled, 'state': state, **({'settings_url': config['settingsUrl']} if config.get('settingsUrl') else {}), 'tools': sorted([
                        {'name': tool.remote_name, 'description': tool.description}
                        for tool in tools if tool.server_name == name and state == 'ready'
                    ], key=lambda tool: tool['name'])})
            return result

    def sync_mcp_into_agent(self, agent) -> tuple:
        """
        Reconcile a live agent's tool collection with the current MCP tool registry.

        Adds tools that finished loading after the agent was created,
        and removes tools whose MCP server was torn down. Built-in tools
        on the agent are left untouched.

        Handles both representations Stella uses:
          - Agent.tools: list[BaseTool]               (default Agent class)
          - AgentStream.tools: dict[str, BaseTool]    (streaming agent)

        Returns (added_names, removed_names) for logging.
        """
        if agent is None or not hasattr(agent, "tools"):
            return ([], [])

        # Never re-inject MCP tools into a restricted review or briefing agent.
        # The review agent is created with a deliberately reduced, workspace-guarded
        # toolset; silently re-adding configured MCP tools here would bypass that
        # policy boundary (see agent/evolution/executor.py). The flag may live on
        # the agent itself (Agent) or on the wrapping stream executor's .agent.
        if getattr(agent, "_evolution_restricted", False) or getattr(
            getattr(agent, "agent", None), "_evolution_restricted", False
        ) or getattr(agent, "fixed_toolset", False) or getattr(getattr(agent, "agent", None), "fixed_toolset", False):
            return ([], [])

        from agent.tools.mcp.mcp_tool import McpTool
        with self._mcp_lock:
            current = {name: tool for name, tool in self._mcp_tool_instances.items()
                       if tool.is_available()}
        registry_names = set(current.keys())

        agent_tools = agent.tools

        if isinstance(agent_tools, dict):
            agent_mcp_names = {
                name for name, tool in agent_tools.items()
                if isinstance(tool, McpTool)
            }
            replaced = {name for name in registry_names & agent_mcp_names
                        if agent_tools[name].client is not current[name].client}
            added = registry_names - agent_mcp_names | replaced
            removed = agent_mcp_names - registry_names
            if not (added or removed):
                return ([], [])
            for name in added:
                agent_tools[name] = copy.copy(current[name])
            for name in removed:
                agent_tools.pop(name, None)

        elif isinstance(agent_tools, list):
            agent_mcp_names = {
                t.name for t in agent_tools if isinstance(t, McpTool)
            }
            replaced = {tool.name for tool in agent_tools if tool.name in registry_names
                        and isinstance(tool, McpTool) and tool.client is not current[tool.name].client}
            added = registry_names - agent_mcp_names | replaced
            removed = agent_mcp_names - registry_names | replaced
            if not (added or removed):
                return ([], [])
            if removed:
                agent.tools = [
                    t for t in agent_tools
                    if not (isinstance(t, McpTool) and t.name in removed)
                ]
            for name in added:
                agent.tools.append(copy.copy(current[name]))

        else:
            return ([], [])

        return (sorted(added), sorted(removed))

    # ------------------------------------------------------------------
    # On-demand MCP tool retrieval support
    #
    # The vector index and the embedding provider are owned here (singleton,
    # process-wide, aligned with the MCP tool lifecycle). The context-aware
    # selection itself lives in agent.tools.mcp.tool_retrieval, driven by the
    # executor which is the only place that knows the conversation context.
    # ------------------------------------------------------------------

    def count_mcp_tools(self) -> int:
        """Return the number of currently loaded MCP tools."""
        return len(self._mcp_tool_instances)

    def get_mcp_tool_vectors(self) -> dict:
        """Return ``{mcp_tool_name: vector}`` for currently loaded MCP tools.

        Lazily embeds any MCP tools not yet in the cache (MCP servers load
        asynchronously, so tools may appear over time). Returns an empty dict
        when no embedding provider is available or embedding fails — the caller
        then falls back to full injection. Never raises.
        """
        try:
            self._ensure_mcp_tool_vectors()
        except Exception as e:
            logger.debug(f"[ToolManager] MCP tool vector build skipped: {e}")
        return dict(self._mcp_tool_vectors)

    def embed_query(self, text: str):
        """Embed a retrieval query with the shared provider.

        Returns the embedding vector, or None if no provider is available or
        the call fails (caller falls back to full injection). Never raises.
        """
        if not text:
            return None
        provider = self._get_embedding_provider()
        if provider is None:
            return None
        try:
            return provider.embed_query(text)
        except Exception as e:
            logger.debug(f"[ToolManager] query embedding failed: {e}")
            return None

    def _ensure_mcp_tool_vectors(self) -> None:
        """Incrementally embed MCP tools that are not yet cached."""
        # Snapshot to avoid concurrent-mutation while the async loader runs.
        current = dict(self._mcp_tool_instances)
        missing = [name for name in current if name not in self._mcp_tool_vectors]
        if not missing:
            return

        provider = self._get_embedding_provider()
        if provider is None:
            return

        with self._mcp_vector_lock:
            # Re-check under lock: another thread may have filled these in.
            missing = [name for name in current if name not in self._mcp_tool_vectors]
            if not missing:
                return
            texts = [self._mcp_tool_embed_text(current[name]) for name in missing]
            vectors = provider.embed_batch(texts)
            for name, vec in zip(missing, vectors):
                self._mcp_tool_vectors[name] = vec

    @staticmethod
    def _mcp_tool_embed_text(tool) -> str:
        """Build the text that represents an MCP tool for embedding."""
        name = getattr(tool, "name", "") or ""
        description = getattr(tool, "description", "") or ""
        return f"{name}: {description}".strip()

    def _get_embedding_provider(self):
        """Lazily create and cache the shared embedding provider (or None)."""
        if not self._embedding_provider_initialized:
            try:
                from models.embedding import create_default_embedding_provider
                self._embedding_provider = create_default_embedding_provider()
            except Exception as e:
                logger.warning(f"[ToolManager] embedding provider init failed: {e}")
                self._embedding_provider = None
            self._embedding_provider_initialized = True
        return self._embedding_provider

    def create_tool(self, name: str) -> BaseTool:
        """
        Get a new instance of a tool by name.

        :param name: The name of the tool to get.
        :return: A new instance of the tool or None if not found.
        """
        tool_class = self.tool_classes.get(name)
        if tool_class:
            # Create a new instance
            tool_instance = tool_class()
            tool_instance._capability_settings = self.capability_settings

            # Apply configuration if available
            if hasattr(self, 'tool_configs') and name in self.tool_configs:
                tool_instance.config = dict(self.tool_configs[name])

            return tool_instance

        # Fall back to MCP tool instances
        mcp_tool = self._mcp_tool_instances.get(name)
        if mcp_tool:
            # Per-call fields (context, cwd, cancellation) belong to one Agent.
            return copy.copy(mcp_tool)

        return None

    def list_tools(self) -> dict:
        """
        Get information about all loaded tools.

        :return: A dictionary with tool information.
        """
        result = {}
        for name, tool_class in self.tool_classes.items():
            if not self.capability_settings.enabled('tool', name):
                continue
            # Create a temporary instance to get schema
            temp_instance = tool_class()
            result[name] = {
                "description": temp_instance.description,
                "parameters": temp_instance.get_json_schema()
            }

        # Include MCP tool instances
        for name, mcp_tool in list(self._mcp_tool_instances.items()):
            if not mcp_tool.is_available():
                continue
            result[name] = {
                "description": mcp_tool.description,
                "parameters": mcp_tool.params,
            }

        return result

    def shutdown_mcp(self):
        with self._mcp_lock:
            for name in list(self._mcp_active_configs):
                self._teardown_mcp_server(name)
            if self._mcp_registry:
                self._mcp_registry.shutdown_all()
            self._mcp_loaded = False
