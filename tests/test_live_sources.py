"""Live contract checks against the real endpoints. Not run by default: pytest -m live

These run in GitHub Actions too, which doubles as the check that ESPN leaguedefaults is
reachable from a runner without credentials. Only leaguedefaults is called on ESPN.
"""
import pytest

from pipeline.adapters import espn_defaults, nflverse_lines, sleeper

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def state():
    d = sleeper.fetch_state()
    sleeper.validate_state(d)
    return int(d["season"]), d["week"]


def test_sleeper_state_and_leagues():
    from pipeline.ingest import load_config
    for lg in load_config()["leagues"]:
        if lg["platform"] == "sleeper":
            lid = str(lg["id"])
            out = sleeper.normalize_league(sleeper.fetch_league(lid), sleeper.fetch_rosters(lid), sleeper.fetch_users(lid), None)
            assert out["name"] == lg["name"] and len(out["teams"]) == out["teamCount"]


def test_sleeper_players():
    assert len(sleeper.normalize_players(sleeper.fetch_players())) > 1000


def test_sleeper_projections(state):
    rows = sleeper.fetch_projections(*state)
    sleeper.validate_rows(rows, "projections", season=state[0], week=state[1], min_with_points=150)


def test_sleeper_stats(state):
    season, week = state
    if week < 2:
        pytest.skip("no completed week yet")
    sleeper.validate_rows(sleeper.fetch_stats(season, week - 1), "stats", season=season, min_with_points=100)


def test_espn_leaguedefaults(state):
    season, week = state
    d = espn_defaults.fetch(season, week)
    out = espn_defaults.normalize(d, season, week)
    by_pos = {}
    for p in out:
        if p["projection"]:
            by_pos[p["pos"]] = by_pos.get(p["pos"], 0) + 1
    assert all(by_pos.get(pos, 0) >= 10 for pos in ("QB", "RB", "WR", "TE")), by_pos
    assert by_pos.get("K", 0) >= 5 and by_pos.get("DEF", 0) >= 5, by_pos


def test_nflverse_lines(state):
    season, week = state
    games = nflverse_lines.normalize(nflverse_lines.parse(nflverse_lines.fetch()), season, week)
    assert games, f"no games for {season} week {week}"
