"""The scenario sync imports its dependencies at module level.

``app.models`` registers the session hooks, and the hooks import the sync
lazily on commit, so no import order reaches a partially initialized module.
Each case imports one module first in a fresh interpreter.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", [
    "app.scenarios.sync",
    "app.models",
    "app.routers.helpers",
    "app.routers.scenarios",
    "app.routers.plans",
])
def test_module_imports_first_in_a_fresh_interpreter(module: str):
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
