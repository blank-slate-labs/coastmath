"""The open-source app never imports a hosting plug-in.

Hosted behavior reaches open-source code only through the extension points:
``app.plugins`` on the server and ``src/extensions`` in the planner. The
plug-in's own code and tests live in ``backend/business``,
``backend/tests/business`` and ``frontend/src/business``.
"""
import ast
import re
from pathlib import Path

import pytest

from app import plugins

BACKEND = Path(__file__).resolve().parents[1]
PLUGIN = "business"
SOURCES = sorted(path for package in ("app", "coastmath", "tests") for path in (BACKEND / package).rglob("*.py")
                 if PLUGIN not in path.relative_to(BACKEND).parts)
PLANNER = BACKEND.parent / "frontend" / "src"
PLANNER_IMPORT = re.compile(r"""(?:from\s+|import\s*\(\s*|vi\.mock\(\s*)["']@/business/""")


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


def test_sources_are_found():
    assert BACKEND / "app" / "plugins.py" in SOURCES
    assert BACKEND / "tests" / "conftest.py" in SOURCES


@pytest.mark.parametrize("path", SOURCES, ids=lambda path: str(path.relative_to(BACKEND)))
def test_open_source_backend_never_imports_the_plugin(path):
    assert PLUGIN not in imported_roots(path)


def test_default_plugin_is_only_the_package_beside_app(tmp_path, monkeypatch):
    stray = tmp_path / "elsewhere"
    stray.mkdir()
    (stray / f"{PLUGIN}.py").write_text("def register(extensions): raise AssertionError('loaded a stray module')\n")
    monkeypatch.syspath_prepend(str(stray))
    monkeypatch.delenv("COASTMATH_PLUGINS", raising=False)
    monkeypatch.setattr(plugins, "PACKAGE_DIR", tmp_path / "backend")
    assert plugins.plugin_names() == []
    (tmp_path / "backend" / PLUGIN).mkdir(parents=True)
    (tmp_path / "backend" / PLUGIN / "__init__.py").write_text("")
    assert plugins.plugin_names() == [PLUGIN]
    monkeypatch.setenv("COASTMATH_PLUGINS", "")
    assert plugins.plugin_names() == []
    monkeypatch.setenv("COASTMATH_PLUGINS", " one, two ,")
    assert plugins.plugin_names() == ["one", "two"]


def test_planner_never_imports_the_hosting_package():
    if not PLANNER.is_dir():
        pytest.skip("No planner source beside this backend")
    offenders = [str(path.relative_to(PLANNER)) for path in sorted(PLANNER.rglob("*.ts*"))
                 if path.relative_to(PLANNER).parts[0] != PLUGIN and PLANNER_IMPORT.search(path.read_text())]
    assert offenders == []
