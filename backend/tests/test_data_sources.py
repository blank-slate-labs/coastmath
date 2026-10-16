"""Every figure cited in a data file's ``_sources`` links to its primary source.

US data files in ``coastmath/data`` carry their citations in a top-level
``_sources`` list of sections, ``{"section": heading or null, "content": [...]}``.
A string item is a cited figure and a dict item is a table row; each must carry
its own ``http(s)://`` link, so a reader can check the figure without hunting for
a shared reference elsewhere in the file. ``{"note": ...}`` items are prose and
are not checked.

Sections that hold no figures (method notes, implementation limits, usage
descriptions) are skipped by the explicit allowlist below, keyed by data file
name and section heading. Country packs (``tax_regimes/<CC>/<YEAR>.json``) carry
a typed ``sources`` table, checked in ``tests/intl/test_intl_data_integrity.py``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DATA_DIR = Path(__file__).resolve().parents[1] / "coastmath" / "data"
_LINK = re.compile(r"https?://\S+")


def _sections(path: Path) -> list[dict] | None:
    sources = json.loads(path.read_text()).get("_sources")
    if isinstance(sources, list) and sources and all(isinstance(s, dict) and "content" in s for s in sources):
        return sources
    return None


CITED = sorted(path for path in DATA_DIR.glob("*.json") if _sections(path))

# (data file name, section heading) pairs whose content states no figure.
NOTE_SECTIONS: dict[str, set[str]] = {
    "estimated_tax_2026.json": {"Projection and limits"},
    "local_income_tax_2026.json": {"Open items to re-check"},
    "real_estate_tax_rules.json": {"Implementation boundaries"},
    "state_tax_enacted_changes.json": {"Scope and rules"},
    # Method notes, per-state coverage status and flag-off vs flag-on examples; every
    # figure they mention is linked in "Supported states" and "Spec-driven states".
    "state_deduction_rules_2026.json": {"Conventions", "All-state coverage matrix", "Defaults"},
}


def _figure_entries(path: Path) -> list[tuple[str | None, object]]:
    """Return (section, item) for each cited figure: bullets and table rows."""
    skipped = NOTE_SECTIONS.get(path.name, set())
    return [
        (section["section"], item)
        for section in _sections(path)
        if section["section"] not in skipped
        for item in section["content"]
        if not (isinstance(item, dict) and set(item) == {"note"})
    ]


def test_cited_files_are_found():
    names = {path.name for path in CITED}
    assert "tax_brackets_2026.json" in names
    assert not set(NOTE_SECTIONS) - names, "allowlist names a file without _sources"


def test_citations_live_in_the_data_files():
    assert not sorted(DATA_DIR.rglob("*.md")), "cite figures in the data file's _sources, not a document"


@pytest.mark.parametrize("path", CITED, ids=lambda p: p.name)
def test_every_figure_links_to_its_source(path: Path):
    unlinked = [
        f"{path.name} [{section}]: {json.dumps(item, ensure_ascii=False)[:100]}"
        for section, item in _figure_entries(path)
        if not _LINK.search(item if isinstance(item, str) else " ".join(map(str, item.values())))
    ]
    assert not unlinked, "figures without a primary-source link:\n" + "\n".join(unlinked)


@pytest.mark.parametrize("name", sorted(NOTE_SECTIONS))
def test_note_sections_exist(name: str):
    """A renamed heading must not silently widen or orphan the allowlist."""
    headings = {section["section"] for section in _sections(DATA_DIR / name)}
    assert NOTE_SECTIONS[name] <= headings, NOTE_SECTIONS[name] - headings
