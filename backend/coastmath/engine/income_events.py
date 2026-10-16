"""One-off payments and salary-based pension accrual, independent of tax routing."""
from coastmath.engine.types import PlanData


def validate_income_formulas(incomes) -> None:
    by_id = {str(inc.id): inc for inc in incomes}
    for inc in incomes:
        formula = inc.pension_formula
        if not formula:
            continue
        if inc.tax_category != "qualified_pension":
            raise ValueError("Pension formulas require qualified pension income")
        if formula["kind"] == "flat":
            continue
        salary = by_id.get(str(formula.get("linked_income_id")))
        if salary is None or salary.owner != inc.owner or str(salary.id) == str(inc.id):
            raise ValueError("Pension salary must exist in this plan and belong to the same owner")
        if salary.frequency == "once" or not salary.is_earned_income or salary.is_social_security or salary.pension_formula:
            raise ValueError("Pension salary must be a recurring earned income stream")


def payment_share(inc, year, start_year, triggered_years, share, year_fraction, active_until, payment_month=None):
    """A one-off pays its full amount in its start month; cadence uses calendar years."""
    activation = triggered_years.get(inc.start_milestone_id, start_year)
    if inc.start_milestone_id and inc.start_milestone_id not in triggered_years:
        return 0.0
    if inc.frequency == "once":
        month_fraction = ((inc.start_month or payment_month or 1) - 1) / 12
        return float(year == activation and 1 - year_fraction <= month_fraction < active_until and share > 0)
    if inc.recurrence_years and (year - max(start_year, activation)) % inc.recurrence_years:
        return 0.0
    return share


class PensionAccrual:
    """Freeze an annual benefit at commencement, then apply only its explicit COLA.

    Unknown pre-plan pay is represented by the salary's plan-start annual pay.
    Partial years weight annualized nominal salary by their active service share.
    """
    def __init__(self, plan: PlanData):
        validate_income_formulas(plan.income_streams)
        self.plan = plan
        self.histories = {}
        self.benefits = {}
        self.by_id = {inc.id: inc for inc in plan.income_streams}

    def amount(self, pension, year, start_year, triggered_years, growth_factors,
               inflation_factor, salary_share, start_month=None, scheduled_amounts=None):
        formula = pension.pension_formula
        if not formula:
            return None
        key = pension.id
        if key in self.benefits:
            amount, first_year = self.benefits[key]
            return amount * (1 + (formula.get("cola_percent") or 0) / 100) ** (year - first_year)
        activation = triggered_years.get(pension.start_milestone_id, start_year)
        started = not pension.start_milestone_id or pension.start_milestone_id in triggered_years
        history = self.histories.setdefault(key, [])
        if formula["kind"] != "flat":
            salary = self.by_id[formula["linked_income_id"]]
            # Accrual ends just before pension payments commence.
            until = ((pension.start_month or start_month or 1) - 1) / 12 if started and year >= activation else 1.0
            service = salary_share(salary, until)
            if service > 0:
                annual_pay = ((scheduled_amounts or {}).get(salary.id)
                              if salary.id in (scheduled_amounts or {})
                              else salary.annual_amount * growth_factors[salary.id])
                if salary.growth_cap is not None:
                    cap = salary.growth_cap * (inflation_factor if salary.growth_cap_inflation_linked else 1)
                    annual_pay = min(annual_pay, cap)
                history.append((year, annual_pay, service))
        if not started or year < activation:
            return 0.0
        if formula["kind"] == "flat":
            amount = formula["flat_annual_amount"] * inflation_factor
        else:
            prior_service = formula.get("years_of_service_before_plan", 0)
            salary = self.by_id[formula["linked_income_id"]]
            prior = [(start_year - 1, salary.annual_amount, prior_service)] if prior_service else []
            rows = prior + history
            total_service = sum(row[2] for row in rows)
            if formula["kind"] == "final_average":
                # Last N calendar years with service; prior years use opening pay.
                cutoff = (history[-1][0] if history else start_year - 1) - formula.get("final_average_years", 3) + 1
                rows = [row for row in rows if row[0] >= cutoff]
                if prior and cutoff < start_year:
                    rows = [row for row in rows if row[0] >= start_year] + [
                        (start_year - 1, salary.annual_amount, min(prior_service, start_year - cutoff))]
            weight = sum(row[2] for row in rows)
            average_pay = sum(row[1] * row[2] for row in rows) / weight if weight else 0
            amount = average_pay * total_service * formula.get("benefit_percent_per_year", 0) / 100
        self.benefits[key] = (amount, year)
        return amount
