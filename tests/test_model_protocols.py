import sqlite3
from types import SimpleNamespace

import pytest

from agent.runtime.run_record import RunRecord
from bridge.agent_bridge import AgentLLMModel
from common.runtime_identity import identity_scope
from models.provider_config import resolve_binding, validate_provider_ready
from models.protocols import OpenAIResponsesAdapter


def _config():
    return {
        "bot_type": "custom:a", "model": "same-model",
        "custom_providers": [
            {"id": "a", "name": "First", "api_key": "first-key",
             "api_base": "https://first.example/v1", "protocol_id": "openai_chat"},
            {"id": "b", "name": "Second", "api_key": "second-key",
             "api_base": "https://second.example/v1", "protocol_id": "openai_responses"},
        ],
    }


def test_same_model_name_keeps_provider_endpoint_and_protocol(monkeypatch):
    cfg = _config()
    monkeypatch.setattr("bridge.agent_bridge.conf", lambda: cfg)
    monkeypatch.setattr("models.provider_config.conf", lambda: cfg)
    model = AgentLLMModel(None)
    first = model.bot
    assert first.provider.provider_id == "custom:a"
    assert first.provider.api_base == "https://first.example/v1"
    assert first.protocol_id == "openai_chat"
    model.set_session_override("custom:b", "same-model")
    second = model.bot
    assert second is not first
    assert second.provider.api_key == "second-key"
    assert second.protocol_id == "openai_responses"
    model.set_session_override(None, None)
    assert model.bot.provider.provider_id == "custom:a"


def test_session_provider_does_not_inherit_global_protocol_override(monkeypatch):
    cfg = _config()
    cfg["chat_protocol_id"] = "openai_responses"
    monkeypatch.setattr("bridge.agent_bridge.conf", lambda: cfg)
    monkeypatch.setattr("models.provider_config.conf", lambda: cfg)
    model = AgentLLMModel(None)
    assert model.bot.protocol_id == "openai_responses"
    model.set_session_override("custom:b", "same-model")
    assert model.bot.protocol_id == "openai_responses"
    model.set_session_override("custom:a", "same-model")
    assert model.bot.protocol_id == "openai_responses"  # same provider as the global binding
    cfg["bot_type"] = "custom:b"
    model.set_session_override("custom:a", "same-model")
    assert model.bot.protocol_id == "openai_chat"


def test_binding_is_fixed_for_one_run(monkeypatch):
    cfg = _config()
    monkeypatch.setattr("bridge.agent_bridge.conf", lambda: cfg)
    monkeypatch.setattr("models.provider_config.conf", lambda: cfg)
    monkeypatch.setattr("agent.runtime.run_record.RunRecord",
                        lambda: SimpleNamespace(set_model_binding=lambda *_args: None))
    model = AgentLLMModel(None)
    with identity_scope(run_id="first-run"):
        first = model.bot
        cfg["bot_type"] = "custom:b"
        cfg["model"] = "changed-model"
        assert model.bot is first
        assert model.model == "same-model"
    with identity_scope(run_id="second-run"):
        assert model.bot.provider.provider_id == "custom:b"
        assert model.model == "changed-model"


def test_protocol_override_requires_explicit_endpoint():
    cfg = {"bot_type": "chatGPT", "model": "example", "open_ai_api_key": "secret"}
    with pytest.raises(ValueError, match="explicit API base"):
        resolve_binding("openai", "example", "anthropic_messages", cfg)


def test_one_provider_can_bind_two_protocols_to_same_endpoint():
    cfg = _config()
    provider, default = resolve_binding("custom:b", "same-model", config=cfg)
    _, alternate = resolve_binding("custom:b", "same-model", "openai_chat", cfg)
    assert provider.api_base == "https://second.example/v1"
    assert default.protocol_id == "openai_responses"
    assert alternate.protocol_id == "openai_chat"


def test_explicit_remote_provider_requires_key():
    cfg = _config()
    cfg["custom_providers"][1]["api_key"] = ""
    provider, _ = resolve_binding("custom:b", "same-model", config=cfg)
    with pytest.raises(ValueError, match="API key"):
        validate_provider_ready(provider)


def test_responses_refuses_provider_specific_state():
    provider, _ = resolve_binding("custom:b", "same-model", config=_config())
    adapter = OpenAIResponsesAdapter(provider)
    with pytest.raises(ValueError, match="thinking"):
        adapter._input([{"role": "assistant", "content": [
            {"type": "thinking", "thinking": "opaque"}]}])


def test_responses_preserves_encrypted_reasoning_for_tool_continuation():
    provider, _ = resolve_binding("custom:b", "same-model", config=_config())
    adapter = OpenAIResponsesAdapter(provider)
    opaque = {"type": "reasoning", "id": "rs-1", "summary": [],
              "encrypted_content": "encrypted"}
    adapter._response({"output": [opaque, {"type": "function_call", "id": "fc-1",
        "call_id": "call-1", "name": "todos", "arguments": "{}"}]})
    items = adapter._input([{"role": "assistant", "content": [{"type": "tool_use",
        "id": "call-1", "name": "todos", "input": {}}]}])
    assert items[0] == opaque
    assert items[1]["call_id"] == "call-1"


def test_responses_encodes_tool_results_and_normalizes_stream(monkeypatch):
    provider, binding = resolve_binding("custom:b", "same-model", config=_config())
    adapter = OpenAIResponsesAdapter(provider)
    recorded = {}

    def fake_request(_self, **kwargs):
        recorded.update(kwargs)
        return iter([
            {"type": "response.output_item.added", "output_index": 0,
             "item": {"type": "function_call", "id": "fc-1", "call_id": "call-1", "name": "todos"}},
            {"type": "response.function_call_arguments.delta", "output_index": 0,
             "delta": '{"action":'},
            {"type": "response.function_call_arguments.done", "output_index": 0,
             "arguments": '{"action":"list"}'},
            {"type": "response.completed", "response": {"usage": {"input_tokens": 3}}},
        ])

    monkeypatch.setattr("models.protocols.OpenAIHTTPClient._request", fake_request)
    messages = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "old-call",
                                            "name": "todos", "input": {"action": "list"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "old-call",
                                       "content": "[]"}]},
    ]
    chunks = list(adapter.call_with_tools(messages, tools=[{"name": "todos",
        "description": "List todos", "input_schema": {"type": "object", "properties": {}}}],
        stream=True, model=binding.model_id))
    assert recorded["path"] == "/responses"
    assert recorded["api_base"] == "https://second.example/v1"
    assert "timeout" in recorded
    assert recorded["payload"]["input"][-1] == {
        "type": "function_call_output", "call_id": "old-call", "output": "[]"}
    calls = [part for chunk in chunks for part in chunk["choices"][0].get("delta", {}).get("tool_calls", [])]
    assert calls[0]["id"] == "call-1"
    assert "".join(part.get("function", {}).get("arguments", "") for part in calls) == '{"action":"list"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"]["prompt_tokens"] == 3


def test_run_record_stores_binding_without_credentials(tmp_path):
    store = RunRecord(tmp_path / "runs.db")
    store.create("run-1")
    store.set_model_binding("run-1", "custom:b", "openai_responses", "same-model")
    with sqlite3.connect(store.path) as db:
        row = db.execute("SELECT provider_id,protocol_id,model_id FROM runs").fetchone()
    assert row == ("custom:b", "openai_responses", "same-model")
