"""Which wage bases a payroll deduction expense reduces.

A payroll deduction expense is either ``pre_tax`` or ``after_tax``. Its
optional ``payroll_tax_elections`` override, base by base, whether the amount
reduces federal taxable wages, state taxable wages, local taxable wages and
FICA (Social Security and Medicare) wages.

The defaults reproduce the engine's behavior before elections existed:
pre-tax reduces federal, state and local wages but not FICA wages (a 401(k)
or 403(b) deferral, IRC 3121(a)(5) and (v)(1)(A)); after-tax reduces none.
A section 125 cafeteria-plan premium reduces FICA wages too (IRC
3121(a)(5)(G)), so it is entered as pre-tax with the FICA election on.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

WAGE_BASES = ("federal", "state", "local", "fica")


@dataclass(frozen=True)
class PayrollWageReductions:
    federal: bool
    state: bool
    local: bool
    fica: bool


def payroll_wage_reductions(treatment: str | None, elections: Mapping | None) -> PayrollWageReductions:
    """The wage bases the deduction reduces, explicit elections first."""
    pre_tax = treatment != "after_tax"  # missing values keep the legacy pre-tax contract
    defaults = {"federal": pre_tax, "state": pre_tax, "local": pre_tax, "fica": False}
    chosen = {base: (bool(elections[base]) if elections and elections.get(base) is not None else default)
              for base, default in defaults.items()}
    return PayrollWageReductions(**chosen)
