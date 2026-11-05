"""Run `make build` and record how long it took."""

import subprocess
import time

from oss_pulse.reports import record_step_seconds

started = time.monotonic()
subprocess.run(["make", "build"], check=True)
record_step_seconds("build", time.monotonic() - started)
