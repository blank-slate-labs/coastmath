"""Connects the tax engine to the statutory state deduction rules.

``coastmath.engine.state_deduction_rules`` is a pure evaluator with its own versioned
data. Plans opt in with ``tax_settings.state_deduction_rules``; only states
whose rules the evaluator reports as ``supported`` use it, and every other
state keeps the existing standard deduction and exemption estimate. Importing
lazily keeps the tax engine free of import cycles and lets the engine run
before a rules module is installed (every state is then ``legacy``).
"""
from __future__ import annotations

import importlib
from types import ModuleType

_MODULE = "coastmath.engine.state_deduction_rules"


def evaluator() -> ModuleType | None:
    """The state deduction rules module, or None when it is unavailable."""
    try:
        return importlib.import_module(_MODULE)
    except ModuleNotFoundError as error:
        if error.name != _MODULE:
            raise
        return None


def coverage(state_code: str | None) -> str:
    """supported | not_applicable | legacy | unverified for ``state_code``."""
    if not state_code:
        return "not_applicable"
    module = evaluator()
    if module is None:
        return "legacy"
    return str(module.state_rule_coverage(state_code.upper()))
