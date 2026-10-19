"""Static package settings with Core-owned validation and category revisions."""
from __future__ import annotations

import json
import math
from pathlib import Path

from core.plugins.management import ManagementStore
from core.plugins.manifest import load_manifest
from core.plugins.package_ops import PackageStore


class PluginSettingsService:
    def __init__(self, management: ManagementStore):
        self.management = management
        self.packages = PackageStore(management.root)

    def descriptors(self, plugin_id: str) -> list[dict]:
        current = self.packages.current_package(plugin_id)
        if current is None:
            raise FileNotFoundError('plugin not installed')
        root = Path(current['path']).resolve()
        manifest = load_manifest(root)
        result = []
        for settings_id in manifest['contributes'].get('settings') or []:
            path = (root / 'settings' / f'{settings_id}.json').resolve()
            if not path.is_relative_to(root):
                raise PermissionError('settings resource escapes package')
            if not path.is_file():
                raise ValueError(f'package settings descriptor missing: {settings_id}')
            descriptor = json.loads(path.read_text())
            if (descriptor.get('id') != settings_id or descriptor.get('pluginId') != plugin_id or
                    descriptor.get('scope') != 'user'):
                raise ValueError('invalid settings descriptor identity')
            result.append(descriptor)
        return result

    def descriptor(self, plugin_id: str, settings_id: str) -> dict:
        descriptor = next((item for item in self.descriptors(plugin_id) if item['id'] == settings_id), None)
        if descriptor is None:
            raise KeyError(settings_id)
        return descriptor

    def read(self, plugin_id: str, user_id: str, settings_id: str, category: str) -> dict:
        descriptor = self.descriptor(plugin_id, settings_id)
        if category not in {item['id'] for item in descriptor['categories']}:
            raise ValueError('unknown settings category')
        fields = [field for field in descriptor['fields'] if field['category'] == category]
        saved = self.management.settings(plugin_id, user_id, settings_id, category)
        defaults = {field['key']: field['default'] for field in fields if 'default' in field and not field.get('secret')}
        saved['values'] = {**defaults, **saved['values']}
        saved['secretFields'] = [field['key'] for field in fields if field.get('secret')]
        for secret in saved['secretFields']:
            saved['values'].pop(secret, None)
        return saved

    def save(self, plugin_id, user_id, settings_id, category, changes, *, expected_revision):
        descriptor = self.descriptor(plugin_id, settings_id)
        fields = {field['key']: field for field in descriptor['fields'] if field['category'] == category}
        if not isinstance(changes, dict) or not changes or set(changes) - set(fields):
            raise ValueError('unknown or empty settings changes')
        for key, value in changes.items():
            field = fields[key]
            if field.get('secret'):
                raise ValueError('secret fields require the protected connection service')
            kind = field['type']
            valid = {'string': isinstance(value, str), 'integer': type(value) is int,
                     'number': type(value) in {int, float} and math.isfinite(value),
                     'boolean': type(value) is bool, 'enum': True,
                     'resourceRef': isinstance(value, dict) and set(value) == {'kind', 'id'} and
                                    all(isinstance(part, str) and part for part in value.values())}.get(kind, False)
            if not valid:
                raise ValueError(f'invalid type for {key}')
            rules = field.get('validation') or {}
            if 'enum' in rules and value not in rules['enum']:
                raise ValueError(f'invalid option for {key}')
            if isinstance(value, str):
                if not rules.get('minLength', 0) <= len(value) <= rules.get('maxLength', 65536):
                    raise ValueError(f'invalid length for {key}')
                if rules.get('pattern'):
                    import regex
                    try:
                        if not regex.fullmatch(rules['pattern'], value, timeout=0.05):
                            raise ValueError(f'invalid format for {key}')
                    except TimeoutError:
                        raise ValueError('settings validation exceeded its time budget') from None
            if type(value) in {int, float} and not rules.get('min', -math.inf) <= value <= rules.get('max', math.inf):
                raise ValueError(f'value out of range for {key}')
        self.management.save_settings(plugin_id, user_id, settings_id, category, changes, expected_revision=expected_revision)
        return self.read(plugin_id, user_id, settings_id, category)
