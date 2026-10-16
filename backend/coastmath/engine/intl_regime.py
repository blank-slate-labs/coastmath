"""Country tax regimes in the yearly loop.

A year whose residence (``coastmath.engine.residency.resolve_country_for_year``)
is not the US is taxed by that country's regime instead of US federal,
state and local income tax, FICA, NIIT and AMT. This module builds the
evaluator's inputs from the year's state, turns its result into the
``TaxResult`` the simulator settles (the same same-year settlement and
withdrawal fixed point as US tax), and handles country benefits and estate
rules. Approximations, documented for the help article:

- Household investment income (interest, dividends, realized gains, rent,
  cancelled debt) is split between the partners in proportion to their
  cash and taxable balances at the start of the year (joint balances half
  each).
- Pre-tax US payroll deductions do not reduce income abroad; only
  contributions to a country account kind marked deductible do.
- Year-to-date entries, US capital loss carryforwards and US passive loss
  rules do not apply in a country year; a net capital loss is not carried.
- US Social Security and other state pensions are ``government_pension``.
- Wealth uses balances at the start of the year.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from coastmath.engine import household_lifecycle as lifecycle
from coastmath.engine import intl_bridge
from coastmath.engine.account_types import ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES
from coastmath.engine.intl_bridge import RegimeTax
from coastmath.engine.types import AccountInfo, PlanData, SimState, TaxResult

US = intl_bridge.US
#: Tax target kinds measured on US brackets, IRMAA or the ACA.
US_ONLY_TARGET_KINDS = frozenset({"federal_bracket", "irmaa_tier", "aca_fpl_percent"})
WEALTH_KEYS = ("cash", "taxable", "tax_deferred", "tax_free", "real_assets", "primary_home",
               "debts", "primary_home_mortgage")
_US_TAX_FREE_TYPES = ROTH_TYPES | {"hsa", "five_twenty_nine"}


def uses_regimes(plan: PlanData) -> bool:
    """Whether any year of the plan can be taxed outside the US."""
    return plan.tax_country != US or any(
        (period.country or plan.tax_country) != US for period in plan.residency_periods)


def every_year_abroad(plan: Any) -> bool:
    return plan.tax_country != US and all(
        (period.country or plan.tax_country) != US for period in plan.residency_periods)


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    return value.model_dump() if hasattr(value, "model_dump") else dict(value)


def validate_regime_settings(plan: Any) -> None:
    """Reject a retired country, and US-only settings in a plan never taxed in the US.

    A plan that moves to or from the US keeps them; they apply only in US
    years. Accepts engine plan data or a stateless plan request.
    """
    intl_bridge.check_supported_countries(plan)
    if not every_year_abroad(plan):
        return
    problems = []
    if _as_dict(plan.healthcare_settings).get("aca_enabled"):
        problems.append("ACA marketplace coverage")
    tax_settings = _as_dict(plan.tax_settings)
    target = tax_settings.get("tax_target") or {}
    if target.get("kind") in US_ONLY_TARGET_KINDS:
        problems.append("a US tax target (federal bracket, IRMAA tier or ACA income)")
    if ((tax_settings.get("estimated_payments") or {}).get("strategy") or "off") != "off":
        problems.append("US estimated tax payments")
    for rule in plan.priorities:
        if rule.priority_type == "roth_conversion" and rule.conversion_mode == "fill_bracket":
            problems.append("Roth conversions that fill a federal bracket")
        if rule.priority_type == "gain_harvest" and not rule.use_plan_tax_target:
            problems.append("gain harvesting to a federal capital gains bracket")
    if problems:
        raise ValueError(
            "This plan is taxed outside the US in every year, so these US-only settings cannot apply: "
            + "; ".join(dict.fromkeys(problems)) + ". Remove them or add a US residency period.")


# ---------------------------------------------------------------------------
# People, income and balances
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Person:
    person: str  # "self" | "spouse"
    age: int
    alive: bool


def people_this_year(plan: PlanData, state: SimState, year: int) -> tuple[Person, ...]:
    """Everyone on this year's assessment, including someone who dies during it."""
    people = []
    for owner, birth_year in (("self", plan.birth_year), ("spouse", plan.spouse_birth_year)):
        if birth_year is None:
            continue
        until = lifecycle.owner_alive_until(plan, state, owner, year)
        if owner == "spouse" and not lifecycle.enabled(plan) and state.partner_deceased:
            present = state.partner_death_year == year
        elif owner == "self" and lifecycle.enabled(plan) and state.primary_deceased:
            present = False
        else:
            present = until > 0
        if not present:
            continue
        dies = deaths_this_year(plan, state, year)
        people.append(Person(owner, year - birth_year, owner not in dies and until >= 1.0))
    if not people:
        people.append(Person("self", year - plan.birth_year, True))
    return tuple(people)


def deaths_this_year(plan: PlanData, state: SimState, year: int) -> set[str]:
    if lifecycle.enabled(plan):
        return {owner for owner in ("self", "spouse") if lifecycle.death_year(plan, owner) == year}
    return {"spouse"} if state.partner_death_year == year else set()


def filing(people: tuple[Person, ...], filing_status: str) -> str:
    if len(people) > 1 and filing_status.startswith("married_"):
        return "couple"
    return "single"


def account_category(account: AccountInfo, kind: intl_bridge.AccountKind | None) -> str:
    """An account's regime category: its country kind's, or the US type's."""
    if kind is not None:
        return kind.category
    if account.account_type in ("checking", "savings"):
        return "cash"
    if account.account_type in TRADITIONAL_RETIREMENT_TYPES:
        return "tax_deferred"
    if account.account_type in _US_TAX_FREE_TYPES:
        return "tax_free"
    return "taxable"


def _owner_split(owner: str, people: tuple[Person, ...]) -> dict[str, float]:
    names = [person.person for person in people]
    if owner in names:
        return {owner: 1.0}
    if owner == "joint" and len(names) > 1:
        return dict.fromkeys(names, 1.0 / len(names))
    return {names[0]: 1.0}


def investment_shares(state: SimState, people: tuple[Person, ...], balances: dict[str, float]) -> dict[str, float]:
    """Each person's share of household investment income (cash and taxable balances)."""
    totals: dict[str, float] = {}
    for account_id, account in state.accounts.items():
        if account_category(account, state.intl_kinds.get(account_id)) not in ("cash", "taxable"):
            continue
        for person, share in _owner_split(account.owner, people).items():
            totals[person] = totals.get(person, 0.0) + max(0.0, balances.get(account_id, 0.0)) * share
    total = sum(totals.values())
    if total <= 0:
        return {person.person: 1.0 / len(people) for person in people}
    return {person.person: totals.get(person.person, 0.0) / total for person in people}


@dataclass
class IncomeParts:
    """Income by owner and income type; "household" amounts are split by investment share."""

    amounts: dict[str, dict[str, float]] = field(default_factory=dict)

    def add(self, owner: str, income_type: str, amount: float) -> None:
        if amount:
            bucket = self.amounts.setdefault(owner, {})
            bucket[income_type] = bucket.get(income_type, 0.0) + amount

    def by_person(self, people: tuple[Person, ...], shares: dict[str, float]) -> dict[str, dict[str, float]]:
        result: dict[str, dict[str, float]] = {person.person: {} for person in people}
        for owner, incomes in self.amounts.items():
            split = shares if owner == "household" else _owner_split(owner, people)
            for person, share in split.items():
                for income_type, amount in incomes.items():
                    bucket = result[person]
                    bucket[income_type] = bucket.get(income_type, 0.0) + amount * share
        return result


def wealth_balances(
    state: SimState,
    plan: PlanData,
    people: tuple[Person, ...],
    balances: dict[str, float],
    real_values: dict[str, float],
    liability_balances: dict[str, float],
) -> dict:
    """``WealthInputs`` fields as dicts: household totals and each person's share.

    Real assets and debts have no owner in the plan, so they are split
    equally between the partners; joint accounts are split equally too.
    """
    names = [person.person for person in people]
    household = dict.fromkeys(WEALTH_KEYS, 0.0)
    by_person = {name: dict.fromkeys(WEALTH_KEYS, 0.0) for name in names}

    def add(owner: str, key: str, amount: float) -> None:
        household[key] += amount
        for person, share in _owner_split(owner, people).items():
            by_person[person][key] += amount * share

    for account_id, account in state.accounts.items():
        add(account.owner, account_category(account, state.intl_kinds.get(account_id)),
            max(0.0, balances.get(account_id, 0.0)))
    homes = {asset.id for asset in plan.real_assets if asset.is_primary_residence}
    for asset_id, value in real_values.items():
        add("joint", "primary_home" if asset_id in homes else "real_assets", max(0.0, value))
    for liability in plan.liabilities:
        balance = max(0.0, liability_balances.get(liability.id, 0.0))
        add("joint", "primary_home_mortgage" if liability.linked_asset_id in homes else "debts", balance)
    for totals in (household, *by_person.values()):
        liquid = totals["cash"] + totals["taxable"] + totals["tax_deferred"] + totals["tax_free"]
        totals["liquid_net_worth"] = liquid
        totals["net_worth"] = (liquid + totals["real_assets"] + totals["primary_home"]
                               - totals["debts"] - totals["primary_home_mortgage"])
    return {"household": household, "by_person": by_person}


def trade_amounts(state: SimState) -> dict:
    """``TradeInputs`` fields: this year's deposits and withdrawals by account category."""
    purchases: dict[str, float] = {}
    sales: dict[str, float] = {}
    for target, flows in ((purchases, state.deposits_this_year), (sales, state.withdrawals_this_year)):
        for account_id, amount in flows.items():
            account = state.accounts.get(account_id)
            if account is None or amount <= 0:
                continue
            category = account_category(account, state.intl_kinds.get(account_id))
            target[category] = target.get(category, 0.0) + amount
    return {"purchases": purchases, "sales": sales}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class RegimeContext:
    """What stays fixed for a plan across its country years."""

    custom_spec: Any = None
    overrides: dict | None = None

    @classmethod
    def for_plan(cls, plan: PlanData) -> RegimeContext:
        settings = plan.intl_settings or {}
        document = settings.get("custom_regime")
        overrides = {key: settings.get(key) for key in ("wealth_tax", "transaction_tax")}
        return cls(
            custom_spec=intl_bridge.custom_spec(document) if document else None,
            overrides=overrides if any(overrides.values()) else None,
        )


def regime_inflation_factor(country: str, region: str | None, year: int, context: RegimeContext,
                            calendar_inflation: dict[int, float], default_rate: float) -> float:
    """Cumulative plan inflation from the regime spec's base year to ``year``."""
    base = intl_bridge.spec_base_year(country, year, context.custom_spec)
    current = calendar_inflation.get(year, 1.0)
    if base in calendar_inflation:
        return current / calendar_inflation[base]
    first = min(calendar_inflation)
    if base < first:
        return current * (1.0 + default_rate) ** (first - base) / calendar_inflation[first]
    return 1.0


def evaluate_year(
    *,
    country: str,
    region: str | None,
    year: int,
    inflation_factor: float,
    people: tuple[Person, ...],
    filing_unit: str,
    incomes: dict[str, dict[str, float]],
    deductible: dict[str, float],
    benefits: dict[str, dict[str, float]],
    wealth: dict | None,
    trades: dict | None,
    prior: Any,
    context: RegimeContext,
    gain_parts: dict[str, dict[str, float]] | None = None,
) -> RegimeTax:
    # Everyone on this year's assessment files its return, including someone who dies
    # during the year: their income up to death is taxed on that final return.
    # `Person.alive` keeps the survivor meaning (benefits, remembered amounts).
    person_inputs = tuple(
        intl_bridge.make(
            "PersonYear", person=person.person, age=person.age, alive=True,
            income={key: value for key, value in incomes.get(person.person, {}).items() if value},
            deductible_contributions=max(0.0, deductible.get(person.person, 0.0)),
            benefit_amounts=dict(benefits.get(person.person, {})),
            # Only when there is a split, so an evaluator without the field still works.
            **({"capital_gain_parts": gain_parts[person.person]}
               if gain_parts and gain_parts.get(person.person) else {}),
        )
        for person in people
    )
    inputs = intl_bridge.make(
        "RegimeYearInputs",
        country=country, region=region, year=year, inflation_factor=inflation_factor,
        filing=filing_unit, people=person_inputs,
        wealth=intl_bridge.make("WealthInputs", **wealth) if wealth is not None else None,
        trades=intl_bridge.make("TradeInputs", **trades) if trades is not None else None,
        prior_year=prior,
        custom_spec=context.custom_spec if country == intl_bridge.CUSTOM else None,
        overrides=context.overrides,
    )

    # The inputs stay on the result: an estate rule recomputes the death
    # year's return with income deemed at death.
    return replace(intl_bridge.normalize_result(country, intl_bridge.evaluate(inputs)), inputs=inputs)


def with_extra_line(regime: RegimeTax, code: str, label: str, category: str, person: str | None,
                    amount: float) -> RegimeTax:
    """Add an integration-made line (an estate tax at a death) to a year's result."""
    if amount <= 0:
        return regime

    return replace(regime, total=regime.total + amount, lines=(*regime.lines, {
        "code": code, "label": label, "category": category, "person": person, "amount": amount}))


def tax_result(regime: RegimeTax, capital_loss_carryforward: float) -> TaxResult:
    """The settlement view of a country year: no US tax, the regime's total."""
    return TaxResult(
        federal=0.0,
        total_tax=regime.total,
        marginal_rate=regime.marginal_rate,
        agi=regime.taxable_income,
        taxable_income=regime.taxable_income,
        modified_agi=regime.taxable_income,
        deduction_used="none",
        capital_loss_carryforward=capital_loss_carryforward,
        regime=regime,
    )


# ---------------------------------------------------------------------------
# Benefits
# ---------------------------------------------------------------------------

@dataclass
class BenefitState:
    """Benefit history carried across years."""

    started: dict[int, int] = field(default_factory=dict)  # benefit index -> first paid year in the projection
    last_amounts: dict[str, dict[str, float]] = field(default_factory=dict)  # owner -> rule -> amount


@dataclass(frozen=True)
class BenefitPayment:
    owner: str
    rule: str
    label: str
    amount: float
    income_type: str


def benefit_payments(
    plan: PlanData,
    state: SimState,
    year: int,
    *,
    history: BenefitState,
    people: tuple[Person, ...],
    filing_unit: str,
    prior: Any,
    milestone_months: dict[str, int],
) -> list[BenefitPayment]:
    """This year's payments from ``intl_settings.benefits``.

    A benefit starting at a milestone starts once it is reached, at the age
    the owner had then. The year a benefit commences is prorated from the
    start month (the owner's birth month for an age, the milestone's month);
    a benefit already payable the year before the projection's first paid year
    is not. The opening year and a death year are prorated like income streams.
    In the year a partner dies, amounts that depend on the death (a survivor's
    pension, a single person's supplement) start the month after the
    partner's last month alive; before that the rule's amount with the
    partner alive is paid. When the owner's own benefit also commences that
    year, the survivor part uses the full year's own amount (approximation).
    """
    settings = plan.intl_settings or {}
    payments: list[BenefitPayment] = []
    present = {person.person for person in people}
    deaths = deaths_this_year(plan, state, year)
    for index, benefit in enumerate(settings.get("benefits") or []):
        owner = benefit.get("owner", "self")
        birth_year = plan.birth_year if owner == "self" else plan.spouse_birth_year
        birth_month = (plan.birth_month if owner == "self" else plan.spouse_birth_month) or 1
        if birth_year is None or owner not in present:
            continue
        rule = intl_bridge.benefit_rule(benefit["rule"])
        if rule is None:
            continue
        start_age = benefit.get("start_age")
        start_month = birth_month
        milestone_id = benefit.get("start_milestone_id")
        if milestone_id is not None:
            reached = state.triggered_milestone_years.get(str(milestone_id))
            if reached is None or str(milestone_id) not in state.triggered_milestones:
                continue
            start_age = reached - birth_year
            start_month = milestone_months.get(str(milestone_id), 1)
        other = "spouse" if owner == "self" else "self"
        has_spouse = plan.spouse_birth_year is not None
        spouse_alive = None
        if has_spouse:
            spouse_alive = any(person.person == other and person.alive for person in people)
        context = intl_bridge.make(
            "BenefitContext",
            year=year, age=year - birth_year, birth_year=birth_year, birth_month=birth_month,
            start_age=start_age, params=intl_bridge.benefit_params(benefit["rule"], benefit.get("params") or {}),
            inflation_factor=state.inflation_factor, prior_year=prior, filing=filing_unit,
            spouse_alive=spouse_alive, spouse_benefit_amounts=dict(history.last_amounts.get(other, {})),
            owner=owner,
        )
        result = rule.annual_amount(context)
        amount = max(0.0, float(getattr(result, "amount", 0.0) or 0.0))
        # The partner dies this year: until the month after the death the
        # rule pays what it would with the partner alive.
        widowed = has_spouse and other in present and other in deaths
        before_death = _amount_with_partner_alive(rule, context) if widowed else 0.0
        if amount <= 0 and before_death <= 0:
            continue
        first_year = history.started.setdefault(index, year)
        share = state.year_fraction
        if first_year == year and not _paid_year_before(rule, context):
            share = min(share, 1.0 - (start_month - 1) / 12)
        alive_until = lifecycle.owner_alive_until(plan, state, owner, year)
        opening = 1.0 - state.year_fraction
        share = max(0.0, min(share, alive_until - opening))
        paid = amount * share
        if widowed:
            # Survivor amounts start the month after the partner's last month
            # alive, not at the owner's own start month.
            partner_until = lifecycle.owner_alive_until(plan, state, other, year)
            survivor_share = max(0.0, min(1.0, alive_until) - max(opening, partner_until))
            paid = max(0.0, before_death * share + (amount - before_death) * survivor_share)
        if paid <= 0:
            continue
        income_type = str(getattr(getattr(result, "income_type", None), "value",
                                  getattr(result, "income_type", "government_pension")))
        payments.append(BenefitPayment(owner, benefit["rule"], str(getattr(rule, "label", benefit["rule"])),
                                       paid, income_type))
    return payments


def _amount_with_partner_alive(rule: Any, context: Any) -> float:
    """The rule's amount for the year had the partner lived (no survivor amounts)."""

    result = rule.annual_amount(replace(context, spouse_alive=True))
    return max(0.0, float(getattr(result, "amount", 0.0) or 0.0))


def _paid_year_before(rule: Any, context: Any) -> bool:
    """Whether the owner's own benefit was already payable a year earlier.

    The first year a benefit is paid in the projection is its commencement
    only when it was not payable the year before: a benefit that began before
    the projection (or before a year it could not be paid, such as one tested
    on a prior year the projection lacks) pays the full year. Survivor amounts
    are left out, so this tracks the owner's own commencement.
    """

    earlier = replace(context, year=context.year - 1, age=context.age - 1, spouse_benefit_amounts={})
    result = rule.annual_amount(earlier)
    return float(getattr(result, "amount", 0.0) or 0.0) > 0


def remember_benefits(history: BenefitState, payments: list[BenefitPayment], people: tuple[Person, ...]) -> None:
    """Keep the living owners' amounts; a deceased owner's last amounts stay for survivors."""
    living = {person.person for person in people if person.alive}
    current: dict[str, dict[str, float]] = {}
    for payment in payments:
        current.setdefault(payment.owner, {})
        current[payment.owner][payment.rule] = current[payment.owner].get(payment.rule, 0.0) + payment.amount
    for owner in ("self", "spouse"):
        if owner in living:
            history.last_amounts[owner] = current.get(owner, {})


# ---------------------------------------------------------------------------
# Estate
# ---------------------------------------------------------------------------

def death_income_inputs(state: SimState, plan: PlanData, decedent: str, people: tuple[Person, ...] | None) -> dict:
    """Deemed-at-death inputs for an estate rule: the decedent's unrealized gains and deferred balances.

    ``people`` None means the whole estate is the decedent's (the last
    death); otherwise joint accounts and real assets are split equally
    between the partners like the wealth inputs. Of the homes marked as the
    primary residence, the one with the largest gain is ``primary_home``
    (one home can be the exempt principal residence); the others count as
    other real assets. Gains are value less basis, without selling costs or
    depreciation. ``taxable_deferred_balance`` covers tax-deferred country
    account kinds whose withdrawals are income (US accounts keep the US
    heir income tax in the net legacy).
    """
    def share(owner: str) -> float:
        return 1.0 if people is None else _owner_split(owner, people).get(decedent, 0.0)

    gains = {"taxable": 0.0, "real_assets": 0.0, "primary_home": 0.0}
    deferred = 0.0
    for account_id, account in state.accounts.items():
        part = share(account.owner)
        if part <= 0:
            continue
        kind = state.intl_kinds.get(account_id)
        if account_category(account, kind) == "taxable":
            basis = account.cost_basis if account.cost_basis is not None else account.balance
            gains["taxable"] += max(0.0, account.balance - basis) * part
        elif kind is not None and kind.category == "tax_deferred" and kind.withdrawal_taxable:
            deferred += max(0.0, account.balance) * part
    joint = share("joint")
    home_gains = []
    for asset in plan.real_assets:
        value = state.real_asset_values.get(asset.id)
        if not value or value <= 0:
            continue
        basis = state.real_asset_basis.get(asset.id)
        if basis is None:
            basis = asset.adjusted_basis if asset.adjusted_basis is not None else asset.current_value
        gain = max(0.0, value - basis) * joint
        if asset.is_primary_residence:
            home_gains.append(gain)
        else:
            gains["real_assets"] += gain
    if home_gains:
        home_gains.sort(reverse=True)
        gains["primary_home"] = home_gains[0]
        gains["real_assets"] += sum(home_gains[1:])
    return {"unrealized_gains": gains, "taxable_deferred_balance": deferred}


def final_estate_wealth(state: SimState, plan: PlanData, decedent: str) -> dict[str, float]:
    """The final estate by wealth category (``WealthBalances`` fields), from end-of-plan state.

    Everything left is the decedent's, as in :func:`death_income_inputs` with
    ``people`` None. Uses the same mapping as the yearly wealth inputs.
    """
    balances = {account_id: account.balance for account_id, account in state.accounts.items()}
    loans = {liability_id: loan.remaining_balance + loan.accrued_interest
             for liability_id, loan in state.liability_states.items()}
    return wealth_balances(state, plan, (Person(decedent, 0, True),), balances,
                           dict(state.real_asset_values), loans)["household"]


def estate_tax(country: str, region: str | None, year: int, decedent: str, age: int,
               balances: dict[str, float] | None, gross_estate: float, surviving_spouse: bool,
               inflation_factor: float, predeceased_partner: bool = False,
               death_income: dict | None = None, terminal_year: Any = None) -> float:
    """The country's estate or inheritance tax at a death, or 0 without a rule.

    ``predeceased_partner``: the decedent outlived a partner (passed only when true).
    ``death_income`` (:func:`death_income_inputs`) and ``terminal_year`` (the
    death year's evaluator inputs) let a rule tax income deemed at death.
    """
    rule = intl_bridge.estate_rule(country)
    if rule is None:
        return 0.0
    extra: dict[str, Any] = {"predeceased_partner": True} if predeceased_partner else {}
    if death_income:
        extra.update(death_income)
    if terminal_year is not None:
        extra["terminal_year"] = terminal_year
    inputs = intl_bridge.make(
        "EstateInputs", country=country, year=year, decedent=decedent, age=age,
        gross_estate=max(0.0, gross_estate), region=region, surviving_spouse=surviving_spouse,
        inflation_factor=inflation_factor, wealth=balances, **extra,
    )
    return max(0.0, float(rule.estate_tax(inputs)))


def apply_final_estate(legacy: dict, country: str, tax: float) -> dict:
    """Replace the US estate tax in the net legacy with the country's."""
    us_tax = legacy.get("estate_tax", 0.0)
    exclusions = list(legacy.get("exclusions", []))
    exclusions.insert(0, f"The final year is taxed by {country}; its estate rules replace US federal and "
                         "state estate tax (none when the country has no estate or inheritance tax).")
    return {
        **legacy,
        "federal_exemption": 0.0, "dsue_amount": 0.0,
        "federal_taxable_estate": 0.0, "federal_estate_tax": 0.0,
        "state_exemption": 0.0, "state_taxable_estate": 0.0, "state_estate_tax": 0.0,
        "estate_tax": tax,
        "net_legacy": legacy.get("net_legacy", 0.0) + us_tax - tax,
        "net_to_heirs_after_income_tax": legacy.get("net_to_heirs_after_income_tax", 0.0) + us_tax - tax,
        "exclusions": exclusions,
    }
