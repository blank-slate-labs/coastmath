"""``coastmath`` is the engine package published as open source.

It must stand alone: no import of the ``app`` package or of web,
database, billing or identity libraries.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "coastmath"
SOURCES = sorted(PACKAGE.rglob("*.py"))
THIRD_PARTY = {"numpy", "pandas", "pydantic", "pydantic_core"}


def _imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    return roots


def test_package_is_found():
    assert (PACKAGE / "engine" / "simulator.py") in SOURCES
    assert (PACKAGE / "schemas" / "plan_data_request.py") in SOURCES


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: str(p.relative_to(PACKAGE)))
def test_imports_stay_inside_the_public_package(path: Path):
    outside = _imported_roots(path) - {"coastmath", "__future__"} - THIRD_PARTY - set(sys.stdlib_module_names)
    assert not outside, f"{path.relative_to(PACKAGE)} imports {sorted(outside)}"



ENGINE_GLUE = {p.stem for p in (PACKAGE.parent / "app" / "engine").glob("*.py")} - {"__init__"}
SAVED_SCHEMAS = {p.stem for p in (PACKAGE.parent / "app" / "schemas").glob("*.py")} - {"__init__"}
ENGINE_MODULES = {p.stem for p in (PACKAGE / "engine").iterdir() if p.suffix == ".py" or (p / "__init__.py").exists()}
ENGINE_SCHEMAS = {p.stem for p in (PACKAGE / "schemas").glob("*.py")} - {"__init__"} - SAVED_SCHEMAS
CALLERS = sorted(
    path
    for root in ("app", "coastmath", "tests", "scripts", "business", "migrations", "sqlite_migrations")
    if (PACKAGE.parent / root).is_dir()
    for path in (PACKAGE.parent / root).rglob("*.py")
)


def _stale_engine_imports(path: Path) -> list[str]:
    """Imports that name an engine module or engine schema under ``app``."""
    stale = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            package = node.module in ("app.engine", "app.schemas")
            modules = [f"{node.module}.{alias.name}" for alias in node.names] if package else [node.module]
        else:
            continue
        for module in modules:
            parts = module.split(".")
            if len(parts) < 3 or parts[0] != "app":
                continue
            if (parts[1] == "engine" and parts[2] not in ENGINE_GLUE) or (
                parts[1] == "schemas" and parts[2] in ENGINE_SCHEMAS
            ):
                stale.append(module)
    return stale


def test_engine_modules_and_schemas_are_found():
    assert {"simulator", "intl"} <= ENGINE_MODULES
    assert "plan_converter" in ENGINE_GLUE and not ENGINE_GLUE & ENGINE_MODULES
    assert {"simulation", "plan_data_request", "monte_carlo"} <= ENGINE_SCHEMAS


@pytest.mark.parametrize("path", CALLERS, ids=lambda p: str(p.relative_to(PACKAGE.parent)))
def test_engine_is_imported_from_coastmath(path: Path):
    stale = _stale_engine_imports(path)
    assert not stale, f"{path.relative_to(PACKAGE.parent)} imports {stale}; use coastmath.engine / coastmath.schemas"


def test_app_has_no_engine_alias():
    with pytest.raises(ModuleNotFoundError):
        __import__("app.engine.simulator")
    with pytest.raises(ModuleNotFoundError):
        __import__("app.schemas.simulation")


def test_reintroduced_engine_import_is_caught(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from app.engine.simulator import run_simulation\n"
        "from app.engine import tax_engine, plan_converter\n"
        "from app.schemas.simulation import SimulationResult\n"
        "from app.schemas.plan import PlanRead\n"
        "import app.engine.plan_converter\n"
    )
    assert _stale_engine_imports(sample) == [
        "app.engine.simulator",
        "app.engine.tax_engine",
        "app.schemas.simulation",
    ]


APP_SOURCES = sorted((PACKAGE.parent / "app").rglob("*.py"))


def _private_engine_imports(path: Path) -> list[str]:
    """``coastmath`` names imported under ``app`` that are underscore-private."""
    private = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "coastmath" and any(part.startswith("_") for part in parts[1:]):
                private.append(name)
    return private


def test_app_sources_are_found():
    assert (PACKAGE.parent / "app" / "routers" / "simulation.py") in APP_SOURCES


@pytest.mark.parametrize("path", APP_SOURCES, ids=lambda p: str(p.relative_to(PACKAGE.parent)))
def test_app_imports_only_public_engine_names(path: Path):
    private = _private_engine_imports(path)
    assert not private, f"{path.relative_to(PACKAGE.parent)} imports {private}; give the engine helper a public name"


def test_private_engine_import_is_caught(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from coastmath.engine.sepp import (\n"
        "    calculate_sepp,\n"
        "    _SINGLE_LIFE_TABLE,\n"
        ")\n"
        "from coastmath.schemas.expense import omit_none, _helper as helper\n"
        "import coastmath.engine._internal\n"
        "from app.schemas.plan import _private\n"
        "from coastmath.engine import sepp\n"
    )
    assert _private_engine_imports(sample) == [
        "coastmath.engine.sepp._SINGLE_LIFE_TABLE",
        "coastmath.schemas.expense._helper",
        "coastmath.engine._internal",
    ]
