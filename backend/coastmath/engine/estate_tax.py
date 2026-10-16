"""Estate tax calculation — federal and optional state estate taxes.

Computes the estate tax liability at the plan holder's death and the net
legacy after that tax. Federal parameters (basic exclusion amounts, top
rate) are loaded from ``coastmath/data/federal_estate_tax.json``; the basic
exclusion is inflation-indexed beyond the last legislated year.

Heir income taxes use a user-specified effective rate after the marginal
federal estate-tax deduction for income in respect of a decedent. Settlement
costs are user inputs. Scope exclusions (``EstateBreakdown.exclusions``) include
lifetime gifts, generation-skipping transfer tax, state inheritance taxes,
graduated state brackets or exemption cliffs, or the survivor's later
estate when the marital deduction defers tax.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

from coastmath.engine.types import _TAXABLE_TYPES, EstateSettingsData, SimState

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "federal_estate_tax.json"
_COMMUNITY_PROPERTY_PATH = _DATA_PATH.with_name("community_property_states.json")
_DEFAULT_INFLATION = 0.03  # standalone-helper fallback; simulation supplies its calendar path


@lru_cache(maxsize=1)
def _federal_parameters() -> dict:
    with _DATA_PATH.open() as fh:
        raw = json.load(fh)
    return {
        "by_year": {int(year): float(amount) for year, amount in raw["basic_exclusion_by_year"].items()},
        "base_year": int(raw["indexing_base_year"]),
        "top_rate": float(raw["top_rate"]),
    }


_FEDERAL_RATE = _federal_parameters()["top_rate"]


@lru_cache(maxsize=1)
def community_property_states() -> frozenset[str]:
    with _COMMUNITY_PROPERTY_PATH.open() as fh:
        return frozenset(json.load(fh)["states"])


def step_up_joint_accounts(state: SimState, estate_settings: EstateSettingsData, state_code: str | None) -> None:
    """Step up basis in joint taxable accounts at the first spouse's death.

    Opt-in (``joint_account_step_up``) and only with step-up on. Half of a
    spouses' joint account is in the decedent's estate (IRC 2040(b)), so
    only that half takes a market-value basis (IRC 1014(a)). In a community
    property state both halves do (IRC 1014(b)(6)); joint accounts there are
    treated as community property. Like the decedent's own accounts, the
    basis also steps down when the value is below it.
    """
    if not (estate_settings.step_up_basis_on_death and estate_settings.joint_account_step_up):
        return
    full = (state_code or "") in community_property_states()
    for account in state.accounts.values():
        if account.owner != "joint" or account.account_type not in _TAXABLE_TYPES:
            continue
        basis = account.cost_basis if account.cost_basis is not None else account.balance
        account.cost_basis = account.balance if full else 0.5 * basis + 0.5 * account.balance


def _federal_estate_exemption(projection_year: int, inflation_factor: float | None = None) -> float:
    """Return the federal basic exclusion amount for a given year.

    Uses legislated values for known years and inflation-indexes the
    latest legislated amount for later projection years. Years before the
    earliest known value use that earliest value.
    """
    params = _federal_parameters()
    by_year = params["by_year"]
    if projection_year in by_year:
        return by_year[projection_year]
    base_year = params["base_year"]
    if projection_year > base_year:
        factor = inflation_factor if inflation_factor is not None else (1 + _DEFAULT_INFLATION) ** (projection_year - base_year)
        # IRC 2010(c)(3)(B): round to the nearest $10,000 (halves up). The
        # simulation supplies its calendar inflation path, including Monte
        # Carlo draws.
        return math.floor(by_year[base_year] * max(1.0, factor) / 10_000 + 0.5 + 1e-9) * 10_000
    return by_year[min(by_year)]


def _applicable_federal_exemption(estate_settings: EstateSettingsData, year: int, inflation_factor: float | None = None) -> float:
    if estate_settings.custom_federal_exemption_enabled:
        return max(0.0, float(estate_settings.federal_estate_exemption))
    return _federal_estate_exemption(year, inflation_factor)


@dataclass
class EstateBreakdown:
    """Itemised estate result reported to the API and UI.

    Line order avoids double counting: debts and accrued taxes reduce the
    gross estate; settlement costs are deducted before estate tax; estate
    tax is charged on the remaining taxable estate; heir income tax applies
    only to pre-tax balances (less the 691(c) deduction) and is shown after
    the net legacy as a separate distribution-tax line.
    """

    total_assets: float
    total_liabilities: float
    gross_estate: float
    federal_exemption: float
    dsue_amount: float
    federal_taxable_estate: float
    federal_estate_tax: float
    state_exemption: float
    state_taxable_estate: float
    state_estate_tax: float
    estate_tax: float
    net_legacy: float
    marital_deduction_applied: bool
    custom_federal_exemption: bool
    death_year: int
    exclusions: list[str] = field(default_factory=list)
    debts: float = 0.0
    accrued_taxes: float = 0.0  # unpaid income tax settlements and unfunded bills owed at death
    settlement_costs: float = 0.0
    taxable_estate_before_exemptions: float = 0.0
    pretax_balance: float = 0.0
    heir_income_tax_deduction_691c: float = 0.0
    heir_income_tax: float = 0.0
    net_to_heirs_after_income_tax: float = 0.0
    # 529 balances: outside the gross estate (IRC 529(c)(4)) but passed on.
    education_savings_outside_estate: float = 0.0
    # Share of the estate left to charity, deducted under IRC 2055.
    charitable_bequest: float = 0.0
    # Selling costs on real assets (net legacy only).
    selling_costs: float = 0.0
    # Heirs' capital gains tax on unrealized taxable-account gains when
    # basis does not step up at death.
    unrealized_gains: float = 0.0
    heir_capital_gains_tax: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


_EXCLUSIONS = [
    "Heir income tax uses a single effective rate on pre-tax balances (net of the 691(c) deduction); the 10-year distribution schedule and heirs' own brackets are not modeled.",
    "Settlement costs are the user's fixed and percentage assumptions; actual probate fees vary by state and asset type.",
    "Lifetime gifts, generation-skipping transfers and state inheritance taxes are not modeled.",
    "State estate tax uses a single flat rate above the exemption; graduated brackets and exemption cliffs are not modeled.",
]


def calculate_estate_breakdown(
    total_assets: float,
    total_liabilities: float,
    estate_settings: EstateSettingsData,
    year: int,
    *,
    marital_deduction: bool = False,
    partner_death_year: int | None = None,
    same_year_deaths: bool = False,
    accrued_taxes: float = 0.0,
    pretax_balance: float = 0.0,
    calendar_inflation: dict[int, float] | None = None,
    education_savings_balance: float = 0.0,
    real_asset_value: float = 0.0,
    unrealized_gains: float = 0.0,
) -> EstateBreakdown:
    """Compute the itemised estate tax result at the plan holder's death.

    Args:
        total_assets: Liquid balances plus real asset values.
        total_liabilities: Remaining debt, unfunded bills and net tax owed.
        estate_settings: Estate configuration from the plan.
        year: Year of the plan holder's death (final projection year).
        marital_deduction: True when a spouse survives the plan holder; the
            unlimited marital deduction defers federal and conforming state
            estate tax to the survivor's death, which is not projected.
        partner_death_year: Year the partner died earlier in the projection.
            With the portability election, the partner's unused basic
            exclusion (DSUE) is added to the holder's exemption.
        same_year_deaths: True when both spouses die in the final year. The
            household's assets form two estates, each with its own federal
            and state exemption, whether or not portability is elected.
        education_savings_balance: 529 balances inside ``total_assets``,
            excluded from the gross estate (IRC 529(c)(4)) and added back to
            the net legacy after estate tax.
        real_asset_value: Real asset values inside ``total_assets``, which
            ``estate_selling_cost_rate`` applies to.
        unrealized_gains: Taxable-account gains heirs inherit when basis
            does not step up (``heir_capital_gains_rate``).
    """
    # ``total_liabilities`` includes accrued taxes (negative = refund due); report the split.
    debts = total_liabilities - accrued_taxes
    outside_estate = max(0.0, min(education_savings_balance, total_assets))
    gross_estate = max(0.0, total_assets - outside_estate - total_liabilities)
    settlement_costs = min(
        gross_estate,
        max(0.0, float(estate_settings.settlement_cost_fixed))
        + max(0.0, float(estate_settings.settlement_cost_rate)) * gross_estate,
    )
    # IRC 2053: administration and settlement expenses are deducted before tax.
    # IRC 2055: a charitable bequest is deducted too. It is a share of the
    # estate after settlement costs, before estate tax.
    charitable_bequest = min(1.0, max(0.0, float(estate_settings.charitable_bequest_rate))) * max(
        0.0, gross_estate - settlement_costs)
    taxable_base = gross_estate - settlement_costs - charitable_bequest
    factors = calendar_inflation or {}
    federal_exemption = _applicable_federal_exemption(estate_settings, year, factors.get(year))
    two_estates = same_year_deaths and not marital_deduction
    if two_estates:
        # Each spouse's own estate claims its basic exclusion; this is not
        # portability, so no DSUE is reported.
        federal_exemption *= 2

    dsue = 0.0
    if (
        not two_estates
        and partner_death_year is not None
        and estate_settings.portability_election
        and not marital_deduction
    ):
        # Partner's estate passed to the survivor under the marital deduction,
        # so the partner's full basic exclusion was unused. DSUE is fixed at
        # the amount in effect at the first death (26 USC 2010(c)(4)).
        dsue = _applicable_federal_exemption(estate_settings, partner_death_year, factors.get(partner_death_year))

    federal_taxable = 0.0
    federal_tax = 0.0
    state_taxable = 0.0
    state_tax = 0.0
    state_exemption = (
        max(0.0, float(estate_settings.state_estate_exemption))
        * (2 if two_estates else 1)
        if estate_settings.state_estate_tax_enabled
        else 0.0
    )

    def taxes_on(base: float) -> tuple[float, float, float, float]:
        """(federal taxable, federal tax, state taxable, state tax) for a base."""
        base_state_taxable = (
            max(0.0, base - state_exemption) if estate_settings.state_estate_tax_enabled else 0.0
        )
        base_state_tax = base_state_taxable * max(0.0, float(estate_settings.state_estate_tax_rate))
        # IRC 2058: state death taxes paid are deducted from the federal
        # taxable estate.
        base_federal_taxable = max(0.0, base - base_state_tax - federal_exemption - dsue)
        return base_federal_taxable, base_federal_taxable * _FEDERAL_RATE, base_state_taxable, base_state_tax

    if taxable_base > 0 and not marital_deduction:
        federal_taxable, federal_tax, state_taxable, state_tax = taxes_on(taxable_base)

    estate_tax = federal_tax + state_tax
    # Selling real assets to distribute them costs a share of their value;
    # it reduces what heirs receive, not the taxable estate.
    selling_costs = min(
        max(0.0, float(estate_settings.estate_selling_cost_rate)) * max(0.0, real_asset_value),
        max(0.0, taxable_base - estate_tax),
    )
    net_legacy = (gross_estate - settlement_costs - charitable_bequest - estate_tax - selling_costs
                  + outside_estate)

    # Heir income tax on inherited pre-tax balances (income in respect of a
    # decedent). A surviving spouse rolls the accounts over, so nothing is
    # due at this death. IRC 691(c) lets heirs deduct the estate tax
    # attributable to the IRD before paying income tax on it.
    pretax = max(0.0, min(pretax_balance, total_assets))
    deduction_691c = 0.0
    heir_tax = 0.0
    if not marital_deduction and pretax > 0 and estate_settings.heir_income_tax_rate > 0:
        # IRC 691(c): federal estate tax with IRD minus the tax without IRD.
        # State estate tax is not itself deductible under this federal rule,
        # but removing IRD also shrinks the state tax deducted under 2058.
        # https://www.irs.gov/publications/p559 (Estate Tax Deduction)
        deduction_691c = federal_tax - taxes_on(max(0.0, taxable_base - pretax))[1]
        heir_tax = max(0.0, pretax - deduction_691c) * min(1.0, float(estate_settings.heir_income_tax_rate))
    # Without a step-up heirs keep the decedent's basis and pay tax on the
    # gain when they sell (one effective rate, as if sold at once).
    gains = max(0.0, unrealized_gains)
    heir_capital_gains_tax = 0.0
    if not marital_deduction and not estate_settings.step_up_basis_on_death:
        heir_capital_gains_tax = gains * min(1.0, max(0.0, float(estate_settings.heir_capital_gains_rate)))
    exclusions = list(_EXCLUSIONS)
    if two_estates:
        exclusions.insert(
            0,
            "Both spouses die in the same year, so the household's estate is taxed as two estates "
            "with an exemption each; it assumes the assets divide so both exemptions are used.",
        )
    if marital_deduction:
        exclusions.insert(
            0,
            "The estate passes to the surviving spouse under the unlimited marital deduction; "
            "estate tax at the survivor's later death is not projected.",
        )
    return EstateBreakdown(
        total_assets=float(total_assets),
        total_liabilities=float(total_liabilities),
        gross_estate=gross_estate,
        federal_exemption=federal_exemption,
        dsue_amount=dsue,
        federal_taxable_estate=federal_taxable,
        federal_estate_tax=federal_tax,
        state_exemption=state_exemption,
        state_taxable_estate=state_taxable,
        state_estate_tax=state_tax,
        estate_tax=estate_tax,
        net_legacy=net_legacy,
        marital_deduction_applied=marital_deduction,
        custom_federal_exemption=bool(estate_settings.custom_federal_exemption_enabled),
        death_year=year,
        exclusions=exclusions,
        debts=debts,
        accrued_taxes=accrued_taxes,
        settlement_costs=settlement_costs,
        taxable_estate_before_exemptions=max(0.0, taxable_base),
        pretax_balance=pretax,
        heir_income_tax_deduction_691c=deduction_691c,
        heir_income_tax=heir_tax,
        net_to_heirs_after_income_tax=net_legacy - heir_tax - heir_capital_gains_tax,
        education_savings_outside_estate=outside_estate,
        charitable_bequest=charitable_bequest,
        selling_costs=selling_costs,
        unrealized_gains=gains,
        heir_capital_gains_tax=heir_capital_gains_tax,
    )


def calculate_estate_tax(
    total_estate_value: float,
    estate_settings: EstateSettingsData,
    year: int,
    *,
    marital_deduction: bool = False,
    partner_death_year: int | None = None,
) -> float:
    """Calculate combined federal + state estate tax on a gross estate value."""
    if total_estate_value <= 0:
        return 0.0
    return calculate_estate_breakdown(
        total_estate_value,
        0.0,
        estate_settings,
        year,
        marital_deduction=marital_deduction,
        partner_death_year=partner_death_year,
    ).estate_tax


def calculate_net_legacy(
    total_assets: float,
    total_liabilities: float,
    estate_settings: EstateSettingsData,
    final_year: int,
    *,
    marital_deduction: bool = False,
    partner_death_year: int | None = None,
    same_year_deaths: bool = False,
    accrued_taxes: float = 0.0,
    pretax_balance: float = 0.0,
    calendar_inflation: dict[int, float] | None = None,
    education_savings_balance: float = 0.0,
    real_asset_value: float = 0.0,
    unrealized_gains: float = 0.0,
) -> dict:
    """Calculate the net legacy after estate taxes.

    Returns the itemised breakdown as a dict. The keys ``gross_estate``,
    ``estate_tax`` and ``net_legacy`` are stable for existing consumers.
    """
    return calculate_estate_breakdown(
        total_assets,
        total_liabilities,
        estate_settings,
        final_year,
        marital_deduction=marital_deduction,
        partner_death_year=partner_death_year,
        same_year_deaths=same_year_deaths,
        accrued_taxes=accrued_taxes,
        pretax_balance=pretax_balance,
        calendar_inflation=calendar_inflation,
        education_savings_balance=education_savings_balance,
        real_asset_value=real_asset_value,
        unrealized_gains=unrealized_gains,
    ).as_dict()
