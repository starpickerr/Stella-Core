"""Validate explicit scheduler destinations without changing execution identity."""

from __future__ import annotations

import re
import sys

SUPPORTED = ('web', 'feishu', 'weixin')
PROACTIVE = ('desktop', 'telegram', 'wecom_bot')


def runtime_channel(channel_type):
    # The packaged backend launches app.py as __main__. Importing "app" here
    # creates a second module whose manager is never started.
    for module_name in ('__main__', 'app'):
        module = sys.modules.get(module_name)
        manager = getattr(module, '_channel_mgr', None) if module else None
        if manager is not None:
            channel = manager.get_channel(channel_type)
            if channel is not None:
                return channel
    if channel_type == 'web':
        from channel.channel_factory import create_channel
        return create_channel('web')
    return None


def web_sessions(agent_id=None):
    from agent.registry import get_agent_registry
    from agent.memory import get_conversation_store
    profile = get_agent_registry().get(agent_id)
    store = get_conversation_store(profile.workspace)
    rows = store.list_sessions(channel_type='web', page_size=1000)['sessions']
    return [{'receiver': row['session_id'], 'name': row['title'] or row['session_id']} for row in rows]


def desktop_client_connected():
    """The desktop process records presence when it claims notifications."""
    from agent.scheduler.desktop_notify import desktop_client_seen
    return desktop_client_seen()


def destination_catalog(agent_id=None):
    """Connected proactive channels only. Unconnected channels are omitted."""
    rows = []
    if desktop_client_connected():
        rows.append({'channel_type': 'desktop', 'configured': True, 'ready': True,
                     'status': 'ready', 'recipients': [], 'supports_groups': False})
    telegram = runtime_channel('telegram')
    if telegram is not None:
        rows.append({'channel_type': 'telegram', 'configured': True, 'ready': True,
                     'status': 'ready', 'recipients': [], 'supports_groups': True})
    wecom = runtime_channel('wecom_bot')
    if (wecom is not None and getattr(wecom, 'mode', None) == 'websocket'
            and (getattr(wecom, 'authenticated', False) or getattr(wecom, '_connected', False))):
        rows.append({'channel_type': 'wecom_bot', 'configured': True, 'ready': True,
                     'status': 'ready', 'recipients': [], 'supports_groups': True})
    return rows


def normalize_destination(destination, agent_id=None):
    if not isinstance(destination, dict):
        raise ValueError('delivery must be an object')
    channel_type = destination.get('channel_type')
    if channel_type in PROACTIVE:
        return normalize_proactive_destination(destination, agent_id)
    if channel_type not in SUPPORTED:
        raise ValueError('Scheduled delivery supports desktop, Feishu and Weixin')
    receiver = destination.get('receiver')
    if not isinstance(receiver, str) or not receiver.strip() or len(receiver.strip()) > 200:
        raise ValueError('A destination recipient is required')
    receiver = receiver.strip()
    is_group = destination.get('is_group', False)
    if type(is_group) is not bool:
        raise ValueError('is_group must be true or false')
    if channel_type != 'feishu' and is_group:
        raise ValueError('This destination does not support group delivery')
    channel = runtime_channel(channel_type)
    if channel is None:
        raise ValueError(f'{channel_type} is not connected; connect it on the Channels page')
    if channel_type == 'weixin' and getattr(channel, 'login_status', None) != 'logged_in':
        raise ValueError('Weixin login is required before scheduled delivery')
    receive_id_type = destination.get('receive_id_type') or ('chat_id' if is_group else 'open_id')
    if channel_type == 'feishu':
        if receive_id_type not in ('chat_id', 'open_id', 'user_id', 'union_id', 'email'):
            raise ValueError('Invalid Feishu receive_id_type')
        if is_group != (receive_id_type == 'chat_id'):
            raise ValueError('Feishu groups require chat_id; users require a user identifier')
        if receive_id_type == 'chat_id' and not receiver.startswith('oc_'):
            raise ValueError('Feishu chat_id must start with oc_')
        if receive_id_type == 'open_id' and not receiver.startswith('ou_'):
            raise ValueError('Feishu open_id must start with ou_')
        if receive_id_type == 'email' and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', receiver):
            raise ValueError('A valid Feishu user email is required')
    if channel_type == 'weixin' and not getattr(channel, '_context_tokens', {}).get(receiver):
        raise ValueError('Start a Weixin conversation with this bot before selecting the recipient')
    name = destination.get('receiver_name') or receiver
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError('recipient name must be at most 200 characters')
    result = {'channel_type': channel_type, 'receiver': receiver, 'is_group': is_group,
              'receiver_name': name, 'notify_session_id': receiver}
    if channel_type == 'feishu':
        result['receive_id_type'] = receive_id_type
    return result


def normalize_notification_route(route, agent_id=None):
    """Normalize one new proactive destination. Backup fields are rejected."""
    if route is None:
        return {'primary': None, 'needs_reselect': False}
    if not isinstance(route, dict):
        raise ValueError('notification route must be an object')
    if route.get('backup_enabled') is True or route.get('backup') not in (None,):
        raise ValueError('备用渠道已移除')
    primary = route.get('primary')
    if primary is None:
        return {'primary': None, 'needs_reselect': False}
    channel_type = primary.get('channel_type') if isinstance(primary, dict) else None
    if channel_type not in PROACTIVE:
        raise ValueError('需要重新选择渠道')
    return {'primary': normalize_proactive_destination(primary, agent_id), 'needs_reselect': False}


def normalize_proactive_destination(destination, agent_id=None):
    if not isinstance(destination, dict):
        raise ValueError('delivery must be an object')
    channel_type = destination.get('channel_type')
    if channel_type not in PROACTIVE:
        raise ValueError('需要重新选择渠道')
    receiver = destination.get('receiver')
    if not isinstance(receiver, str) or not receiver.strip() or len(receiver.strip()) > 200:
        raise ValueError('A destination recipient is required')
    receiver = receiver.strip()
    is_group = destination.get('is_group', False)
    if type(is_group) is not bool:
        raise ValueError('is_group must be true or false')
    if channel_type == 'desktop' and is_group:
        raise ValueError('This destination does not support group delivery')
    name = destination.get('receiver_name') or receiver
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError('recipient name must be at most 200 characters')
    return {'channel_type': channel_type, 'receiver': receiver, 'is_group': is_group,
            'receiver_name': name, 'notify_session_id': receiver}


def load_saved_route(route):
    """Keep a stored primary and drop any backup. Legacy channels need a new choice."""
    if not isinstance(route, dict):
        return {'primary': None, 'needs_reselect': False}
    primary = route.get('primary')
    if not isinstance(primary, dict):
        return {'primary': None, 'needs_reselect': False}
    channel_type = primary.get('channel_type')
    return {'primary': primary, 'needs_reselect': channel_type not in PROACTIVE}


def same_notification_route(candidate, saved):
    """Compare user choices while ignoring server-added recipient metadata."""
    if not isinstance(candidate, dict) or not isinstance(saved, dict):
        return False
    def identity(destination):
        if destination is None:
            return None
        if not isinstance(destination, dict):
            return False
        channel = destination.get('channel_type')
        group = destination.get('is_group', False)
        return (channel, destination.get('receiver'), group,
                destination.get('receive_id_type') or ('chat_id' if group else 'open_id') if channel == 'feishu' else None)

    return identity(candidate.get('primary')) == identity(saved.get('primary'))


DESTINATION_FIELDS = ('channel_type', 'receiver', 'receiver_name', 'is_group',
                      'notify_session_id', 'receive_id_type', 'dingtalk_sender_staff_id',
                      'context_token')


def patch_destination(original, patch, agent_id=None):
    action = dict(original)
    source = original.get('execution_session_id') or original.get('notify_session_id')
    if source:
        action['execution_session_id'] = source
    channel_changed = patch.get('channel_type', action.get('channel_type')) != action.get('channel_type')
    if channel_changed:
        for field in DESTINATION_FIELDS:
            action.pop(field, None)
    action.update(patch)
    if any(key in patch and patch[key] != original.get(key) for key in DESTINATION_FIELDS):
        action.update(normalize_destination(action, agent_id))
    return action
