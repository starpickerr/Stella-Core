"""Test-only external Email domain access for deterministic IMAP integration."""
import importlib
import importlib.util
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2] / 'MCP/email-mcp/email_mcp'
name = 'stella_email_domain_core_tests'
spec = importlib.util.spec_from_file_location(name, root / '__init__.py', submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules[name] = package
spec.loader.exec_module(package)
imap = importlib.import_module(name + '.imap')
service = importlib.import_module(name + '.service')
EmailService = service.EmailService


def EmailSource(**kwargs):
    config = dict(host='imap.example.test', port=993, user='test@example.test', password='test-secret', folder='INBOX')
    config.update(kwargs)
    if 'opener' in kwargs:
        config.setdefault('account_id', 'default')
    return imap.EmailSource(**config)
