import importlib.util
import sys
from pathlib import Path


domain_root = Path(__file__).resolve().parents[1] / "backend/domain"
spec = importlib.util.spec_from_file_location("stella_bills_domain", domain_root / "__init__.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
