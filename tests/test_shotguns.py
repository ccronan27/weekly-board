"""Shotgun counts: any starter, K or D/ST at 0 or less in a week is one shotgun. Bench never counts."""
import json
from pathlib import Path

import pytest

from pipeline import shotguns as sg
from pipeline.common import BUILD

NAMES = {1: "Alpha", 2: "Bravo", 3: "Charlie"}


def lineup(tid, *pts):
    return {"teamId": tid, "points": 100.0, "starters": [
        {"espnId": i, "name": f"P{tid}{i}", "pos": "WR", "slot": "WR", "points": p, "projected": 9.0} for i, p in enumerate(pts)]}


def test_zero_and_negative_count_positive_does_not():
    rows = sg.week_counts([lineup(1, 0.0, -2.0, 0.1), lineup(2, 5.0)], NAMES, mine_id=2)
    a = next(r for r in rows if r["name"] == "Alpha")
    assert a["count"] == 2 and [p["points"] for p in a["players"]] == [-2.0, 0.0]
    assert next(r for r in rows if r["name"] == "Bravo") == {"name": "Bravo", "isMine": True, "count": 0, "players": []}
    assert rows[0]["name"] == "Alpha", "most shotguns first"


def test_unknown_team_is_skipped():
    assert sg.week_counts([lineup(9, 0.0)], NAMES, 1) == []


def test_season_totals_and_newest_week_first():
    weekly = {8: [lineup(1, 0.0), lineup(2, 0.0, 0.0), lineup(3, 4.0)],
              9: [lineup(1, -1.0), lineup(2, 3.0), lineup(3, 2.0)]}
    b = sg.season_block(weekly, NAMES, mine_id=1)
    assert [w["week"] for w in b["weeks"]] == [9, 8]
    assert b["seasonTotal"] == 4
    assert [(r["name"], r["total"], r["weeksHit"]) for r in b["totals"]] == [("Alpha", 2, 2), ("Bravo", 2, 1), ("Charlie", 0, 0)]
    assert b["totals"][0]["isMine"] is True


def test_no_weeks_is_none():
    assert sg.season_block({}, NAMES, 1) is None


@pytest.mark.skipif(not (BUILD / "fantasizing.json").exists(), reason="no build")
def test_built_board_carries_shotguns_for_the_espn_league_only():
    assert "shotguns" in json.loads((BUILD / "fantasizing.json").read_text(encoding="utf-8"))
    for k in ("hwh", "chicago-dynasty"):
        assert "shotguns" not in json.loads((BUILD / f"{k}.json").read_text(encoding="utf-8"))


def test_flag_on_a_sleeper_league_is_ignored():
    """The rule belongs to the ESPN league. The build only computes it for ESPN leagues."""
    import inspect
    from pipeline import build
    assert 'lc.get("shotguns") and lc["platform"] == "espn"' in inspect.getsource(build.build)
