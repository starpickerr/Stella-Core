"""
Write tool - Write file content
Creates or overwrites files, automatically creates parent directories
"""

import os
from typing import Dict, Any
from pathlib import Path

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.credentials import is_credential_path
from agent.tools.utils.diff import looks_like_line_numbered_block
from agent.tools.utils.file_state import note_write, staleness_warning
from common.utils import expand_path


class Write(BaseTool):
    """Tool for writing file content"""
    
    name: str = "write"
    description: str = "Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Automatically creates parent directories. IMPORTANT: Single write should not exceed 10KB. For large files, create a skeleton first, then use edit to add content in chunks."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (relative or absolute)"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["path", "content"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.memory_manager = self.config.get("memory_manager", None)
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file write operation
        
        :param args: Contains file path and content
        :return: Operation result
        """
        path = args.get("path", "").strip()
        content = args.get("content", "")
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")

        # write replaces the whole file, so echoing read's numbered output here
        # would corrupt every line at once.
        if looks_like_line_numbered_block(content):
            return ToolResult.fail(
                f"Error: content looks like read tool output ('12|content'), not file "
                f"content. Those line-number prefixes are display only - strip them "
                f"before writing {path}."
            )
        
        try:
            # Resolve path (may raise PermissionError for protected locations)
            absolute_path = self._resolve_path(path)

            # Create parent directory (if needed)
            parent_dir = os.path.dirname(absolute_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            # Check before writing - our own write would reset the mtime.
            warning = staleness_warning(absolute_path)

            # Write file
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(content)
            note_write(absolute_path)
            
            # Get bytes written
            bytes_written = len(content.encode('utf-8'))
            
            # Auto-sync to memory database if this is a memory file
            if self.memory_manager and 'memory/' in path:
                self.memory_manager.mark_dirty()
            
            result = {
                "message": f"Successfully wrote {bytes_written} bytes to {path}",
                "path": path,
                "bytes_written": bytes_written
            }
            if warning:
                result["warning"] = warning
            
            return ToolResult.success(result)
            
        except PermissionError as e:
            return ToolResult.fail(f"Error: {str(e) or f'Permission denied writing to {path}'}")
        except Exception as e:
            return ToolResult.fail(f"Error writing file: {str(e)}")
    
    def _resolve_path(self, path: str) -> str:
        """
        Resolve path to absolute path

        :param path: Relative or absolute path
        :return: Absolute path
        :raises PermissionError: if the path targets a protected location
        """
        # Expand ~ to user home directory
        path = expand_path(path)
        if os.path.isabs(path):
            absolute = path
        else:
            absolute = os.path.abspath(os.path.join(self.cwd, path))

        real = os.path.realpath(absolute)

        # Always block the credentials file, mirroring the bash tool's guard.
        # The suffix rule also covers non-home .cow/.env files; the shared guard
        # adds symlink resolution and the /proc environ aliases.
        if real.endswith(os.path.join(".cow", ".env")) or is_credential_path(absolute):
            raise PermissionError("writing to ~/.cow/.env is not allowed")

        # Optional workspace confinement. Off by default to preserve existing
        # behavior; enable via config.json tools.write.restrict_to_workspace.
        if self.config.get("restrict_to_workspace"):
            ws = os.path.realpath(self.cwd)
            if os.path.commonpath([ws, real]) != ws:
                raise PermissionError(
                    f"writing outside the workspace is not allowed: {path}"
                )

        return absolute
