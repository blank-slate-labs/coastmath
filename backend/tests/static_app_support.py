"""A fresh app instance that serves an isolated static build, never backend/static.

`isolated_spa` redirects the build-directory lookup in `app.main`, which is
`os.path.join(os.path.dirname(__file__), "..", "static")` at import time. It
patches `os.path.join` for exactly those arguments, so real path resolution and
file responses stay untouched. If `app/main.py` stops finding its build through
`os.path.join`, this helper must change with it.
"""
from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from app import main

APP_SHELL = '<html>isolated app shell</html>'


def isolated_spa(monkeypatch, tmp_path: Path) -> tuple[Callable[[], FastAPI], Path]:
    """Create `tmp_path/static` (an `assets/` directory and an `index.html` app
    shell) and point `app.main`'s build lookup at it.

    Returns `(load, static)`. `load()` re-executes `app/main.py` and returns a new
    app; call it after preparing `static`, because the module checks at import
    time whether the build exists.
    """
    static = tmp_path / 'static'
    (static / 'assets').mkdir(parents=True)
    (static / 'index.html').write_text(APP_SHELL)
    original_join = os.path.join
    expected = (str(Path(main.__file__).parent), '..', 'static')
    monkeypatch.setattr(os.path, 'join', lambda *parts: str(static) if parts == expected else original_join(*parts))

    def load() -> FastAPI:
        spec = importlib.util.spec_from_file_location('isolated_spa_app', main.__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.app

    return load, static
