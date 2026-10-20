"""Load bounded context contributions through installed public services."""
from common.log import logger
from core.plugins.caller import plugin_user_id
from core.plugins.management import default_store
from core.plugins.package_ops import PackageStore
from core.plugins.manifest import load_manifest


def context_sections(language):
    from core.plugins.core_invoke import _domain_invoke
    store = default_store()
    user = plugin_user_id()
    sections = []
    for selection in sorted(PackageStore(store.root).packages.glob('*/current.json')):
        plugin_id = selection.parent.name
        # PackageStore entries are identifiers; all access still goes through
        # managed lifecycle and current authorization, never direct domain files.
        if not store.has_instance(plugin_id, user) or store.instance(plugin_id, user)['intent'] != 'enabled':
            continue
        try:
            package = PackageStore(store.root).current_package(plugin_id)
            manifest = load_manifest(package['path'])
            for contract in manifest['contributes'].get('context') or []:
                if contract not in manifest['contributes'].get('services', []):
                    continue
                result = _domain_invoke(plugin_id, 'get_context', {'language': language})
                if result['status'] == 'succeeded':
                    value = result.get('value') or {}
                    text = value.get('prompt', '')
                    if isinstance(text, str) and text:
                        sections.append(text[:25000])
        except Exception as exc:
            logger.warning('[Plugins] context unavailable for %s: %s', plugin_id, exc)
    return sections
