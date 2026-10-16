"""Account-type families shared by the engine, schemas and routers.

Employer plans are 401(k), 403(b), 457(b) and 401(a) accounts. A 457(b) is
modeled as a governmental plan (IRC 457(e)(1)(A)): nongovernmental 457(b)
rules are not modeled. Sources for each family's treatment:

- IRC 402(g)(1): one elective deferral limit per person across 401(k) and
  403(b) plans, traditional and Roth combined.
  https://www.irs.gov/retirement-plans/plan-participant-employee/retirement-topics-403b-contribution-limits
- IRC 457(e)(15), 457(b)(2): a separate 457(b) limit that also counts
  employer deferrals, capped at includible compensation.
  https://www.irs.gov/retirement-plans/irc-457b-deferred-compensation-plans
- IRC 415(c), Treas. Reg. 1.415(f)-1(f)(1): the annual additions limit; a
  403(b) is treated as the participant's own plan and is not aggregated with
  a qualified plan of the same employer unless the participant controls it.
- IRC 72(t)(1), 4974(c), 72(t)(9): the 10% additional tax applies to
  qualified plans, 403(b)s and IRAs; a governmental 457(b) is outside
  4974(c), except for amounts rolled in from another plan type (not modeled).
- A 401(a) here is an employer-funded plan (for example a governmental money
  purchase plan): employees make no elective deferrals into it. Mandatory
  employee contributions picked up under IRC 414(h)(2) are not modeled.
"""

from __future__ import annotations

SECTION_401K_TYPES = frozenset({"traditional_401k", "roth_401k"})
SECTION_403B_TYPES = frozenset({"traditional_403b", "roth_403b"})
SECTION_457B_TYPES = frozenset({"traditional_457b", "roth_457b"})
#: Employer contributions only; no employee elective deferral room.
EMPLOYER_ONLY_PLAN_TYPES = frozenset({"traditional_401a"})

TRADITIONAL_EMPLOYER_PLAN_TYPES = frozenset({"traditional_401k", "traditional_403b", "traditional_457b", "traditional_401a"})
ROTH_EMPLOYER_PLAN_TYPES = frozenset({"roth_401k", "roth_403b", "roth_457b"})
EMPLOYER_PLAN_TYPES = TRADITIONAL_EMPLOYER_PLAN_TYPES | ROTH_EMPLOYER_PLAN_TYPES
#: The designated Roth account type in the same plan as a traditional one
#: (IRC 402A); a 401(a) has none.
ROTH_PLAN_COUNTERPART = {
    "traditional_401k": "roth_401k",
    "traditional_403b": "roth_403b",
    "traditional_457b": "roth_457b",
}
#: Plans whose contributions make the owner an "active participant" for the
#: traditional IRA deduction phase-out (IRC 219(g)(5)). An eligible 457(b)
#: deferred compensation plan is expressly not one of them.
IRA_ACTIVE_PARTICIPANT_PLAN_TYPES = EMPLOYER_PLAN_TYPES - SECTION_457B_TYPES

#: One IRC 402(g) elective deferral limit per person.
ELECTIVE_DEFERRAL_402G_TYPES = SECTION_401K_TYPES | SECTION_403B_TYPES
#: Plans that take employee elective deferrals (402(g) or 457(b) limits).
ELECTIVE_DEFERRAL_TYPES = ELECTIVE_DEFERRAL_402G_TYPES | SECTION_457B_TYPES
#: Plans subject to the IRC 415(c) annual additions limit and the IRC
#: 401(a)(17) compensation limit (403(b) through 403(b)(12)(A)(i)).
ANNUAL_ADDITIONS_415C_TYPES = ELECTIVE_DEFERRAL_402G_TYPES | EMPLOYER_ONLY_PLAN_TYPES
#: IRC 415(c) aggregation groups for one person. All 403(b)s aggregate with
#: each other. The engine has no employer identity, so 401(k)s and 401(a)s
#: are conservatively treated as one employer's plans, as 401(k)s already were.
ANNUAL_ADDITIONS_GROUPS = (SECTION_403B_TYPES, SECTION_401K_TYPES | EMPLOYER_ONLY_PLAN_TYPES)

TRADITIONAL_RETIREMENT_TYPES = TRADITIONAL_EMPLOYER_PLAN_TYPES | {"traditional_ira"}
ROTH_TYPES = ROTH_EMPLOYER_PLAN_TYPES | {"roth_ira"}
#: Accounts that can be inherited and carry beneficiary distribution rules.
RETIREMENT_ACCOUNT_TYPES = TRADITIONAL_RETIREMENT_TYPES | ROTH_TYPES
#: Required minimum distributions during the owner's life (IRC 401(a)(9),
#: 457(d)(2)); designated Roth accounts have none from 2024 (SECURE 2.0 s.325).
RMD_TYPES = TRADITIONAL_RETIREMENT_TYPES
#: Withdrawals before 59 1/2 carry the IRC 72(t) 10% additional tax.
EARLY_WITHDRAWAL_PENALTY_TYPES = RETIREMENT_ACCOUNT_TYPES - SECTION_457B_TYPES
#: A 72(t)(2)(A)(iv) series only matters where the 10% applies; from an
#: employer plan it also needs separation from service, which the user asserts.
SEPP_ELIGIBLE_TYPES = TRADITIONAL_RETIREMENT_TYPES & EARLY_WITHDRAWAL_PENALTY_TYPES
#: IRC 72(t)(2)(A)(v): the age-55 separation exception covers distributions
#: from a qualified plan or 403(b) of the employer the person left, never an
#: IRA, and only where the 10% tax applies at all (a governmental 457(b) has none).
RULE_OF_55_TYPES = EMPLOYER_PLAN_TYPES & EARLY_WITHDRAWAL_PENALTY_TYPES
#: Contributions excluded from federal taxable income.
PRE_TAX_CONTRIBUTION_TYPES = TRADITIONAL_RETIREMENT_TYPES | {"hsa"}
#: Owned by one person by law, so never jointly.
INDIVIDUAL_ONLY_ACCOUNT_TYPES = RETIREMENT_ACCOUNT_TYPES | {"hsa"}

#: Plan family names for messages, e.g. "Employer contributions to a Roth 403(b)".
EMPLOYER_PLAN_FAMILY = {
    "traditional_401k": "401(k)", "roth_401k": "401(k)",
    "traditional_403b": "403(b)", "roth_403b": "403(b)",
    "traditional_457b": "457(b)", "roth_457b": "457(b)",
    "traditional_401a": "401(a)",
}


def annual_additions_group(account_type: str) -> frozenset[str]:
    """The IRC 415(c) aggregation group of an account type, or empty if none."""
    return next((group for group in ANNUAL_ADDITIONS_GROUPS if account_type in group), frozenset())
