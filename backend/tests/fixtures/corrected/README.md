# Corrected persona inputs

These are separate copies of the persona fixtures with explicit income
ownership and Social Security metadata. Every original source fixture and
captured baseline remains unchanged. `provenance.json` records each original
path, SHA-256 and exact field edit; `test_corrected_fixtures.py` verifies that
the copies differ only as recorded.

- All income records explicitly encode `owner` and `is_social_security`.
  High-earner income `…021021` and Median income `…000031` are spouse wages.
  Median income `…000032` explicitly encodes the Social Security benefit.
  These are fixture-specific corrections, not production inference from labels.
- Median spouse retirement is explicitly `2055-01-01`: spouse born in 1992,
  retirement at 63. The original generic age milestone evaluates the primary
  person's age and therefore fired in 2053. No production milestone inference
  from the display name is introduced.
- Account ownership, names, inherited-account metadata and expense categories
  are preserved by the corrected persona loader. The original explicit spouse
  Roth and joint HNW owners required no fixture edit.
- Rates in these historical fixtures use decimal fractions. Persisted/HTTP
  income growth and withholding fields require percentages; the tests perform
  this conversion explicitly. Assumption rates retain their existing decimals.

No HSA family-coverage/eligibility assumption is inferred from marital status.
No state payroll tax, estate override, opening-date, COLA, return timing, or
tax-settlement assumption is added to these copies. Those require
separate evidence and must not be conflated with the input-contract fixes.

`build_plan_from_fixture(raw)` now respects explicit metadata and never infers
Social Security or income owner from a label. `legacy_replay=True` deliberately
restores the old loader semantics only for archival diagnostics. It does not
restore old financial-engine code or make old output baselines current.
Ordinary regression tests do not enable this option.

The independent two-worker payroll regression uses the [SSA 2026 wage base
of $184,500](https://www.ssa.gov/OACT/cola/cbbdet.html), the [2026 employee
6.2% Social Security and 1.45% Medicare rates](https://www.irs.gov/publications/p15),
and the [0.9% Additional Medicare joint threshold of
$250,000](https://www.irs.gov/taxtopics/tc560). On salaries of $300,000 and
$150,000, FICA is `(184500 + 150000) * .062 + 450000 * .0145 + 200000 * .009`
= **$29,064**; assigning both salaries to one worker gives **$19,764**.

Run from `backend/`:

```sh
python -m pytest tests/test_corrected_fixtures.py tests/persona -q
```

The six cases persist and reload isolated SQLite data and compare full
results with direct engine and stateless execution.
