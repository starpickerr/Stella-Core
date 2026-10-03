"""Validate explicit scheduler destinations without changing execution identity."""

from __future__ import annotations

import re

SUPPORTED = ('web', 'feishu', 'weixin')


def runtime_channel(channel_type):
    from app import get_channel_manager
    manager = get_channel_manager()
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


def destination_catalog(agent_id=None):
    result = []
    for name in SUPPORTED:
        channel = runtime_channel(name)
        recipients = web_sessions(agent_id) if name == 'web' else []
        if name == 'weixin' and channel is not None:
            lock = getattr(channel, '_context_tokens_lock', None)
            if lock:
                with lock:
                    tokens = dict(getattr(channel, '_context_tokens', {}) or {})
            else:
                tokens = dict(getattr(channel, '_context_tokens', {}) or {})
            recipients = [{'receiver': key, 'name': key} for key, token in tokens.items() if token]
        result.append({'channel_type': name, 'ready': channel is not None,
                       'recipients': recipients, 'supports_groups': name == 'feishu'})
    return result


def normalize_destination(destination, agent_id=None):
    if not isinstance(destination, dict):
        raise ValueError('delivery must be an object')
    channel_type = destination.get('channel_type')
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
