"""Provider setup errors must survive deferred streaming iteration."""

import pytest

from models.claudeapi.claude_api_bot import ClaudeAPIBot
from models.deepseek.deepseek_bot import DeepSeekBot
from models.doubao.doubao_bot import DoubaoBot
from models.linkai.link_ai_bot import LinkAIBot
from models.mimo.mimo_bot import MimoBot
from models.minimax.minimax_bot import MinimaxBot
from models.moonshot.moonshot_bot import MoonshotBot


@pytest.mark.parametrize("bot_class", [DeepSeekBot, DoubaoBot, LinkAIBot, MimoBot, MinimaxBot, MoonshotBot])
def test_streaming_setup_failure_preserves_original_error(bot_class, monkeypatch):
    bot = bot_class.__new__(bot_class)

    def fail_conversion(_messages):
        raise RuntimeError("offline sentinel")

    monkeypatch.setattr(bot, "_convert_messages_to_openai_format", fail_conversion)
    chunk = next(bot.call_with_tools([], stream=True))

    assert chunk == {"error": True, "message": "offline sentinel", "status_code": 500}


def test_claude_streaming_setup_failure_preserves_original_error(monkeypatch):
    bot = ClaudeAPIBot.__new__(ClaudeAPIBot)

    def fail_stream(_request):
        raise RuntimeError("offline sentinel")

    monkeypatch.setattr(bot, "_handle_stream_response", fail_stream)
    chunk = next(bot.call_with_tools([], stream=True, model="claude-sonnet-4", max_tokens=64))

    assert chunk == {"error": True, "message": "offline sentinel", "status_code": 500}
