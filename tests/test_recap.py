"""Recap unit tests on small hand-built inputs. The build-level check lives in test_build.py."""
import pytest

from pipeline import recap, scoring
from pipeline.common import read_json

SLOTS = ["RB", "WR", "FLEX"]


@pytest.fixture
def lg():
    # 0.1 per rushing yard, 1 per reception, 0.1 per receiving yard
    return scoring.League(key="t", name="Test", platform="sleeper",
                          scoring={"rush_yd": 0.1, "rec": 1.0, "rec_yd": 0.1}, starters=list(SLOTS))


def row(pid, pos, **stats):
    return {"playerId": pid, "pos": pos, "stats": stats}


def test_week_points_rescores_with_league_scoring(lg):
    rows = [row("1", "RB", rush_yd=100.0), row("2", "WR", rec=5.0, rec_yd=60.0)]
    pts = recap.week_points(lg, rows)
    assert pts == pytest.approx({"1": 10.0, "2": 11.0})


def test_optimal_fills_best_lineup_and_skips_ir_and_taxi(lg):
    roster = [{"id": "a", "pos": "RB", "slot": "START"}, {"id": "b", "pos": "RB", "slot": "BN"},
              {"id": "c", "pos": "WR", "slot": "START"}, {"id": "d", "pos": "WR", "slot": "IR"},
              {"id": "e", "pos": "WR", "slot": "TAXI"}]
    pts = {"a": 10.0, "b": 8.0, "c": 20.0, "d": 50.0, "e": 40.0}
    # RB takes a (10), WR takes c (20), FLEX takes b (8). d and e cannot start
    assert recap.optimal_points(lg, roster, pts) == 38.0


def test_optimal_counts_players_who_did_not_play_as_zero(lg):
    roster = [{"id": "a", "pos": "RB", "slot": "START"}]
    assert recap.optimal_points(lg, roster, {}) == 0.0


def test_platform_points_needs_a_real_score(lg):
    m = {"5": [{"rosterId": 3, "matchupId": 1, "points": 118.44}, {"rosterId": 4, "matchupId": 1, "points": 0.0}]}
    assert recap.platform_points(m, 5, 3) == 118.4
    assert recap.platform_points(m, 5, 4) is None      # 0 means no game data
    assert recap.platform_points(m, 6, 3) is None      # no such week
    assert recap.platform_points(None, 5, 3) is None   # ESPN league
    assert recap.platform_points(m, 5, None) is None


def test_recommended_file_round_trip_and_overwrite(tmp_path):
    recap.write_recommended(tmp_path, 2026, 10, "hwh", ["QB", "RB"], ["q1", None], "2026-11-15T12:00:00Z")
    assert read_json(recap.recommended_path(tmp_path, 2026, 10, "hwh"))["slots"] == [
        {"slot": "QB", "playerId": "q1"}, {"slot": "RB", "playerId": None}]
    assert recap.read_recommended(tmp_path, 2026, 10, "hwh") == ["q1", None]
    recap.write_recommended(tmp_path, 2026, 10, "hwh", ["QB", "RB"], ["q2", "r2"], "2026-11-16T12:00:00Z")
    assert recap.read_recommended(tmp_path, 2026, 10, "hwh") == ["q2", "r2"]
    assert recap.read_recommended(tmp_path, 2026, 9, "hwh") is None


def test_unreadable_recommended_file_counts_as_missing(tmp_path):
    p = recap.recommended_path(tmp_path, 2026, 10, "hwh")
    p.parent.mkdir(parents=True)
    p.write_text('{"slots": "nope"}')
    assert recap.read_recommended(tmp_path, 2026, 10, "hwh") is None


def test_league_recap_all_parts(lg, tmp_path):
    stats = {9: [row("a", "RB", rush_yd=100.0), row("c", "WR", rec=10.0), row("b", "RB", rush_yd=50.0)]}
    roster = [{"id": "a", "pos": "RB", "slot": "START"}, {"id": "b", "pos": "RB", "slot": "BN"},
              {"id": "c", "pos": "WR", "slot": "START"}]
    matchups = {"9": [{"rosterId": 7, "matchupId": 2, "points": 15.0}]}
    recap.write_recommended(tmp_path, 2026, 9, "t", SLOTS, ["a", "b", None], "2026-11-09T12:00:00Z")
    r = recap.league_recap(season=2026, week=10, lg=lg, roster=roster, stats=stats, matchups=matchups,
                           my_roster_id=7, raw_root=tmp_path)
    # optimal: RB a 10, WR c 10, FLEX b 5 = 25. recommended a + b = 15. actual 15
    assert r == {"week": 9, "actual": 15.0, "optimal": 25.0, "recommended": 15.0, "left": 10.0}


def test_league_recap_espn_has_no_actual_and_missing_recommendation_is_null(lg, tmp_path):
    stats = {9: [row("a", "RB", rush_yd=100.0)]}
    roster = [{"id": "a", "pos": "RB", "slot": "START"}]
    r = recap.league_recap(season=2026, week=10, lg=lg, roster=roster, stats=stats, matchups=None,
                           my_roster_id=None, raw_root=tmp_path)
    assert r == {"week": 9, "actual": None, "optimal": 10.0, "recommended": None, "left": None}


def test_league_recap_missing_stats_nulls_optimal_and_recommended(lg, tmp_path):
    matchups = {"9": [{"rosterId": 7, "matchupId": 2, "points": 99.0}]}
    r = recap.league_recap(season=2026, week=10, lg=lg, roster=[{"id": "a", "pos": "RB", "slot": "START"}],
                           stats={}, matchups=matchups, my_roster_id=7, raw_root=tmp_path)
    assert r == {"week": 9, "actual": 99.0, "optimal": None, "recommended": None, "left": None}


def test_league_recap_null_when_nothing_is_available(lg, tmp_path):
    assert recap.league_recap(season=2026, week=10, lg=lg, roster=[], stats={}, matchups=None,
                              my_roster_id=None, raw_root=tmp_path) is None


def test_first_week_has_no_recap(lg, tmp_path):
    stats = {1: [row("a", "RB", rush_yd=100.0)]}
    assert recap.league_recap(season=2026, week=1, lg=lg, roster=[{"id": "a", "pos": "RB", "slot": "START"}],
                              stats=stats, matchups=None, my_roster_id=None, raw_root=tmp_path) is None


def test_best_possible_below_actual_is_dropped(tmp_path, monkeypatch):
    """Re-scored stats can miss platform stat ids. A best possible under the real score is not shown."""
    from pipeline import recap as rc
    monkeypatch.setattr(rc, "week_points", lambda lg, rows: {"a": 10.0})
    monkeypatch.setattr(rc, "optimal_points", lambda lg, roster, pts: 150.0)
    out = rc.league_recap(season=2026, week=11, lg=type("L", (), {"key": "x"})(), roster=[{"id": "a"}],
                          stats={10: []}, matchups={"10": [{"rosterId": 1, "points": 160.0}]}, my_roster_id=1, raw_root=tmp_path)
    assert out["actual"] == 160.0 and out["optimal"] is None and out["left"] is None
