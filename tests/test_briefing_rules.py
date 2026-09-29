from agent.briefing.models import EmailMessage, FilterRule, SourceItem
from agent.briefing.rules import decide, filter_candidates


def _item(**extra):
    values = dict(
        id="src-1",
        source="email",
        account_id="default",
        source_id="<msg-1@example.com>",
        thread_id="",
        sender="Ada",
        title="Weekly digest",
        snippet="Nothing urgent",
        occurred_at="2026-09-08T22:00:00Z",
        url="",
        payload={},
    )
    values.update(extra)
    return SourceItem(**values)


def _email(address="ada@example.com", list_id=""):
    return EmailMessage(source_item_id="src-1", sender_email=address, list_id=list_id)


def _rule(**extra):
    values = dict(
        id="rule-1",
        enabled=True,
        source="email",
        action="exclude",
        match_field="sender_domain",
        match_op="eq",
        match_value="spam.example",
        note="",
        created_at="2026-09-09T00:00:00Z",
        updated_at="2026-09-09T00:00:00Z",
    )
    values.update(extra)
    return FilterRule(**values)


def test_builtin_drops_noreply():
    keep, included, reason = decide(
        _item(), _email("noreply@github.com"), []
    )
    assert keep is False
    assert included is False
    assert reason == "noreply"


def test_user_exclude_and_include_override():
    rules = [_rule()]
    keep, _, reason = decide(_item(), _email("bot@spam.example"), rules)
    assert keep is False
    assert reason == "exclude"

    rules.append(
        _rule(
            id="rule-2",
            action="include",
            match_field="sender_email",
            match_op="eq",
            match_value="bot@spam.example",
        )
    )
    keep, included, reason = decide(_item(), _email("bot@spam.example"), rules)
    assert keep is True
    assert included is True
    assert reason == "include"


def test_action_section_from_title():
    kept, filtered = filter_candidates(
        [
            (
                _item(title="请确认合同条款", snippet="今天下午前回复"),
                _email(),
            ),
            (
                _item(
                    id="src-2",
                    source_id="<promo@x>",
                    title="折扣",
                    payload={"list_unsubscribe": True},
                ),
                _email("store@shop.example"),
            ),
        ],
        [],
    )
    assert filtered == 1
    assert len(kept) == 1
    assert kept[0].section == "action"
    assert kept[0].score >= 80
