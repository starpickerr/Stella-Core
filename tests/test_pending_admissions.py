from channel.desktop.desktop_channel import _pending_admissions


def test_completed_retry_clears_stale_unknown_banner():
    def row(seq, status, content):
        return {"run_id": str(seq), "session_id": "chat", "user_seq": seq,
                "status": status, "user_content": [{"type": "text", "text": content}]}

    rows = [row(5, "completed", "retry"), row(4, "outcome_unknown", "retry"),
            row(3, "outcome_unknown", "still uncertain")]
    assert [entry["run_id"] for entry in _pending_admissions(rows)] == ["3"]
