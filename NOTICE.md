# Data sources and attribution

CoastMath's code is licensed as described in [LICENSE](LICENSE). The published
figures it ships with come from the sources below, each under its own terms.
Every statutory value cites its source in the data itself: the `_sources` key of
a file under `backend/coastmath/data/` or the docstring of the module that loads
a CSV file.

## Historical market data

Used by the Monte Carlo and historical stress tests
(`backend/coastmath/engine/historical_data.py` derives every return from the
published values; the CSV files hold only those values).

- **S&P 500 index levels and dividends, 1927–2025**
  (`backend/coastmath/data/sp500_dividends.csv`): the "S&P 500 & Raw Data"
  sheet of Aswath Damodaran's `histretSP.xls`, NYU Stern,
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html.
  Published for free use:
  https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datahistory.html#rules.
- **U.S. Treasury yields, 1927–2024** (`backend/coastmath/data/treasury_yields.csv`):
  Federal Reserve H.15 10-year constant maturity series
  (https://www.federalreserve.gov/releases/h15/; FRED `GS10` and `DGS10`), and
  for 1927–1953 long-term Treasury bond yields from the Federal Reserve Bulletin
  and Treasury Bulletin as digitized in the NBER Macrohistory Database, series
  m13033a and m13033b (FRED `M1333AUSM156NNBR` and `M1333BUSM156NNBR`). Data
  retrieved from FRED, Federal Reserve Bank of St. Louis,
  https://fred.stlouisfed.org/.
- **Consumer Price Index, 1927–2024** (`backend/coastmath/data/cpi_u.csv`):
  U.S. Bureau of Labor Statistics, CPI-U all items, U.S. city average, not
  seasonally adjusted, series `CUUR0000SA0`,
  https://data.bls.gov/timeseries/CUUR0000SA0.

## United States tax and benefit rules

Federal and state figures come from the statutes and regulations and from the
pages of the agencies that administer them: the Internal Revenue Service, the
Social Security Administration, the Centers for Medicare & Medicaid Services,
and each state's department of revenue or taxation. These are works of the
United States government or of a state and carry no copyright restriction on
the figures.

## Software

Third-party packages are listed with their versions in
`backend/requirements.txt` and `frontend/package.json`; each is distributed
under its own open-source licence.
