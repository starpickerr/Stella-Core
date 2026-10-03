"""Keep completed scheduled output in the user's run directory for delivery retries."""

from pathlib import Path

from common.state_dir import runs_dir


def load_output(store, job_run_id):
    if not store or not job_run_id or not hasattr(store, "get_execution_ref"):
        return None
    path = store.get_execution_ref(job_run_id)
    if path:
        return Path(path).read_text(encoding="utf-8")
    return None


def save_output(store, job_run_id, content):
    if not store or not job_run_id or not hasattr(store, "record_execution_ref"):
        return
    path = runs_dir(ensure=True) / f"job-{job_run_id}.txt"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(str(content), encoding="utf-8")
    temporary.replace(path)
    store.record_execution_ref(job_run_id, path)
