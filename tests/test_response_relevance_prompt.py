"""The answer policy reaches ordinary Agent runs and briefing runs."""

from agent.briefing.generator import SYSTEM_PROMPT as BRIEFING_SYSTEM_PROMPT
from unittest.mock import Mock, patch

from agent.chat.session_service import generate_session_title
from agent.memory.summarizer import (
    DREAM_SYSTEM_PROMPT_EN, DREAM_SYSTEM_PROMPT_ZH,
    SUMMARIZE_SYSTEM_PROMPT_EN, SUMMARIZE_SYSTEM_PROMPT_ZH,
)
from agent.prompt.builder import ContextFile, build_agent_system_prompt
from agent.prompt.workspace import _AGENT_TEMPLATE_EN, _AGENT_TEMPLATE_ZH, _RULE_TEMPLATE_EN, _RULE_TEMPLATE_ZH


def test_general_prompt_keeps_one_off_exclusions_out_of_answers_and_memory():
    for language, answer_rule, memory_rule in (
        ("zh", "不要仅为证明遵守要求而复述排除条件", "仅适用于当前请求的排除条件不构成长期记忆"),
        ("en", "Do not repeat an exclusion merely to show compliance", "a one-off exclusion for the current request is not a long-term memory"),
    ):
        prompt = build_agent_system_prompt(
            workspace_dir="/tmp/stella", language=language,
            memory_manager=object(), tools=["memory_search"],
        )
        assert answer_rule in prompt
        assert memory_rule in prompt
        assert answer_rule in build_agent_system_prompt(
            workspace_dir="/tmp/stella", language=language
        )


def test_briefing_prompt_uses_filter_rules_without_relisting_filtered_topics():
    assert "不要仅为了说明规则而在简报正文中复述被过滤的主题或事项" in BRIEFING_SYSTEM_PROMPT


def test_memory_distillation_does_not_make_task_exclusions_durable():
    assert "单次任务的排除条件只用于该任务" in DREAM_SYSTEM_PROMPT_ZH
    assert "an exclusion for one task applies only to that task" in DREAM_SYSTEM_PROMPT_EN


def test_daily_memory_preserves_the_scope_needed_to_continue_a_task():
    assert "并注明只适用于该任务" in SUMMARIZE_SYSTEM_PROMPT_ZH
    assert "不要把它改写成用户的长期偏好" in SUMMARIZE_SYSTEM_PROMPT_ZH
    assert "preserve its task scope" in SUMMARIZE_SYSTEM_PROMPT_EN
    assert "do not rewrite it as an enduring user preference" in SUMMARIZE_SYSTEM_PROMPT_EN


def test_persona_guidance_requires_durable_intent_for_existing_and_new_agents():
    for language, rule, template, workspace_rules in (
        ("zh", "单次任务的限制条件只用于该任务", _AGENT_TEMPLATE_ZH, _RULE_TEMPLATE_ZH),
        ("en", "Keep one-task constraints within that task", _AGENT_TEMPLATE_EN, _RULE_TEMPLATE_EN),
    ):
        prompt = build_agent_system_prompt(
            workspace_dir="/tmp/stella", language=language,
            context_files=[ContextFile("AGENT.md", "# Persona")],
        )
        assert rule in prompt
        assert "稳定偏好" in template if language == "zh" else "stable preference" in template
        assert "任务范围" in workspace_rules if language == "zh" else "task scope" in workspace_rules


def test_title_prompt_targets_the_requested_result_and_preserves_normal_fallback():
    bot = Mock()
    bot.reply_text.return_value = {"content": "出差路线安排", "completion_tokens": 8}
    with patch("bridge.bridge.Bridge") as bridge:
        bridge.return_value.get_bot.return_value = bot
        assert generate_session_title("安排出差路线，不用复述饮食排除条件", "路线已安排") == "出差路线安排"
        prompt = bot.reply_text.call_args.args[0].messages[0]["content"]
        assert "main requested task, topic, or actual result" in prompt
        assert "Treat exclusions and output constraints as boundaries, not title topics" in prompt
        assert "User: 安排出差路线" in prompt
        bot.reply_text.return_value = {"content": "请再问我一次吧", "completion_tokens": 0}
        assert generate_session_title("打开文档") == "打开文档"
