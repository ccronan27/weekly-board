import copy
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def load():
    """Load a fixture. Always returns a deep copy so tests can mutate it."""
    def _load(name):
        p = FIX / name
        if name.endswith(".json"):
            return copy.deepcopy(json.loads(p.read_text(encoding="utf-8")))
        return p.read_text(encoding="utf-8")
    return _load
