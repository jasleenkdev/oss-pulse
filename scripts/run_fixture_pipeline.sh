#!/bin/sh
# Offline pipeline run over tests/fixtures. No network and no token.
# Usage: run_fixture_pipeline.sh <python> <dbt>
set -eu
PYTHON=$1
DBT=$2
ROOT=$(pwd)

"$PYTHON" -m oss_pulse.cli backfill \
    --days 4 --end-date 2026-03-05 \
    --base-url "file://$ROOT/tests/fixtures/gharchive" \
    --max-attempts 1 --force
"$PYTHON" -m oss_pulse.cli enrich
cd dbt
"$DBT" seed --quiet --target-path "$OSS_PULSE_DATA_DIR/dbt_target"
"$DBT" build --target-path "$OSS_PULSE_DATA_DIR/dbt_target"
cd "$ROOT"
"$PYTHON" -m oss_pulse.cli check-contract
