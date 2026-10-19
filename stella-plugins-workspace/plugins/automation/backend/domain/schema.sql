-- Automation task rules. Shares automation.db with Core's lease/dispatch/delivery
-- tables (job_runs, job_deliveries, metadata), which Core's AutomationStore owns.
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY, owner_agent_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL,
    next_run_at TEXT, data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_due
    ON tasks(owner_agent_id,owner_user_id,enabled,next_run_at);
