"""Desktop mailbox settings use /api/email/accounts, not briefing settings."""
from __future__ import annotations

from pathlib import Path


def test_desktop_client_calls_email_accounts_not_briefing_settings():
    client = Path("desktop/src/renderer/src/api/client.ts").read_text(encoding="utf-8")
    assert "/api/email/accounts" in client
    assert "/api/email/accounts/test" in client
    # Product mailbox helpers must not target the legacy briefing settings path.
    assert "briefingRequest('/api/briefings/settings'" not in client
    assert 'briefingRequest("/api/briefings/settings"' not in client


def test_email_account_handlers_are_registered():
    source = Path("channel/desktop/desktop_channel.py").read_text(encoding="utf-8")
    assert "'/api/email/accounts', 'EmailAccountsHandler'" in source
    assert "'/api/email/accounts/test', 'EmailAccountsTestHandler'" in source
    assert "BriefingSettingsHandler = EmailAccountsHandler" in source
