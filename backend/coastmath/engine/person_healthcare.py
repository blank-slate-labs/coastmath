"""Per-person medical costs from explicit coverage and budget assumptions."""
from dataclasses import replace

from coastmath.engine.healthcare import (
    calculate_medicare_premiums,
    medicare_cost_factor,
    part_a_premium_monthly,
)
from coastmath.engine.household_lifecycle import (
    longevity_end_month_index,
    owner_alive_until,
)
from coastmath.schemas.healthcare_settings import HealthcareSettings


def validate_person_healthcare_plan(plan):
    raw = plan.healthcare_settings
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump(mode="json")
    if not raw or not raw.get("persons"):
        return
    settings = HealthcareSettings.model_validate(raw)
    if not settings.enabled:
        return
    for person in settings.persons:
        if person.owner == "spouse" and plan.spouse_birth_year is None:
            raise ValueError("A spouse health override requires the spouse's birth date")
        care = person.long_term_care
        if care and care.months_before_longevity is not None and person.owner == "spouse" and plan.spouse_life_expectancy is None:
            raise ValueError("An LTC budget relative to longevity requires that person's longevity")
        if care and care.amount_reference_year not in {None, plan.start_year} and care.inflation_rate is None:
            raise ValueError("An LTC amount reference year other than the plan start requires an explicit inflation rate")


def overrides(settings):
    return {person["owner"]: person for person in settings.persons}


def lookback_filing_status(settings, state, year, start_year, current):
    """IRMAA uses the filing status of the lookback return, including widowhood."""
    if year in state.filing_status_history:
        return state.filing_status_history[year]
    if year == start_year - 1 and settings.magi_prior_year_filing_status is not None:
        return settings.magi_prior_year_filing_status
    if year == start_year - 2 and settings.magi_two_years_prior_filing_status is not None:
        return settings.magi_two_years_prior_filing_status
    return current


def medicare_enrollment_start(settings, owner, age, birth_month):
    """Share of the calendar year before modeled Medicare enrollment begins,
    0.0 when enrolled all year, or None when not enrolled this year.

    Mirrors the premiums in ``add_person_costs``: enrollment starts in the
    birthday month of the enrollment age (65 unless overridden).
    """
    if not settings.enabled:
        return None
    person = overrides(settings).get(owner)
    if (person["mode"] if person else "coverage") != "coverage":
        return None
    enabled = person["medicare_enabled"] if person else settings.medicare_enabled
    enrollment_age = person["medicare_start_age"] if person else 65
    if not enabled or age < enrollment_age:
        return None
    return ((birth_month or 1) - 1) / 12 if age == enrollment_age else 0.0


def aca_participates(settings, owner):
    person = overrides(settings).get(owner)
    return person is None or (person["mode"] == "coverage" and person["aca_enabled"])


def medical_total(hc):
    return (hc.aca_net_premium + hc.medicare_part_b + hc.medicare_irmaa_part_b
            + hc.medicare_irmaa_part_d + hc.medicare_part_d_plan + hc.medicare_supplement
            + hc.medicare_part_a + hc.itemized_medical + hc.out_of_pocket + hc.long_term_care)


def person_profiles(plan, state, year):
    """Use the selected household convention for each original person's costs.

    Month indices are absolute, zero-based, with an exclusive death endpoint.
    Active-until is a fraction of the current calendar year.
    """
    result = [{"owner": "self", "age": year - plan.birth_year,
               "birth_month": plan.birth_month or 1,
               "alive_until": owner_alive_until(plan, state, "self", year),
               "death_month": longevity_end_month_index(plan, "self")}]
    if plan.spouse_birth_year is not None:
        birthday = plan.spouse_birth_month or 1
        death = longevity_end_month_index(plan, "spouse")
        until = owner_alive_until(plan, state, "spouse", year)
        result.append({"owner": "spouse", "age": year - plan.spouse_birth_year,
                       "birth_month": birthday, "alive_until": until, "death_month": death})
    return result


def add_person_costs(hc, settings, profiles, *, year, start_year, year_fraction,
                     filing_status, magi, inflation_factor, medical_factor,
                     mfs_lived_apart_all_year=False):
    """Add each person's selected costs once, returning input qualifications.

    ACA remains a household tax-credit calculation in the simulator. Costs here
    are itemized totals, Medicare premiums, optional out-of-pocket budgets, and
    explicit LTC budgets net of an entered covered share.
    """
    selected = overrides(settings)
    warnings = []
    known_owners = {person["owner"] for person in profiles}
    if set(selected) - known_owners:
        raise ValueError("A spouse health override requires the spouse's birth date")
    for profile in profiles:
        owner = profile["owner"]
        person = selected.get(owner)
        mode = person["mode"] if person else "coverage"
        rate = person.get("medical_inflation_rate") if person else None
        factor = (1 + rate) ** (year - start_year) if rate is not None else medical_factor
        age, birthday, until = profile["age"], profile["birth_month"], profile["alive_until"]
        period_start = 1 - year_fraction
        alive_fraction = max(0.0, until - period_start)
        row = {"owner": owner, "mode": mode, "active_fraction": alive_fraction,
               "itemized_medical": 0.0, "out_of_pocket": 0.0, "medicare_premiums": 0.0,
               "long_term_care_gross": 0.0, "long_term_care_covered": 0.0,
               "long_term_care": 0.0, "total_excluding_aca": 0.0,
               "out_of_pocket_assumption": "not_applicable"}
        if mode == "itemized":
            first_age, last_age = person["itemized_start_age"], person["itemized_end_age"]
            first = (birthday - 1) / 12 if age == first_age else 0.0
            last = (birthday - 1) / 12 if last_age is not None and age == last_age else 1.0
            active = max(0.0, min(until, last) - max(period_start, first))
            if age < first_age or (last_age is not None and age > last_age):
                active = 0.0
            amount = person["itemized_annual_amount"] * factor * active
            hc.itemized_medical += amount
            row["itemized_medical"] = amount
        elif mode == "coverage":
            enabled = person["medicare_enabled"] if person else settings.medicare_enabled
            enrollment_age = person["medicare_start_age"] if person else 65
            enrollment_start = (birthday - 1) / 12 if age == enrollment_age else 0.0
            enrolled = max(0.0, until - max(period_start, enrollment_start)) if enabled and age >= enrollment_age else 0.0
            if enrolled:
                personal_settings = replace(settings, **{
                    key: person[key] for key in (
                        "medicare_part_b", "medicare_part_d", "medicare_apply_irmaa",
                        "medicare_part_d_plan_premium_monthly", "medicare_supplement_premium_monthly")
                }) if person else settings
                statutory_factor = medicare_cost_factor(
                    year, rate if rate is not None else settings.medical_inflation_rate, inflation_factor)
                med = calculate_medicare_premiums(magi, filing_status, enrolled, personal_settings,
                    year=year, inflation_factor=inflation_factor, medical_factor=factor,
                    statutory_medical_factor=statutory_factor,
                    mfs_lived_apart_all_year=mfs_lived_apart_all_year)
                hc.medicare_persons += enrolled
                hc.medicare_tier = max(hc.medicare_tier, med.tier_index)
                hc.medicare_part_b += med.part_b_standard
                hc.medicare_irmaa_part_b += med.part_b_irmaa
                hc.medicare_irmaa_part_d += med.part_d_irmaa
                hc.medicare_part_d_plan += med.part_d_plan
                hc.medicare_supplement += med.supplement
                part_a = (person["medicare_part_a_premium_monthly"] * 12 * enrolled * factor) if person else 0.0
                if person and person.get("medicare_part_a_quarters") is not None:
                    # The published premium for the person's covered quarters,
                    # indexed from its data year like Part B.
                    part_a += (part_a_premium_monthly(person["medicare_part_a_quarters"])
                               * 12 * enrolled * statutory_factor)
                hc.medicare_part_a += part_a
                row["medicare_premiums"] = med.total + part_a
            if person:
                budget = person["out_of_pocket_annual"]
                row["out_of_pocket_assumption"] = "unknown" if budget is None else "explicit"
                if budget is None:
                    warnings.append(f"{owner}: Coverage includes selected premiums only; out-of-pocket costs were not supplied. This is not a complete healthcare-cost estimate.")
                else:
                    # This is a separate annual budget, including years before
                    # Medicare enrollment, clipped only to the active period.
                    amount = budget * factor * alive_fraction
                    hc.out_of_pocket += amount
                    row["out_of_pocket"] = amount
        care = person.get("long_term_care") if person else None
        if care:
            death_month = profile["death_month"]
            if care["months_before_longevity"] is not None:
                if death_month is None:
                    raise ValueError("An LTC budget relative to longevity requires that person's longevity")
                begin = death_month - care["months_before_longevity"]
            else:
                begin = care["start_year"] * 12 + care["start_month"] - 1
            end = begin + care["duration_months"]
            if death_month is not None:
                end = min(end, death_month)
            overlap = max(0.0, min(year * 12 + until * 12, end)
                          - max(year * 12 + period_start * 12, begin))
            care_rate = care["inflation_rate"]
            reference = care["amount_reference_year"]
            if care_rate is None and reference is not None and reference != start_year:
                raise ValueError("An LTC amount reference year other than the plan start requires an explicit inflation rate")
            care_factor = (1 + care_rate) ** (year - (reference if reference is not None else start_year)) if care_rate is not None else factor
            gross = care["monthly_cost"] * care_factor * overlap
            covered = gross * care["covered_fraction"]
            net = gross - covered
            for key, amount in (("long_term_care_gross", gross), ("long_term_care_covered", covered), ("long_term_care", net)):
                setattr(hc, key, getattr(hc, key) + amount)
                row[key] = amount
        row["total_excluding_aca"] = sum(row[key] for key in (
            "itemized_medical", "out_of_pocket", "medicare_premiums", "long_term_care"))
        hc.person_costs.append(row)
    hc.total = medical_total(hc)
    return warnings
