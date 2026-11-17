"""Pair-accuracy metric used by scripts/backtest.py, on small synthetic data."""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("backtest", REPO / "scripts" / "backtest.py")
bt = importlib.util.module_from_spec(_spec)
sys.modules["backtest"] = bt   # dataclasses look the module up while it loads
_spec.loader.exec_module(bt)


def test_perfect_and_reversed_order():
    actual = [20, 15, 10, 5]
    g = ["WR"] * 4
    assert bt.pair_accuracy([4, 3, 2, 1], actual, g) == 1.0
    assert bt.pair_accuracy([1, 2, 3, 4], actual, g) == 0.0


def test_pairs_only_within_group():
    # Within each group the order is right. Across groups it would be wrong, but those pairs never count
    pred = [10, 9, 30, 29]
    actual = [2, 1, 50, 40]
    assert bt.pair_counts(pred, actual, ["RB", "RB", "WR", "WR"]) == (2.0, 2)


def test_actual_ties_dropped_and_projection_ties_count_half():
    # pairs: (a,b) actual tie -> dropped; (a,c) right; (b,c) projection tie -> half
    pred = [12, 10, 10]
    actual = [8, 8, 3]
    assert bt.pair_counts(pred, actual, ["TE"] * 3) == (1.5, 2)


def test_mixed_case_by_hand():
    # 4 players, 6 pairs
    pred = [20, 18, 15, 9]
    actual = [25, 10, 12, 4]
    # (0,1) R, (0,2) R, (0,3) R, (1,2) W, (1,3) R, (2,3) R -> 5 of 6
    assert bt.pair_accuracy(pred, actual, ["WR"] * 4) == pytest.approx(5 / 6)


def test_tuple_groups_and_flex_kinds():
    groups = [(1, "RB"), (1, "RB"), (2, "RB"), (2, "RB")]
    assert bt.pair_counts([2, 1, 1, 2], [9, 3, 9, 3], groups) == (1.0, 2)
    # FLEX: only cross-position pairs inside a week count
    kinds = ["RB", "RB", "WR"]
    right, n = bt.pair_counts([3, 2, 1], [1, 2, 3], [1, 1, 1], kinds)
    assert n == 2 and right == 0.0


def test_start_sit_uses_startable_rows_by_average():
    pw = bt.PlayerWeek
    rows = [pw(1, "WR", "a", "X", 20, 20, 30), pw(1, "WR", "b", "X", 12, 12, 10),
            pw(1, "WR", "c", "X", 6, 6, 40)]   # c projects 6, not startable, so its big game is ignored
    assert bt.start_sit(rows, [r.avg for r in rows]) == 1.0
