from stella_elearning_test_support import settings, SyncCancelled

BASE = "https://elearning.fudan.edu.cn"
def config(**changes):
    return {**settings.DEFAULTS, "enabled": True, "username": "student", "password": "campus-secret", "courses": ["42"], "request_interval": 0, **changes}


def _capture_cancel(client):
    try:
        client.get("/api/v1/courses")
    except SyncCancelled:
        return "cancelled"
    return "not cancelled"


class FakeCanvas:
    base = BASE

    def __init__(self):
        self.calls = []
        self.rows = {
            "courses": [{"id": 42, "name": "课程"}],
            "discussion_topics": [{"id": 1, "title": "公告", "message": "<p>上课通知</p><script>ignore</script>", "posted_at": "2026-09-08T23:00:00Z"}],
            "assignments": [{"id": 2, "name": "作业", "description": "<p>完整作业说明</p>", "updated_at": "2026-09-08T23:00:00Z",
                             "due_at": "2026-09-10T12:00:00Z", "points_possible": 100,
                             "submission": {"workflow_state": "graded", "graded_at": "2026-09-08T23:00:00Z", "score": 0}}],
            "quizzes": [{"id": 3, "title": "测试", "description": "测试要求", "updated_at": "2026-09-08T23:00:00Z"}],
            "files": [{"id": 4, "display_name": "讲义.pdf", "size": 123, "updated_at": "2026-09-08T23:00:00Z"}],
            "enrollments": [{"id": 5, "grades": {"current_score": 0}}],
        }

    def get(self, path, params=None):
        return {"id": 99}, None

    def list(self, path, params=None):
        self.calls.append((path, params))
        rows = self.rows[path.rsplit("/", 1)[-1]]
        if isinstance(rows, Exception):
            raise rows
        return rows


