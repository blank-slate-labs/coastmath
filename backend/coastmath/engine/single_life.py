"""Complete IRS 2022 Single Life Table, Pub.590-B Appendix B Table I."""
import json
from pathlib import Path

_DATA = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'irs_single_life_table_2022.json').read_text())
SINGLE_LIFE_TABLE = {int(age): float(value) for age,value in _DATA['divisors'].items()}


def single_life_divisor(age: int) -> float:
    if age < 0:
        raise ValueError('Beneficiary age cannot be negative')
    return SINGLE_LIFE_TABLE[min(age,120)]
