CREATE TABLE IF NOT EXISTS provider_configs (
    provider_config_id TEXT PRIMARY KEY,
    provider_local_id TEXT NOT NULL,
    agent_id TEXT,
    access_mode TEXT,
    display_name TEXT NOT NULL,
    binary_path TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    settings_json TEXT NOT NULL DEFAULT '{}',
    last_probe_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_runs (
    execution_id TEXT PRIMARY KEY,
    provider_config_id TEXT NOT NULL,
    external_session_ref TEXT,
    external_run_ref TEXT,
    adapter_version TEXT,
    policy_digest TEXT,
    workspace_ref TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(provider_config_id) REFERENCES provider_configs(provider_config_id)
);

CREATE INDEX IF NOT EXISTS ext_runs_by_provider ON external_runs(provider_config_id, updated_at);
