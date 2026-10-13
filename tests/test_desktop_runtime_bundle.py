"""Frozen desktop backends must ship runtime data end users cannot install themselves."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _desktop_reqs() -> str:
    return (ROOT / "desktop/build/requirements-desktop.txt").read_text(encoding="utf-8")


def _backend_spec() -> str:
    return (ROOT / "desktop/build/stella-backend.spec").read_text(encoding="utf-8")


def test_desktop_requirements_include_tzdata_and_regex():
    text = _desktop_reqs()
    assert "tzdata" in text
    assert "regex" in text


def test_backend_spec_collects_tzdata_and_certifi_data_files():
    text = _backend_spec()
    assert "collect_data_files('tzdata'" in text or 'collect_data_files("tzdata"' in text
    assert "collect_data_files('certifi'" in text or 'collect_data_files("certifi"' in text


def test_backend_spec_imports_regex_and_tzdata():
    text = _backend_spec()
    assert "'regex'" in text or '"regex"' in text
    assert "'tzdata'" in text or '"tzdata"' in text


def test_backend_spec_ships_subagent_assets():
    text = _backend_spec()
    assert "agent/subagent/assets" in text or "subagent/assets" in text
