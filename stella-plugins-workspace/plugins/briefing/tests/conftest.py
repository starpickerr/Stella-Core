import importlib.util
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'backend/domain'
spec = importlib.util.spec_from_file_location('stella_briefing_domain', root / '__init__.py', submodule_search_locations=[str(root)])
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
