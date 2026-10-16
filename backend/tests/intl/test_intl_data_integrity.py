"""Integrity checks that run over every pack in `coastmath/data/tax_regimes/` automatically.

CoastMath ships no country packs today; the test-only pack under
`tests/fixtures/tax_regimes/` keeps these checks exercised. A new country pack
is covered by dropping in its data files: each `<YEAR>.json`
must validate as a `RegimeSpec` (which also checks contiguous brackets, rates in
[0, 1], region keys and that every `rule:` reference resolves), name its own
country and year, and give a `source` that is a key of its own `sources` table
for every component it sets explicitly. Every citation links to its primary source.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from coastmath.engine.intl import registry
from coastmath.engine.intl.spec import (
    Bracket,
    Conversion,
    DividendsSpec,
    Meta,
    RegimeSpec,
    Region,
)
from tests.intl_fixture_pack import FIXTURE_COUNTRY, FIXTURE_DIR

PACK_ROOTS = (registry.DATA_DIR, FIXTURE_DIR)
PACK_DIRS = sorted(
    (path for root in PACK_ROOTS if root.is_dir() for path in root.iterdir() if path.is_dir()),
    key=lambda path: path.name,
)
SPEC_FILES = sorted(path for directory in PACK_DIRS for path in directory.glob("*.json"))
# Containers whose figures live in child components (or that carry no figures).
_NO_SOURCE_NEEDED = (RegimeSpec, Meta, Region, Bracket, Conversion, DividendsSpec)
_LINK = re.compile(r"https?://\S+")


def _components_missing_source(value, path: str = "spec") -> list[str]:
    missing: list[str] = []
    if isinstance(value, BaseModel):
        explicit = bool(value.model_fields_set)
        if (
            explicit
            and not isinstance(value, _NO_SOURCE_NEEDED)
            and "source" in type(value).model_fields
            and not getattr(value, "source", None)
        ):
            missing.append(path)
        for name in type(value).model_fields:
            missing += _components_missing_source(getattr(value, name), f"{path}.{name}")
    elif isinstance(value, dict):
        for key, item in value.items():
            missing += _components_missing_source(item, f"{path}[{key}]")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            missing += _components_missing_source(item, f"{path}[{index}]")
    return missing


def test_packs_exist():
    assert FIXTURE_COUNTRY in {path.name for path in PACK_DIRS}


@pytest.mark.parametrize("directory", PACK_DIRS, ids=lambda p: p.name)
def test_pack_directory_layout(directory: Path):
    assert re.fullmatch(r"[A-Z]{2}", directory.name), "pack directories are ISO 3166-1 alpha-2 codes"
    assert directory.name not in {"US", "XX"}
    years = list(directory.glob("*.json"))
    assert years, "every pack needs at least one <YEAR>.json"
    for path in years:
        assert re.fullmatch(r"\d{4}\.json", path.name)


@pytest.mark.parametrize("path", SPEC_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_spec_validates_and_is_sourced(path: Path, fixture_pack):
    raw = json.loads(path.read_text())
    spec = RegimeSpec.model_validate(raw)
    assert spec.meta.country == path.parent.name
    assert spec.meta.base_year == int(path.stem)
    assert spec.meta.approximations, "every pack lists its approximations"

    missing = _components_missing_source(spec)
    assert not missing, f"components without a source: {missing}"

    unknown = sorted(set(spec.source_ids()) - set(spec.sources))
    assert not unknown, f"source ids without a citation in sources: {unknown}"

    for _, layer in spec.all_layers():
        assert layer.brackets, layer.id


@pytest.mark.parametrize("path", SPEC_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_every_citation_links_to_its_source(path: Path, fixture_pack):
    """Each citation carries its own primary-source link, so every figure can be checked."""
    spec = RegimeSpec.model_validate(json.loads(path.read_text()))
    assert spec.sources, "every pack cites its figures"
    unlinked = sorted(key for key, cited in spec.sources.items() if not _LINK.search(cited.citation))
    assert not unlinked, f"citations without a link: {unlinked}"


@pytest.mark.parametrize("directory", PACK_DIRS, ids=lambda p: p.name)
def test_registry_metadata_for_every_pack(directory: Path, fixture_pack, monkeypatch):
    monkeypatch.setattr(registry, "DATA_DIR", directory.parent)
    registry._pack_codes.cache_clear()
    info = registry.get_country(directory.name)
    assert info is not None
    data = info.to_dict()
    assert data["spec_years"] == sorted(int(p.stem) for p in directory.glob("*.json"))
    json.dumps(data)  # route-serializable, including benefit params schemas
    for kind in data["account_kinds"]:
        assert kind["id"].startswith(f"{directory.name}:")
        assert kind["category"] in {"taxable", "tax_deferred", "tax_free", "cash"}
