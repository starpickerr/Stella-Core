"""One source registry for desktop, scheduled tasks and Agent tools."""
import sqlite3

from agent.briefing import settings, elearning_settings
from agent.briefing.sources.calendar_agenda import CalendarAgendaSource


def source_key(source):
    return source.name + ":" + source.account_id


def configured_sources():
    sources = settings.email_sources() + elearning_settings.elearning_sources()
    if apple_calendar_connected():
        sources.append(CalendarAgendaSource())
    return sources


def apple_calendar_connected():
    from common.state_dir import calendar_db
    path = calendar_db(ensure=False).with_name("apple_sync.db")
    if not path.is_file():
        return False
    try:
        with sqlite3.connect(str(path), timeout=2) as db:
            row = db.execute("SELECT value FROM settings WHERE key='connected'").fetchone()
        return bool(row and row[0] == "true")
    except sqlite3.Error:
        return False


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
