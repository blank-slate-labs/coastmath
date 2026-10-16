"""Roth basis and distribution accounting (IRS590-B and designated Roth FAQ).

IRA distributions aggregate by taxpayer for the calendar year, including
contributions made after a distribution. Inherited IRAs remain separate from
the beneficiary's own IRAs. Designated Roth plans distribute basis pro rata.
Sources: https://www.irs.gov/publications/p590b
https://www.irs.gov/retirement-plans/retirement-plans-faqs-on-designated-roth-accounts
"""
from copy import deepcopy

from coastmath.engine.account_types import (
    ROTH_EMPLOYER_PLAN_TYPES,
    ROTH_TYPES,
    SECTION_457B_TYPES,
)


class RothLedger:
    def __init__(self, accounts, year):
        self.year = year
        self.groups = {}
        self.account_groups = {}
        self.designated_income = 0.0
        self.designated_penalty = 0.0
        # Federal 10% plus any state additional tax (set by ledger()).
        self.penalty_rate = .1
        for aid, acct in accounts.items():
            if acct.account_type not in ROTH_TYPES:
                continue
            key = (('owner', acct.owner) if acct.account_type == 'roth_ira' and acct.inherited_year is None else ('account', aid))
            self.account_groups[aid] = key
            group = self.groups.setdefault(key, {'members': [], 'basis': 0.0, 'conversions': [],
                'first_year': None, 'withdrawals': 0.0, 'qualified': False, 'early': False,
                'exempt': False})
            data = deepcopy(acct.roth_settings or {})
            group['members'].append(aid)
            group['basis'] += data.get('contribution_basis', 0.0)
            group['conversions'].extend(data.get('conversions', []))
            first = data.get('first_contribution_year')
            if first is None and data.get('conversions'):
                first = min(c['year'] for c in data['conversions'])
            if first is None and (acct.balance > 0 or data.get('contribution_basis', 0) > 0):
                first = year
            if first is not None:
                group['first_year'] = first if group['first_year'] is None else min(group['first_year'], first)

    def deposit(self, aid, amount, conversion_taxable=None):
        group = self.groups[self.account_groups[aid]]
        if amount > 0 and group['first_year'] is None:
            group['first_year'] = self.year
        if conversion_taxable is None:
            group['basis'] += amount
        else:
            group['conversions'].append({'year': self.year, 'taxable_basis': conversion_taxable,
                'nontaxable_basis': amount - conversion_taxable})

    def _ordered(self, group, amount):
        """Return income, penalty, remaining basis and FIFO conversion records."""
        basis_used = min(amount, group['basis'])
        remaining = amount - basis_used
        penalty_basis = 0.0
        conversions = deepcopy(group['conversions'])
        # Same-year taxable conversions precede all that year's nontaxable basis.
        for year in sorted({c['year'] for c in conversions}):
            for field in ('taxable_basis', 'nontaxable_basis'):
                for c in conversions:
                    if c['year'] != year:
                        continue
                    used = min(remaining, c[field])
                    c[field] -= used
                    remaining -= used
                    if field == 'taxable_basis' and self.year < year + 5:
                        penalty_basis += used
        income = 0.0 if group['qualified'] else remaining
        penalty = (self.penalty_rate * (penalty_basis + income)
                   if group['early'] and not group['qualified'] and not group['exempt'] else 0.0)
        return income, penalty, group['basis'] - basis_used, conversions

    def totals(self):
        income, penalty = self.designated_income, self.designated_penalty
        for group in self.groups.values():
            i, p, _, _ = self._ordered(group, group['withdrawals'])
            income += i
            penalty += p
        return income, penalty

    def distribution(self, aid, amount, balance, account_type, early, inherited, *, commit=False,
                     penalty_exempt=False):
        group = self.groups[self.account_groups[aid]]
        qualified = group['first_year'] is not None and self.year >= group['first_year'] + 5 and (not early or inherited)
        # Age 59 1/2 still decides qualification, but a governmental 457(b) is
        # outside IRC 72(t), including the 402A(c)(4)(D) recapture.
        early = early and not inherited and account_type not in SECTION_457B_TYPES
        if account_type in ROTH_EMPLOYER_PLAN_TYPES:
            total_basis = group['basis'] + sum(c['taxable_basis'] + c['nontaxable_basis'] for c in group['conversions'])
            basis_used = amount * min(1.0, total_basis / balance) if balance > 0 else 0.0
            income = 0.0 if qualified else max(0.0, amount - basis_used)
            # Notice2010-84 Q13: recovered basis uses regular contributions
            # first, then FIFO in-plan rollover basis (taxable portion first).
            group['early'], group['qualified'], group['exempt'] = early, qualified, penalty_exempt
            _, recapture, remaining_basis, conversions = self._ordered(group, basis_used)
            # IRC 72(t)(2) exceptions (the Rule of 55) also lift the 402A(c)(4)(D) recapture.
            penalty = 0.0 if penalty_exempt else (self.penalty_rate * income if early else 0.0) + recapture
            if commit:
                group['basis'] = remaining_basis
                group['conversions'] = conversions
                self.designated_income += income
                self.designated_penalty += penalty
            return income, penalty
        group['qualified'], group['early'], group['exempt'] = qualified, early, penalty_exempt
        before = self._ordered(group, group['withdrawals'])
        after = self._ordered(group, group['withdrawals'] + amount)
        if commit:
            group['withdrawals'] += amount
        return after[0] - before[0], after[1] - before[1]

    def finish(self, accounts):
        """Carry undistributed IRA basis into the next calendar year once."""
        for group in self.groups.values():
            _, _, basis, conversions = self._ordered(group, group['withdrawals'])
            for index, aid in enumerate(group['members']):
                accounts[aid].roth_settings = {'first_contribution_year': group['first_year'],
                    'contribution_basis': basis if index == 0 else 0.0,
                    'conversions': conversions if index == 0 else []}


def ledger(state):
    from coastmath.engine.waterfall import (  # noqa: PLC0415 - waterfall imports this module
        state_early_distribution_rate_share,
    )
    if state.roth_ledger is None:
        state.roth_ledger = RothLedger(state.accounts, state.year)
    # Roth ordering holds one early status per year, so the state additional
    # tax (CA FTB 3805P) applies by the share of modeled months resident.
    active = 12.0 * max(0.0, min(1.0, state.year_fraction))
    state.roth_ledger.penalty_rate = .1 + state_early_distribution_rate_share(
        state.early_distribution_state_rates, 12.0 - active, 12.0, active)
    return state.roth_ledger
