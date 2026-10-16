import json
from pathlib import Path


def load_standard_plan() -> dict:
    path = Path(__file__).parent / "standard_plan.json"
    return json.loads(path.read_text())
