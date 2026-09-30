"""Desktop model credentials must survive a backend restart."""

import json

import config as config_module


def _load_desktop_config(monkeypatch, data_dir):
    from agent import registry

    monkeypatch.setattr(config_module, "config", config_module.config)
    monkeypatch.setattr(config_module, "get_data_root", lambda: str(data_dir))
    monkeypatch.setattr(registry, "set_agent_registry", lambda value: None)
    monkeypatch.setattr(registry, "get_agent_registry", lambda: None)
    config_module.load_config()


def test_desktop_saved_keys_replace_stale_environment_after_restart(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({
        "agent": False,
        "appdata_dir": "data",
        "linkai_api_key": "new-linkai-key",
        "deepseek_api_key": "new-deepseek-key",
        "open_ai_api_key": "new-openai-key",
    }), encoding="utf-8")
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setenv("LINKAI_API_KEY", "expired-linkai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "expired-deepseek-key")
    monkeypatch.setenv("OPENAI_API_KEY", "expired-openai-key")

    _load_desktop_config(monkeypatch, tmp_path)

    assert config_module.conf()["linkai_api_key"] == "new-linkai-key"
    assert config_module.conf()["deepseek_api_key"] == "new-deepseek-key"
    assert config_module.conf()["open_ai_api_key"] == "new-openai-key"
    assert config_module.os.environ["LINKAI_API_KEY"] == "new-linkai-key"
    assert config_module.os.environ["DEEPSEEK_API_KEY"] == "new-deepseek-key"
    assert config_module.os.environ["OPENAI_API_KEY"] == "new-openai-key"


def test_desktop_cleared_key_does_not_return_from_environment(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({
        "agent": False,
        "appdata_dir": "data",
        "linkai_api_key": "",
    }), encoding="utf-8")
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setenv("LINKAI_API_KEY", "expired-linkai-key")

    _load_desktop_config(monkeypatch, tmp_path)

    assert config_module.conf()["linkai_api_key"] == ""
    assert "LINKAI_API_KEY" not in config_module.os.environ


def test_desktop_custom_provider_ignores_stale_environment(tmp_path, monkeypatch):
    saved = [{"id": "saved", "name": "Saved", "api_key": "new-custom-key"}]
    stale = [{"id": "stale", "name": "Stale", "api_key": "expired-custom-key"}]
    (tmp_path / "config.json").write_text(json.dumps({
        "agent": False,
        "appdata_dir": "data",
        "custom_providers": saved,
    }), encoding="utf-8")
    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setenv("CUSTOM_PROVIDERS", repr(stale))

    _load_desktop_config(monkeypatch, tmp_path)

    assert config_module.conf()["custom_providers"] == saved


def test_source_deployment_keeps_environment_override(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({
        "agent": False,
        "appdata_dir": "data",
        "linkai_api_key": "saved-linkai-key",
    }), encoding="utf-8")
    monkeypatch.delenv("STELLA_DESKTOP", raising=False)
    monkeypatch.setenv("LINKAI_API_KEY", "external-linkai-key")

    _load_desktop_config(monkeypatch, tmp_path)

    assert config_module.conf()["linkai_api_key"] == "external-linkai-key"
    assert config_module.os.environ["LINKAI_API_KEY"] == "external-linkai-key"


def test_models_save_updates_runtime_and_persisted_key(tmp_path, monkeypatch):
    from channel.web.web_channel import ModelsHandler

    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setenv("LINKAI_API_KEY", "expired-linkai-key")
    monkeypatch.setattr("channel.web.web_channel.get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(ModelsHandler, "_reset_bridge", staticmethod(lambda: None))
    monkeypatch.setattr(
        config_module, "config", config_module.Config({"linkai_api_key": "expired-linkai-key"})
    )
    (tmp_path / "config.json").write_text(
        json.dumps({
            "agent": False,
            "appdata_dir": "data",
            "linkai_api_key": "expired-linkai-key",
        }), encoding="utf-8"
    )

    result = json.loads(ModelsHandler()._handle_set_provider({
        "provider_id": "linkai", "api_key": "new-linkai-key"
    }))

    assert result["status"] == "success"
    assert config_module.conf()["linkai_api_key"] == "new-linkai-key"
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["linkai_api_key"] == "new-linkai-key"
    assert config_module.os.environ["LINKAI_API_KEY"] == "new-linkai-key"

    # A new backend process can inherit the old key from its parent.
    monkeypatch.setenv("LINKAI_API_KEY", "expired-linkai-key")
    _load_desktop_config(monkeypatch, tmp_path)
    assert config_module.conf()["linkai_api_key"] == "new-linkai-key"
    assert config_module.os.environ["LINKAI_API_KEY"] == "new-linkai-key"


def test_models_delete_removes_runtime_key(tmp_path, monkeypatch):
    from channel.web.web_channel import ModelsHandler

    monkeypatch.setenv("STELLA_DESKTOP", "1")
    monkeypatch.setenv("LINKAI_API_KEY", "expired-linkai-key")
    monkeypatch.setattr("channel.web.web_channel.get_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(ModelsHandler, "_reset_bridge", staticmethod(lambda: None))
    monkeypatch.setattr(
        config_module, "config", config_module.Config({"linkai_api_key": "expired-linkai-key"})
    )
    (tmp_path / "config.json").write_text(
        json.dumps({"linkai_api_key": "expired-linkai-key"}), encoding="utf-8"
    )

    result = json.loads(ModelsHandler()._handle_delete_provider({"provider_id": "linkai"}))

    assert result["status"] == "success"
    assert config_module.conf()["linkai_api_key"] == ""
    assert json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))["linkai_api_key"] == ""
    assert "LINKAI_API_KEY" not in config_module.os.environ
