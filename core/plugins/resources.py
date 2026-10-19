"""Resolve concrete resource references using public metadata on a bound channel.

Metadata lookup is private to Core and follows a preliminary method/capability
check. A missing filter means the whole user namespace, never an empty scope.
"""
from __future__ import annotations


def invocation_resources(plugin_id, method, payload, user_id, metadata):
    own_user = [{'kind': 'user', 'id': user_id}]
    if plugin_id == 'stella.email' and method in {'fetch_messages', 'get_cursors', 'set_cursors', 'reset_cursors'}:
        account = metadata('get_account', {'account_id': payload.get('account_id')})
        source = account.get('source_account_id')
        if not source:
            raise PermissionError('email source is unavailable')
        return [{'kind': 'folder', 'id': source}]
    if plugin_id == 'stella.elearning' and method in {'fetch', 'fetch_source', 'list_files', 'sync_files'}:
        settings = metadata('get_settings', {})
        courses = payload.get('course_ids')
        if method == 'fetch' and courses == []:
            return own_user
        if courses is None or courses == []:
            courses = settings.get('courses') or []
        if not isinstance(courses, list) or any(not isinstance(course, str) or not course for course in courses):
            raise ValueError('invalid course resources')
        account = settings.get('account_id')
        if not account or any(not course.isdigit() for course in courses):
            # Legacy names/URLs are not account-qualified stable resource IDs.
            return own_user
        return [{'kind': 'course', 'id': f'{account}:{course}'} for course in sorted(set(courses))] or own_user
    return own_user
