"""Cached loader for historical market returns.

Derives annual S&P 500 total returns, 10-year Treasury total returns and CPI
inflation for 1928–2024 from the published values below, for the Monte Carlo
and stress-test engines. The data files hold only those published values;
every return is computed here.

Sources:

- ``sp500_dividends.csv``: the S&P 500 year-end index level and the dividends
  paid during each year, 1927–2025, from the "S&P 500 & Raw Data" sheet of
  Aswath Damodaran's histretSP.xls (NYU Stern, updated January 5, 2026,
  downloaded 2026-10-11):
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html
  Damodaran publishes the data for free use:
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html#rules
- ``treasury_yields.csv``: monthly U.S. Treasury yields in percent, as
  published, downloaded 2026-10-11. ``series`` names the source:

  - ``long_term_partially_tax_exempt``, 1927-12 to 1941-10: average yield of
    partially tax-exempt Treasury bonds callable after 12 years, monthly
    averages of daily figures, Federal Reserve Bulletin (December 1938 and
    later issues): https://fraser.stlouisfed.org/title/federal-reserve-bulletin-62
    Digitized as NBER Macrohistory m13033a:
    https://fred.stlouisfed.org/series/M1333AUSM156NNBR
  - ``long_term_taxable``, 1941-10 to 1953-04: average yield of taxable
    Treasury bonds due or callable after 15 years (12 years from April 1952,
    12–20 years from April 1953), Treasury Bulletin and Federal Reserve
    Bulletin: https://fraser.stlouisfed.org/title/treasury-bulletin-407
    Digitized as NBER Macrohistory m13033b:
    https://fred.stlouisfed.org/series/M1333BUSM156NNBR
  - ``ten_year_monthly_average``, 1953-04 to 1962-01: 10-year constant
    maturity, monthly average of business days, Federal Reserve H.15:
    https://www.federalreserve.gov/releases/h15/ (FRED GS10:
    https://fred.stlouisfed.org/series/GS10)
  - ``ten_year_month_end``, 1962-01 to 2024-12: 10-year constant maturity on
    the last business day of each month, Federal Reserve H.15:
    https://www.federalreserve.gov/releases/h15/ (FRED DGS10:
    https://fred.stlouisfed.org/series/DGS10)
- ``cpi_u.csv``: the December CPI-U (U.S. city average, all items, not
  seasonally adjusted, 1982–84=100), BLS series CUUR0000SA0, 1927–2024,
  downloaded 2026-10-11 from the BLS public API:
  https://data.bls.gov/timeseries/CUUR0000SA0

Stocks: total return in year Y is (level_Y − level_Y−1 + dividends_Y) /
level_Y−1 and the dividend yield is dividends_Y / level_Y−1, so price change
and yield sum to the total. Approximation: dividends count at year end, not
reinvested during the year; no freely usable monthly S&P dividend series
exists. Damodaran's dividend amounts before about 1960 differ from other
compilations of S&P's dividends by up to about 40% in some years, so those
years' yields and total returns carry that uncertainty.

Bonds: each month a 10-year par bond is bought at the opening yield (coupon =
yield, paid semiannually) and valued a month later at the closing yield with
10 − 1/12 years left, plus a month of coupon; a year compounds its twelve
months. A month uses the newest series that holds both of its yields, so no
return spans two series. Approximations: before April 1953, long-term bond
yields stand in for the 10-year yield; before 1962, monthly averages smooth
moves within a month; pricing treats the remaining term as a continuous
number of coupon periods.

Inflation: December-to-December change in the CPI-U.

A replayed (stress test) or sampled (Monte Carlo) year keeps the total return
and splits it into price return = total return − yield and dividend income =
yield, so nothing is double counted. A year with no yield uses the plan's own
dividend-yield assumption, and the result carries a warning. The yields
describe the S&P 500 only; small-cap, international and REIT distributions are
not represented.
"""

from __future__ import annotations

import functools
from itertools import pairwise
from pathlib import Path

import pandas as pd

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DIVIDENDS_CSV_PATH = _DATA_DIR / "sp500_dividends.csv"
_TREASURY_CSV_PATH = _DATA_DIR / "treasury_yields.csv"
_CPI_CSV_PATH = _DATA_DIR / "cpi_u.csv"

# Newest first: a month's bond return uses the first series holding both yields.
_TREASURY_SERIES = (
    "ten_year_month_end",
    "ten_year_monthly_average",
    "long_term_taxable",
    "long_term_partially_tax_exempt",
)
_BOND_MATURITY_YEARS = 10.0
_DECIMALS = 6

DIVIDEND_YIELD_PROVENANCE = (
    "Historical stock returns are split into price growth and dividends using "
    "each year's S&P 500 dividends; total returns are unchanged."
)


@functools.lru_cache(maxsize=1)
def _load_sp500_returns() -> pd.DataFrame:
    """Year, stock_return and dividend_yield derived from index levels and dividends.

    The first year of the file only supplies the starting level.
    """
    raw = pd.read_csv(_DIVIDENDS_CSV_PATH).sort_values("year")
    prior_level = raw["sp500_level"].shift(1)
    df = pd.DataFrame({
        "year": raw["year"].astype(int),
        "stock_return": ((raw["sp500_level"] - prior_level + raw["dividends"]) / prior_level).round(_DECIMALS),
        "dividend_yield": (raw["dividends"] / prior_level).round(_DECIMALS),
    })
    return df.dropna().reset_index(drop=True)


@functools.lru_cache(maxsize=1)
def load_historical_dividend_yields() -> pd.DataFrame:
    """Derive each year's S&P 500 dividend yield (year, dividend_yield).

    Row Y is dividends paid in Y over the index level at the end of Y−1.
    """
    return _load_sp500_returns()[["year", "dividend_yield"]]


def _par_bond_price(coupon: float, market_yield: float, years: float) -> float:
    """Price per unit face of a semiannual-coupon bond at a bond-equivalent yield."""
    periods = 2.0 * years
    if market_yield == 0.0:
        return 1.0 + coupon / 2.0 * periods
    discount = (1.0 + market_yield / 2.0) ** -periods
    return coupon / market_yield * (1.0 - discount) + discount


def _monthly_bond_return(opening_yield: float, closing_yield: float) -> float:
    """One month's return on a 10-year par bond bought at *opening_yield*."""
    price = _par_bond_price(opening_yield, closing_yield, _BOND_MATURITY_YEARS - 1.0 / 12.0)
    return price - 1.0 + opening_yield / 12.0


def _next_month(month: str) -> str:
    year, number = int(month[:4]), int(month[5:7])
    return f"{year + number // 12}-{number % 12 + 1:02d}"


@functools.lru_cache(maxsize=1)
def _load_treasury_returns() -> pd.DataFrame:
    """Year and bond_return compounded from monthly 10-year par bond returns."""
    raw = pd.read_csv(_TREASURY_CSV_PATH, dtype={"month": str, "series": str})
    unknown = set(raw["series"]) - set(_TREASURY_SERIES)
    if unknown:
        raise ValueError(f"treasury_yields.csv has unknown series: {sorted(unknown)}")
    yields = {
        (series, month): percent / 100.0
        for month, series, percent in raw[["month", "series", "yield_percent"]].itertuples(index=False)
    }
    months = sorted(set(raw["month"]))
    growth: dict[int, float] = {}
    month_count: dict[int, int] = {}
    for opening, closing in pairwise(months):
        if closing != _next_month(opening):
            raise ValueError(f"treasury_yields.csv skips from {opening} to {closing}")
        series = next(
            (s for s in _TREASURY_SERIES if (s, opening) in yields and (s, closing) in yields),
            None,
        )
        if series is None:
            raise ValueError(f"treasury_yields.csv has no series with both {opening} and {closing}")
        year = int(closing[:4])
        monthly = _monthly_bond_return(yields[(series, opening)], yields[(series, closing)])
        growth[year] = growth.get(year, 1.0) * (1.0 + monthly)
        month_count[year] = month_count.get(year, 0) + 1
    partial = sorted(year for year, count in month_count.items() if count != 12)
    if partial:
        raise ValueError(f"treasury_yields.csv covers only part of {partial}")
    years = sorted(growth)
    return pd.DataFrame({
        "year": years,
        "bond_return": [round(growth[year] - 1.0, _DECIMALS) for year in years],
    })


@functools.lru_cache(maxsize=1)
def _load_inflation() -> pd.DataFrame:
    """Year and December-to-December CPI-U inflation."""
    raw = pd.read_csv(_CPI_CSV_PATH).sort_values("year")
    df = pd.DataFrame({
        "year": raw["year"].astype(int),
        "inflation": (raw["december_index"] / raw["december_index"].shift(1) - 1.0).round(_DECIMALS),
    })
    return df.dropna().reset_index(drop=True)


@functools.lru_cache(maxsize=1)
def load_historical_returns() -> pd.DataFrame:
    """Load and cache the annual historical returns.

    Returns a DataFrame with columns: year, stock_return, bond_return,
    inflation and dividend_yield, covering the years every source spans. The
    year column is integer-typed.
    """
    stocks = _load_sp500_returns()
    df = (
        stocks[["year", "stock_return"]]
        .merge(_load_treasury_returns(), on="year")
        .merge(_load_inflation(), on="year")
        .merge(stocks[["year", "dividend_yield"]], on="year")
    )
    return df.sort_values("year").reset_index(drop=True)


def get_returns_for_range(start_year: int, end_year: int) -> pd.DataFrame:
    """Return historical returns for *start_year* through *end_year* inclusive.

    Raises ``ValueError`` if the requested range falls entirely outside
    the available data or produces an empty result.
    """
    df = load_historical_returns()
    min_year = int(df["year"].min())
    max_year = int(df["year"].max())

    if start_year > end_year:
        raise ValueError(
            f"start_year ({start_year}) must be <= end_year ({end_year})"
        )

    if start_year > max_year or end_year < min_year:
        raise ValueError(
            f"Requested range {start_year}–{end_year} is outside available "
            f"data ({min_year}–{max_year})"
        )

    subset = df[(df["year"] >= start_year) & (df["year"] <= end_year)]

    if subset.empty:
        raise ValueError(
            f"No data found for range {start_year}–{end_year}"
        )

    return subset.reset_index(drop=True)
