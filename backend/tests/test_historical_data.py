"""Tests for the historical returns data loader."""

import pandas as pd
import pytest

import coastmath.engine.historical_data as hd
from coastmath.engine.historical_data import (
    _DIVIDENDS_CSV_PATH,
    _TREASURY_CSV_PATH,
    _monthly_bond_return,
    _par_bond_price,
    get_returns_for_range,
    load_historical_dividend_yields,
    load_historical_returns,
)
from coastmath.engine.historical_stress import _build_override_returns

EXPECTED_COLUMNS = {"year", "stock_return", "bond_return", "inflation", "dividend_yield"}


class TestLoadHistoricalReturns:
    def test_loads_successfully(self):
        df = load_historical_returns()
        assert len(df) > 0

    def test_has_expected_columns(self):
        df = load_historical_returns()
        assert set(df.columns) == EXPECTED_COLUMNS

    def test_covers_1928_to_2024(self):
        df = load_historical_returns()
        assert df["year"].min() == 1928
        assert df["year"].max() == 2024

    def test_year_is_integer(self):
        df = load_historical_returns()
        assert df["year"].dtype.kind == "i"

    def test_returns_within_plausible_range(self):
        df = load_historical_returns()
        for col in ("stock_return", "bond_return", "inflation"):
            assert df[col].min() >= -0.60, f"{col} has implausibly low value"
            assert df[col].max() <= 1.0, f"{col} has implausibly high value"

    def test_no_missing_values(self):
        df = load_historical_returns()
        assert df.isna().sum().sum() == 0

    def test_no_duplicate_years(self):
        df = load_historical_returns()
        assert df["year"].is_unique


class TestGetReturnsForRange:
    def test_full_range(self):
        df = get_returns_for_range(1928, 2024)
        assert df["year"].min() == 1928
        assert df["year"].max() == 2024

    def test_partial_range(self):
        df = get_returns_for_range(2000, 2010)
        assert len(df) == 11
        assert df["year"].min() == 2000
        assert df["year"].max() == 2010

    def test_single_year(self):
        df = get_returns_for_range(2008, 2008)
        assert len(df) == 1
        assert df["year"].iloc[0] == 2008

    def test_clamps_to_available_data(self):
        # Range extends beyond data on one side — returns what's available
        df = get_returns_for_range(2020, 2030)
        assert df["year"].min() == 2020
        assert df["year"].max() == 2024

    def test_raises_on_entirely_outside_range(self):
        with pytest.raises(ValueError, match="outside available data"):
            get_returns_for_range(2030, 2040)

    def test_raises_on_inverted_range(self):
        with pytest.raises(ValueError, match="must be <="):
            get_returns_for_range(2010, 2000)

    def test_has_correct_columns(self):
        df = get_returns_for_range(1950, 1960)
        assert set(df.columns) == EXPECTED_COLUMNS

    def test_reset_index(self):
        df = get_returns_for_range(2000, 2005)
        assert list(df.index) == list(range(len(df)))



class TestDividendYields:
    def test_yields_cover_every_returns_year(self):
        yields = load_historical_dividend_yields()
        returns = load_historical_returns()
        assert set(returns["year"]) <= set(yields["year"])
        assert "dividend_yield" in returns.columns
        assert returns["dividend_yield"].isna().sum() == 0
        assert yields["year"].is_unique

    def test_yield_is_the_years_dividends_over_the_prior_close(self):
        """Row Y is dividends paid in Y over the index level at the end of Y-1,
        the dividend term of the source's own annual return."""
        by_year = dict(zip(load_historical_dividend_yields()["year"], load_historical_dividend_yields()["dividend_yield"], strict=True))
        assert by_year[1928] == pytest.approx(1.05 / 17.66, abs=1e-6)
        assert by_year[1950] == pytest.approx(1.53 / 16.79, abs=1e-6)
        assert by_year[2008] == pytest.approx(28.39 / 1468.36, abs=1e-6)
        assert by_year[2024] == pytest.approx(74.83 / 4769.8, abs=1e-6)
        assert all(0.005 < v < 0.12 for v in by_year.values())

    def test_stock_total_return_is_price_change_plus_yield(self):
        raw = pd.read_csv(_DIVIDENDS_CSV_PATH).set_index("year")
        price = raw["sp500_level"] / raw["sp500_level"].shift(1) - 1
        returns = load_historical_returns().set_index("year")
        for year, row in returns.iterrows():
            assert row["stock_return"] == pytest.approx(price[year] + row["dividend_yield"], abs=2e-6), year
        # 2008: (903.25 - 1468.36 + 28.39) / 1468.36; the workbook publishes -36.55%.
        assert returns.loc[2008, "stock_return"] == pytest.approx(-0.3655, abs=5e-5)

    def test_stress_replay_books_the_years_yield(self):
        """A 2008 replay splits each year's total return with that year's derived yield."""
        by_year = dict(zip(load_historical_dividend_yields()["year"], load_historical_dividend_yields()["dividend_yield"], strict=True))
        override, years_used, _ = _build_override_returns(load_historical_returns(), 2026, 2028, 2008)
        assert years_used == [2008, 2009]
        assert override[2026][3] == pytest.approx(by_year[2008])
        assert override[2027][3] == pytest.approx(by_year[2009])


@pytest.fixture
def treasury_csv(tmp_path, monkeypatch):
    """Point the bond loader at a temporary yields file of (month, series, percent) rows."""
    def load(rows):
        path = tmp_path / "treasury_yields.csv"
        path.write_text("month,series,yield_percent\n" + "".join(f"{m},{s},{y}\n" for m, s, y in rows))
        monkeypatch.setattr(hd, "_TREASURY_CSV_PATH", path)
        hd._load_treasury_returns.cache_clear()
        return hd._load_treasury_returns()

    yield load
    hd._load_treasury_returns.cache_clear()


def _months(start_year, start_month, count):
    return [f"{start_year + (start_month - 1 + i) // 12}-{(start_month - 1 + i) % 12 + 1:02d}" for i in range(count)]


class TestTreasuryReturns:
    def test_par_bond_price_matches_the_textbook_value(self):
        # A 10-year 4% semiannual-coupon bond priced to yield 5% is worth 92.2054 per 100.
        assert _par_bond_price(0.04, 0.05, 10.0) == pytest.approx(0.922054, abs=1e-6)
        assert _par_bond_price(0.05, 0.05, 10.0 - 1 / 12) == pytest.approx(1.0, abs=1e-12)

    def test_unchanged_yield_earns_one_month_of_coupon(self, treasury_csv):
        assert _monthly_bond_return(0.06, 0.06) == pytest.approx(0.005, abs=1e-12)
        flat = treasury_csv([(m, "ten_year_month_end", "6.00") for m in _months(1927, 12, 13)])
        assert flat["year"].tolist() == [1928]
        assert flat["bond_return"].iloc[0] == pytest.approx(1.005 ** 12 - 1, abs=1e-6)

    def test_rising_yields_lose_and_falling_yields_gain(self, treasury_csv):
        rising = treasury_csv([(m, "ten_year_month_end", "4.00" if m == "1927-12" else "5.00")
                               for m in _months(1927, 12, 13)])
        # Price falls to about 92.2 in January, then eleven months of 5% coupon.
        assert -0.04 < rising["bond_return"].iloc[0] < -0.03
        falling = treasury_csv([(m, "ten_year_month_end", "5.00" if m == "1927-12" else "4.00")
                                for m in _months(1927, 12, 13)])
        assert falling["bond_return"].iloc[0] > 0.10

    def test_month_uses_one_series_for_both_yields(self, treasury_csv):
        # The taxable series starts 0.5pp higher; mixing the two would book a loss.
        rows = [(m, "long_term_partially_tax_exempt", "2.00") for m in _months(1927, 12, 11)]
        rows += [(m, "long_term_taxable", "2.50") for m in _months(1928, 10, 3)]
        bond = treasury_csv(rows)
        # January-October earn the 2% coupon, November-December the 2.5% coupon.
        assert bond["bond_return"].iloc[0] == pytest.approx((1 + 0.02 / 12) ** 10 * (1 + 0.025 / 12) ** 2 - 1, abs=1e-6)

    def test_gaps_and_unbridged_months_fail(self, treasury_csv):
        months = _months(1927, 12, 13)
        with pytest.raises(ValueError, match="skips from 1928-05 to 1928-07"):
            treasury_csv([(m, "ten_year_month_end", "3.00") for m in months if m != "1928-06"])
        rows = [(m, "long_term_taxable", "3.00") for m in months[:6]]
        rows += [(m, "ten_year_month_end", "3.00") for m in months[6:]]
        with pytest.raises(ValueError, match="no series with both 1928-05 and 1928-06"):
            treasury_csv(rows)
        with pytest.raises(ValueError, match="covers only part of"):
            treasury_csv([(m, "ten_year_month_end", "3.00") for m in months[:7]])
        with pytest.raises(ValueError, match="unknown series"):
            treasury_csv([(m, "gs10", "3.00") for m in months])

    def test_shipped_yields_match_published_values(self):
        raw = pd.read_csv(_TREASURY_CSV_PATH, dtype={"month": str}).set_index(["series", "month"])["yield_percent"]
        # H.15 10-year constant maturity, last business day of December.
        assert raw[("ten_year_month_end", "2008-12")] == 2.25
        assert raw[("ten_year_month_end", "2024-12")] == 4.58
        # Federal Reserve Bulletin, long-term Treasury bonds, December 1927 average.
        assert raw[("long_term_partially_tax_exempt", "1927-12")] == 3.17

    def test_1941_bond_return_stays_within_each_series(self):
        returns = load_historical_returns().set_index("year")
        # Splicing the series' year-end yields (1.89% -> 2.47%) would show a loss.
        assert returns.loc[1941, "bond_return"] == pytest.approx(0.009642, abs=1e-6)


class TestInflation:
    def test_inflation_is_december_over_december_cpi_u(self):
        returns = load_historical_returns().set_index("year")
        # BLS CPI-U NSA: December 2022 296.797, December 2023 306.746.
        assert returns.loc[2023, "inflation"] == pytest.approx(306.746 / 296.797 - 1, abs=1e-6)
        # December 1927 17.3, December 1928 17.1.
        assert returns.loc[1928, "inflation"] == pytest.approx(17.1 / 17.3 - 1, abs=1e-6)
