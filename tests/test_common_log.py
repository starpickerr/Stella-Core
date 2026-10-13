"""Unit tests for common.log helpers: redaction and get_logger."""
import logging

from common.log import _SecretFilter, _redact, get_logger, logger


def test_redact_masks_field_values_and_bearer():
    text = 'Authorization: Bearer TOPSECRET, password=TOPSECRET, api_key="AKIASECRET"'
    redacted = _redact(text)
    assert "TOPSECRET" not in redacted
    assert "AKIASECRET" not in redacted
    assert "[REDACTED]" in redacted
    assert _redact("prefix Bearer TOPSECRET suffix") == "prefix Bearer [REDACTED] suffix"


def test_redact_masks_standalone_sk_tokens():
    text = "model reply used key sk-abcdefghijklmnopqrstuvwxyz0123456789"
    redacted = _redact(text)
    assert "sk-abcdefghijklmnopqrstuvwxyz0123456789" not in redacted
    assert "sk-[REDACTED]" in redacted


def test_secret_filter_rewrites_log_record():
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1,
        "Authorization: Bearer TOPSECRET, password=TOPSECRET", (), None,
    )
    assert _SecretFilter().filter(record)
    assert "TOPSECRET" not in record.getMessage()


def test_get_logger_shares_handlers_and_redacts(caplog):
    named = get_logger("phase2-probe")
    assert named is not logger
    assert named.name == "log.phase2-probe"

    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level("INFO", logger="log"):
            named.info("token=%s", "LEAKED_SECRET_VALUE")
    finally:
        logger.removeHandler(caplog.handler)

    assert "LEAKED_SECRET_VALUE" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_get_logger_none_returns_root_logger():
    assert get_logger() is logger
    assert get_logger("log") is logger
