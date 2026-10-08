PYTHON ?= .venv/bin/python
ISOLATED = $(PYTHON) scripts/run_isolated.py

.PHONY: setup dev lint test test-integration test-e2e eval audit check

setup:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt
	npm --prefix desktop ci
	$(PYTHON) -m playwright install chromium

dev:
	npm --prefix desktop run dev:hot

lint:
	$(ISOLATED) $(PYTHON) -m ruff check --select E4,E7,E9,F agent application bridge channel cli common models scripts tests evals translate voice app.py config.py
	$(ISOLATED) npm --prefix desktop run lint
	$(ISOLATED) npm --prefix desktop run typecheck

test:
	$(ISOLATED) $(PYTHON) -m pytest tests -q

test-integration:
	$(ISOLATED) $(PYTHON) -m pytest tests/test_harness_runtime.py tests/test_briefing_pipeline.py tests/test_security_gateway.py tests/test_scheduler_delivery.py -q

test-e2e:
	$(ISOLATED) $(PYTHON) scripts/ui_check.py

eval:
	$(ISOLATED) $(PYTHON) evals/run.py
	$(ISOLATED) $(PYTHON) scripts/check_dev_policy.py

audit:
	$(PYTHON) scripts/quality_check.py full

check:
	$(PYTHON) scripts/quality_check.py incremental
