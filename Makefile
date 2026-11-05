PYTHON ?= .venv/bin/python
DBT := $(abspath .venv/bin/dbt)
export OSS_PULSE_DATA_DIR ?= $(CURDIR)/data
export DBT_PROFILES_DIR := $(CURDIR)/dbt

DAYS ?= 30
END ?=
END_FLAG := $(if $(END),--end-date $(END),)
FORCE ?=
FORCE_FLAG := $(if $(FORCE),--force,)
FIXTURE_DIR := $(CURDIR)/data_fixture

.PHONY: setup setup-python backfill build timed-build test dashboard all lint fixtures verify dagster freshness

setup: setup-python
	cd dashboard && npm ci

setup-python:
	uv venv --python 3.11 .venv
	uv pip install --python $(PYTHON) -r requirements.lock
	uv pip install --python $(PYTHON) --no-deps -e .
	@test -f .env || (umask 077; printf 'GITHUB_TOKEN=%s\n' "$$GITHUB_TOKEN" > .env)

backfill:
	$(PYTHON) -m oss_pulse.cli backfill --days $(DAYS) $(END_FLAG) $(FORCE_FLAG) --workers 6 --record

build:
	cd dbt && $(DBT) seed --quiet
	cd dbt && $(DBT) build --select tag:staging tag:silver
	$(PYTHON) -m oss_pulse.cli enrich --top-n 900
	cd dbt && $(DBT) build
	$(PYTHON) -c "from oss_pulse.reports import record_dbt_tests; record_dbt_tests()"
	$(PYTHON) -m oss_pulse.cli check-contract
	$(PYTHON) -m oss_pulse.cli extracts
	$(PYTHON) -m oss_pulse.cli report

# Same as build, and saves its duration to reports/run_summary.json for the README.
timed-build:
	$(PYTHON) scripts/timed_build.py

lint:
	.venv/bin/ruff check .

test:
	OSS_PULSE_RECORD_TESTS=1 .venv/bin/pytest

freshness:
	cd dbt && $(DBT) source freshness

# The offline path used by CI: fixtures through ingestion, dbt build and the contract.
fixtures:
	rm -rf $(FIXTURE_DIR)
	OSS_PULSE_DATA_DIR=$(FIXTURE_DIR) OSS_PULSE_OFFLINE=1 OSS_PULSE_DBT_TARGET=ci \
		sh scripts/run_fixture_pipeline.sh $(PYTHON) $(DBT)

dashboard:
	cd dashboard && npm run build

verify:
	$(PYTHON) scripts/verify_readme.py

dagster:
	.venv/bin/dagster dev -m oss_pulse.orchestration.definitions

all: backfill build test dashboard verify
