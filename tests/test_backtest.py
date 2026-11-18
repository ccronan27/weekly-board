"""scripts/backtest.py metrics on synthetic rows. No network."""
import importlib.util
import math
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("backtest", Path(__file__).resolve().parent.parent / "scripts" / "backtest.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


def row(week, pos, espn, rw, actual, team="AAA"):
    return {"week": week, "pos": pos, "espn": espn, "rw": rw, "actual": actual, "team": team}


def test_relevant_uses_the_equal_average():
    rows = bt.relevant([row(1, "WR", 6, 5, 1), row(1, "WR", 4, 5, 1)])
    assert len(rows) == 1 and rows[0]["avg"] == 5.5


def test_pair_accuracy_counts_startable_pairs_at_one_position():
    rows = bt.relevant([row(1, "WR", 20, 20, 30), row(1, "WR", 10, 10, 5), row(1, "WR", 9, 9, 12),
                        row(1, "RB", 15, 15, 1), row(1, "WR", 6, 6, 50)])   # last one is not startable
    pred = [r["avg"] for r in rows]
    # WR pairs: (20,10) right, (20,9) right, (10,9) wrong. The RB has no pair
    assert bt.pair_accuracy(rows, pred) == pytest.approx(2 / 3)


def test_ties_are_skipped_and_flex_pairs_cross_positions_only():
    rows = bt.relevant([row(1, "WR", 10, 10, 10), row(1, "WR", 9, 9, 10), row(1, "RB", 12, 12, 3), row(1, "QB", 20, 20, 1)])
    pred = [r["avg"] for r in rows]
    assert math.isnan(bt.pair_accuracy(rows, pred))   # the only WR pair ties on actual, so no pairs count
    # FLEX: RB vs each WR, QB excluded: RB 12 projected over WRs but scored less, both wrong
    assert bt.pair_accuracy(rows, pred, flex=True) == 0.0


def test_vegas_multiplier_and_fit():
    rows = bt.relevant([row(1, "WR", 10, 10, 15, "HI"), row(1, "WR", 11, 11, 8, "LO")])
    imp = {(1, "HI"): 30.0, (1, "LO"): 15.0}
    assert bt.vegas(rows, imp, 22.5, lambda _: 0.0) == [10.0, 11.0]
    assert bt.fit_b(rows, imp, 22.5) > 0          # only a Vegas tilt orders this pair correctly
    missing = bt.vegas([dict(rows[0], team="NONE")], imp, 22.5, lambda _: 1.0)
    assert missing == [10.0]                      # no line, no change


def test_bootstrap_diff_is_zero_for_identical_models():
    rows = bt.relevant([row(w, "WR", 10 + i, 10 + i, (i * 7 + w) % 11) for w in range(1, 6) for i in range(4)])
    pred = [r["avg"] for r in rows]
    assert bt.bootstrap_diff(rows, pred, pred, n=50) == (0.0, 0.0)
