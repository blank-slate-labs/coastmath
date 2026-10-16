"""Pydantic v2 schemas for Monte Carlo simulation requests and results."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from coastmath.schemas.simulation import SimulationResult

FailureMode = Literal["liquid_assets", "net_worth"]
SamplingMethod = Literal[
    "block_bootstrap", "moving_block", "historical_sequential", "random_start", "random_years",
]
OnDataEnd = Literal["loop", "stop", "random_restart"]
ExtraMetric = Literal["liquid_net_worth", "spending", "taxes", "income"]


class FailureDetail(BaseModel):
    trial_index: int
    failure_year: int
    failure_age: int
    cause: str
    net_worth_at_failure: float


class PercentileCurves(BaseModel):
    years: list[int]
    p10: list[float]
    p25: list[float]
    p50: list[float]
    p75: list[float]
    p90: list[float]


class SuccessTargets(BaseModel):
    """Optional outcome targets evaluated per trial, separately from funding failure.

    Amounts are nominal dollars at the end of the plan unless noted.
    """

    terminal_net_worth_min: float | None = Field(default=None, ge=0)
    count_spending_cuts_as_shortfall: bool = False


class OutcomeCategory(BaseModel):
    key: str
    label: str
    definition: str
    count: int
    rate: float


class MilestoneDistribution(BaseModel):
    """Timing conditional on reaching a milestone; missing reports stay unknown."""

    id: str
    name: str
    reached_trials: int
    unreached_trials: int
    unreported_trials: int = 0
    reach_rate: float | None = None
    year_counts: dict[int, int] = Field(default_factory=dict)
    p10_year: int | None = None
    median_year: int | None = None
    p90_year: int | None = None


class TrialSummaries(BaseModel):
    """One entry per trial as parallel arrays: position ``i`` is trial index ``i``.

    Columns instead of one object per trial keep 10,000 trials near 2.6 MB of
    JSON. Replay any trial with ``POST .../monte-carlo/trials/{index}``.
    """

    #: No funding failure under the run's failure mode.
    success: list[bool]
    #: First failed year from ``failure_analysis``; null for a successful trial.
    failure_year: list[int | None]
    #: Net worth in the final projection year, nominal; the source of the final percentiles.
    ending_net_worth: list[float]
    #: Liquid account balances in the final projection year, nominal.
    ending_liquid: list[float]
    #: The ``outcome_categories`` key the trial was counted in.
    outcome: list[str]
    #: Milestone id (as in ``milestone_distributions``) to the year it fired per
    #: trial; null when not reached or not reported.
    milestone_years: dict[str, list[int | None]] = Field(default_factory=dict)
    #: First projection year and the primary person's age in it, to turn years into ages.
    start_year: int
    start_age: int
    #: Projection years sampled for the sparklines (at most 24, first and last included).
    sparkline_years: list[int]
    #: Net worth at ``sparkline_years`` per trial, nominal dollars rounded to three
    #: significant figures. Display only; use ``ending_net_worth`` for values.
    sparklines: list[list[int]]


class FailureTiming(BaseModel):
    """When failed trials failed, by the share of the projection completed."""

    early_fraction: float
    late_fraction: float
    early: int
    mid: int
    late: int
    #: Shares of failed trials; all zero when no trial failed.
    early_rate: float
    mid_rate: float
    late_rate: float


class SurplusClasses(BaseModel):
    """Successful trials by final net worth relative to net worth at retirement."""

    thin_margin_percent: float
    wide_margin_percent: float
    #: Milestone used as the reference year; null means the first projection year.
    reference_milestone_id: str | None = None
    reference_milestone_name: str | None = None
    thin_margin: int
    moderate_margin: int
    wide_margin: int
    #: Shares of successful trials; all zero when no trial succeeded.
    thin_margin_rate: float
    moderate_margin_rate: float
    wide_margin_rate: float


class OutcomeDetail(BaseModel):
    failure_timing: FailureTiming
    surplus: SurplusClasses
    definitions: dict[str, str] = Field(default_factory=dict)


class MonteCarloResult(BaseModel):
    success_rate: float
    n_trials: int
    percentile_curves: PercentileCurves
    failure_analysis: list[FailureDetail]
    median_final_net_worth: float
    p10_final_net_worth: float
    p90_final_net_worth: float
    # Explicit success measures. ``success_rate`` above is always the funding
    # success rate (no failure under the chosen failure mode).
    funding_success_rate: float = 0.0
    target_success_rate: float | None = None
    outcome_categories: list[OutcomeCategory] = []
    success_targets: SuccessTargets | None = None
    definitions: dict[str, str] = {}
    milestone_distributions: list[MilestoneDistribution] = Field(default_factory=list)
    # Always false; kept so shipped clients keep decoding results.
    distributions_locked: bool = False
    # Trial explorer. Both are absent from results stored before they existed.
    #: The seed of trial 0; trial ``i`` uses ``base_seed + i``. The requested
    #: seed, or the one drawn when the request had none.
    base_seed: int | None = None
    trials: TrialSummaries | None = None
    # Return sampling. Absent from results stored before these existed.
    #: The sampling method the run used.
    sampling: SamplingMethod | None = None
    #: Failure timing and surplus classes of successful trials.
    outcome_detail: OutcomeDetail | None = None
    #: Per-year percentiles of the requested ``extra_metrics``, nominal dollars.
    metric_percentiles: dict[str, PercentileCurves] | None = None


class MonteCarloTrialDetail(BaseModel):
    """One trial replayed exactly, with its full projection."""

    index: int
    #: The trial's own random seed: ``base_seed + index``.
    seed: int
    success: bool
    #: Present when the trial failed; ``trial_index`` equals ``index``.
    failure: FailureDetail | None = None
    outcome: str
    ending_net_worth: float
    ending_liquid: float
    milestone_years: dict[str, int | None] = Field(default_factory=dict)
    #: The same shape as the deterministic projection.
    simulation: SimulationResult
    #: First historical year of the trial's sequence for the chronological
    #: methods (``historical_sequential``, ``random_start``); null otherwise.
    historical_start_year: int | None = None


class NormalDistribution(BaseModel):
    """Independent yearly draws from a normal distribution, in percent."""

    model_config = ConfigDict(extra="forbid")

    #: Arithmetic mean, percent per year.
    mean: float = Field(ge=-50, le=200)
    #: Standard deviation, percent per year.
    stdev: float = Field(ge=0, le=200)


class ReturnSource(BaseModel):
    """Where one market variable comes from in each trial year."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["historical", "normal"] = "historical"
    mean: float | None = Field(default=None, ge=-50, le=200)
    stdev: float | None = Field(default=None, ge=0, le=200)

    @model_validator(mode="after")
    def _normal_needs_parameters(self) -> "ReturnSource":
        if self.source == "normal" and (self.mean is None or self.stdev is None):
            raise ValueError("a normal source needs both mean and stdev (percent)")
        if self.source == "historical" and (self.mean is not None or self.stdev is not None):
            raise ValueError("mean and stdev apply only to a normal source")
        return self


class ReturnSources(BaseModel):
    """Per-variable return source. Stocks are total return (price plus dividends)."""

    model_config = ConfigDict(extra="forbid")

    stocks: ReturnSource = Field(default_factory=ReturnSource)
    dividend_yield: ReturnSource = Field(default_factory=ReturnSource)
    bonds: ReturnSource = Field(default_factory=ReturnSource)
    inflation: ReturnSource = Field(default_factory=ReturnSource)


class OutcomeThresholds(BaseModel):
    """Cut-offs for failure timing and the surplus classes of successful trials."""

    model_config = ConfigDict(extra="forbid")

    #: A failure before this share of the projection is early.
    failure_early_fraction: float = Field(default=1 / 3, gt=0, lt=1)
    #: A failure at or after this share of the projection is late.
    failure_late_fraction: float = Field(default=2 / 3, gt=0, lt=1)
    #: Final net worth below this percent of net worth at retirement: thin margin.
    #: ``almost_failed_percent`` is still accepted from older native builds.
    thin_margin_percent: float = Field(
        default=25, ge=0, le=10000,
        validation_alias=AliasChoices("thin_margin_percent", "almost_failed_percent"),
    )
    #: Final net worth above this percent of net worth at retirement: wide margin.
    #: ``large_surplus_percent`` is still accepted from older native builds.
    wide_margin_percent: float = Field(
        default=200, ge=0, le=10000,
        validation_alias=AliasChoices("wide_margin_percent", "large_surplus_percent"),
    )
    #: Milestone whose year is the surplus reference. Unset (or not in the
    #: plan) finds the plan holder's retirement milestone by name.
    retirement_milestone_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _ordered(self) -> "OutcomeThresholds":
        if self.failure_early_fraction >= self.failure_late_fraction:
            raise ValueError("failure_early_fraction must be below failure_late_fraction")
        if self.thin_margin_percent >= self.wide_margin_percent:
            raise ValueError("thin_margin_percent must be below wide_margin_percent")
        return self


#: Moving-block length when ``moving_block`` omits ``block_length``.
DEFAULT_BLOCK_LENGTH = 5


#: Above this a run outlasts the proxy's 100 s origin limit on production (about 39 ms a trial),
#: so it could never answer. 1,000 trials take about 39 s.
MAX_MONTE_CARLO_TRIALS = 1000

#: A ``historical_sequential`` run has start years x iterations trials, whatever ``n_trials`` says.
#: The 97 start years of 1928-2024 times 10 stay within ``MAX_MONTE_CARLO_TRIALS``.
MAX_SEQUENTIAL_ITERATIONS = 10


class MonteCarloMethodOptions(BaseModel):
    """Return sampling and outcome-detail options shared by every Monte Carlo request.

    Every field is optional; omitting all of them reproduces the circular block
    bootstrap of historical years with no extra metrics.
    """

    sampling: SamplingMethod = "block_bootstrap"
    #: ``moving_block`` only: fixed block length in years (default 5).
    block_length: int | None = Field(default=None, ge=1, le=30)
    #: ``historical_sequential`` only: what happens after the last historical year (default loop).
    on_data_end: OnDataEnd | None = None
    #: ``historical_sequential`` with ``random_restart`` only: runs per start year (default 1).
    iterations: int | None = Field(default=None, ge=1, le=MAX_SEQUENTIAL_ITERATIONS)
    sources: ReturnSources | None = None
    #: Return distribution for cryptocurrency accounts; absent keeps their usual growth.
    crypto: NormalDistribution | None = None
    outcome_thresholds: OutcomeThresholds | None = None
    extra_metrics: list[ExtraMetric] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def _method_fields_match(self) -> "MonteCarloMethodOptions":
        if self.block_length is not None and self.sampling != "moving_block":
            raise ValueError("block_length applies only to the moving_block sampling method")
        if self.on_data_end is not None and self.sampling != "historical_sequential":
            raise ValueError("on_data_end applies only to the historical_sequential sampling method")
        if self.iterations is not None and self.iterations > 1 and (
            self.sampling != "historical_sequential" or self.on_data_end != "random_restart"
        ):
            raise ValueError("iterations above 1 need historical_sequential with on_data_end random_restart")
        if len(set(self.extra_metrics)) != len(self.extra_metrics):
            raise ValueError("extra_metrics must not repeat a metric")
        return self


class MonteCarloRequest(MonteCarloMethodOptions):
    n_trials: int = Field(default=1000, ge=1, le=MAX_MONTE_CARLO_TRIALS)
    block_size_min: int = Field(default=3, ge=1, le=30)
    block_size_max: int = Field(default=7, ge=1, le=30)
    seed: int | None = Field(default=None, ge=0, le=2147483647)
    failure_mode: FailureMode = "liquid_assets"
    success_targets: SuccessTargets | None = None
    # Shift sampled history so its compound return matches the plan's
    # assumptions; False uses raw 1928-2024 averages.
    calibrate_to_plan: bool = True


#: Drawn base seeds come from [0, 2**32); requested seeds stay within ``seed``'s bound.
MAX_BASE_SEED = 2**32 - 1


class MonteCarloTrialRequest(MonteCarloRequest):
    """Replays one trial: the run's own settings plus the ``base_seed`` it reported.

    ``n_trials`` is required here because it bounds the trial index. For
    ``historical_sequential`` send the run's reported ``n_trials``.
    """

    n_trials: int = Field(ge=1, le=MAX_MONTE_CARLO_TRIALS)
    base_seed: int = Field(ge=0, le=MAX_BASE_SEED)

    @model_validator(mode="after")
    def _seed_matches_base_seed(self) -> "MonteCarloTrialRequest":
        if self.seed is not None and self.seed != self.base_seed:
            raise ValueError("seed, when sent, must equal base_seed")
        return self
