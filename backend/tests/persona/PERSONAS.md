# Persona Regression Suite

End-to-end regression harness for the simulation engine. Five archetypal
plans ("personas") are simulated in full, and their output is compared
checkpoint-by-checkpoint against a committed baseline.

## Purpose

The rest of the test suite checks **shape** (types, decompositions,
sign/direction invariants) and **behavior** (specific calculations on
small contrived inputs). Those tests will not catch a silent **numeric
drift** — a tax-bracket edit, a waterfall tweak, or a cost-basis bug
that shifts every year's net worth by 0.8% but keeps every decomposition
and sign correct.

Persona regression plugs that gap. Each persona is a realistic full-life
plan whose baseline output was captured when the engine was known-good.
If any engine change shifts a net-worth, tax, or drawdown number by
more than 0.5% at any of the 10 checkpoint ages, the suite fails and
prints a diagnostic with the exact field, expected value, actual value,
and percent delta.

This complements — not replaces — the invariant suites in
`test_drawdown_invariants.py`, `test_tax_invariants.py`, and
`test_milestone_invariants.py`, which assert engine-contract properties
that hold for every persona without reference to a baseline.

## Adding a new persona

1. **Create the fixture** at `backend/tests/persona/fixtures/<name>.json`.
   Follow the shape of an existing fixture (e.g. `fire_persona.json`):
   plan-level fields (`birth_year`, `birth_month`, `state_code`), UUID-keyed
   `accounts` with `cost_basis`, `income_streams`, `milestones`,
   `residency_periods`, and optional `sepp_settings`, `charity_entities`,
   `estate_settings`. The fixture is loaded via
   `harness.build_plan_from_fixture`, which delegates the common mapping
   to `tests.engine_support.fixture_to_plan_data` and layers on the newer
   fields — any field that helper doesn't handle yet must be added there.

2. **Capture the baseline** by running the simulation once and snapshotting
   the 10 checkpoint ages:

   ```bash
   cd backend
   python -m scripts.regenerate_persona_baseline <name>
   ```

   This writes `baselines/<name>.baseline.json`. Open it and sanity-check
   the numbers against your expectations before committing — the baseline
   encodes the engine's output as-is, so a bug in your fixture will bake
   into the baseline and quietly pass forever.

3. **Create the test** at `backend/tests/persona/test_<name>.py` following
   the template in `test_fire_persona.py`:

   - Mark with `@pytest.mark.persona_regression` (always) and
     `@pytest.mark.persona_fast` (if the fixture runs in well under a
     second).
   - Load fixture + baseline via the harness; assert the baseline is
     non-empty with a regeneration hint in the message.
   - Run `run_simulation(plan)`, index snapshots by age, loop
     `CHECKPOINT_AGES`, and call `assert_snapshot_near(...,
     tolerance_pct=0.5, context=f"age {age}")` for each.
   - Add 2–4 **engine-invariant spot assertions** specific to the
     archetype — these are independent of the baseline and catch
     regressions where the baseline was regenerated against buggy output.
     Examples in `test_fire_persona.py:54-101`: residency-driven state
     tax, pro-rated salary arithmetic, pre-59½ source gating.

4. **Add the persona to the cross-cut invariant suites**. Each of
   `test_drawdown_invariants.py`, `test_tax_invariants.py`, and
   `test_milestone_invariants.py` parametrizes over the full persona
   list. Append the new name there so it gets the full cross-persona
   checks for free.

5. **Commit together**: fixture, baseline, and test in a single commit
   so the baseline's provenance is always a reviewable diff alongside
   the fixture that produced it.

## When to regenerate baselines

Regenerating a baseline replaces the "known-good" contract. Do it
deliberately — a regenerated baseline is a commit that says _the old
numbers were wrong and these new numbers are right_.

**Regenerate when:**

- Engine logic changed **on purpose** — a tax-bracket update, a rule
  change (new RMD age, updated contribution limit), or a bug fix that
  correctly changes behavior.
- A new scalar field was added to the baseline snapshot (see
  `_SNAPSHOT_FIELD_MAP` in `harness.py` and `_SCALAR_FIELD_MAP` in
  `scripts/regenerate_persona_baseline.py` — keep these in sync).
- A fixture was intentionally edited (new income stream, adjusted
  residency, added milestone).

**Do NOT regenerate when:**

- A test fails and you don't understand why. **Investigate first.**
  Regenerating to green a failing test defeats the entire purpose of
  the suite — you will have erased the drift detection the persona
  was there to catch.
- You're chasing a test failure caused by unrelated code and want to
  "unblock the build." Revert your change or fix the real bug instead.

**Workflow:**

```bash
# 1. Preview — per-checkpoint deltas with colorized percent changes.
#    Green <1%, yellow 1-5%, red >5% or zero→nonzero.
python -m scripts.regenerate_persona_baseline --all --diff

# 2. Review. Every non-green delta should be explainable by the change
#    you just made. If one isn't, stop and investigate.

# 3. Apply, only if the diff matches intent.
python -m scripts.regenerate_persona_baseline --all
```

For a single persona, drop `--all` and pass the fixture stem
(e.g. `fire_persona`).

## Persona catalog

### `fire_persona` — Liquid FIRE Optimizer
Born 1994, CA resident who moves to NV at age 35 (residency milestone)
and retires at 45. Exercises the **pre-59½ drawdown source gate**
(retirement years pull from taxable brokerage only — the 401(k) is
off-limits until 59½ to avoid the early-withdrawal penalty),
**residency-bound state tax** (CA → NV mid-plan), and **partial-year
salary pro-rating** (5 months of W2 income in the retire
year because `birth_month=6`). The canonical FIRE happy-path; the
`persona_fast` tier uses this persona for quick smoke checks.

### `high_earner_late_saver` — High-Earner Late Saver
Born 1976, TX resident with multi-stream compensation (base W2 + bonus
+ RSU). Exercises the **high-AGI tax path** — NIIT on investment
income, AMT exposure in peak earning years — and stacked income
streams hitting payroll-tax caps. TX has no state income tax, so
`state_tax` must be zero every year (a dedicated tax-invariant
assertion). Late-saver archetype: small starting balances, aggressive
catchup contributions near retirement.

### `self_employed_sepp` — Self-Employed SEPP 72(t)
Born 1988, FL resident, sole 1099 income stream with
`is_self_employed=True`. Exercises **SE tax** (self-employment FICA
on the whole stream), **SEP-IRA / solo-401(k) contribution limits**,
and the **SEPP 72(t) early-withdrawal exemption** starting at age 50
using the `fixed_amortization` method out of the traditional IRA. The
drawdown-invariant suite verifies zero early-withdrawal penalty
despite pulling from a traditional account before 59½ — that's the
72(t) exemption working.

### `inherited_ira` — Inherited IRA 10-Year Rule
Born 1971, CA resident with an inherited traditional IRA subject to
the **10-year forced drawdown rule** (SECURE Act). Exercises
`rmd.py`'s inherited-account path, which must fully distribute the
inherited balance within 10 years of the inheritance date regardless
of the beneficiary's age or RMD status on their own accounts. CA
state tax compounds the drawdown-year AGI spike, making this a good
stress test for the state-tax bracket walk.

### `hnw_estate` — High Net Worth Estate
Born 1966, WA resident with a large taxable brokerage and a
**Qualified Charitable Distribution** (QCD) stream of $50k/yr once
the retire milestone fires. Exercises `estate_tax.py` against the
federal estate exemption, **step-up basis on death** (cost-basis
reset for heirs), and WA-specific behavior (no state income tax,
but a state estate tax that's off by default and can be toggled via
`estate_settings`). The canonical test for end-of-life accounting.

## Tolerance rationale

`assert_snapshot_near` takes a `tolerance_pct` that's **relative** to
the expected value. The default is **0.5%**.

- **Why 0.5%** — it's tight enough to catch real drifts (a 1% bracket
  shift, a compounding 0.3% drawdown bug over 40 years) while
  tolerating last-cent rounding differences that creep in from
  floating-point accumulation across the 12-step yearly loop. Running
  the same fixture twice should produce identical output; 0.5% is
  slack for *intentionally different* but *still correct* outputs
  from minor refactors (field reordering, dataclass copying).

- **Tighten to 0.1%** for deterministic arithmetic where you know the
  exact expected value — e.g. a single year's federal tax on a fixed
  AGI, or a direct contribution-limit test. At 0.1% the test asserts
  "this arithmetic is exact," not just "it's in the ballpark."

- **Loosen to ~2%** for growth-chained projections where small
  compounding differences are expected — see
  `test_fire_persona.py:74`, which asserts `expected_age45_salary =
  180_000 * 1.03**13 * 5/12` within ±2% because the engine applies
  growth year-by-year (not in closed form) and rounding accumulates.
  A regression to full-year salary semantics would be off by ~2.4×,
  so 2% still catches the bug cleanly.

- **Zero-expected values** fall back to a **$1 absolute tolerance**
  (`harness.py:_ZERO_ABS_TOLERANCE`). This handles no-state-tax
  jurisdictions (NV, TX, FL, WA) without spurious `expected == 0 →
  divide by zero` failures, and lets "this line item should be zero"
  checks pass cleanly when tiny float residuals show up.
