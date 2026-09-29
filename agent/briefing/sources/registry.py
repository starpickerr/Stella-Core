"""One source registry for desktop, scheduled tasks and Agent tools."""
from agent.briefing import settings, elearning_settings


def source_key(source):
    return source.name + ":" + source.account_id


def configured_sources():
    return settings.email_sources() + elearning_settings.elearning_sources()


def public_sources():
    return [{"id": source_key(source), "source": source.name, "account_id": source.account_id,
             "name": getattr(source, "display_name", source.name)} for source in configured_sources()]


def select_sources(available, selectors=None):
    if selectors is None or selectors == ["all"]:
        return list(available)
    if not isinstance(selectors, list) or not selectors or any(not isinstance(value, str) for value in selectors):
        raise ValueError("sources 必须是非空来源列表；省略或 ['all'] 表示全部")
    valid = {source_key(source) for source in available} | {source.name for source in available}
    if any(value not in valid for value in selectors):
        raise ValueError("来源不存在或未配置，请先查询可用来源")
    return [source for source in available if source_key(source) in selectors or source.name in selectors]
