"""Sleeper contract. Fixtures are trimmed real responses (scripts/record_fixtures.py)."""
import pytest

from pipeline.adapters import sleeper
from pipeline.common import ContractError


def test_state(load):
    d = load("sleeper_state.json")
    sleeper.validate_state(d)
    for k in ("week", "season"):
        bad = {x: y for x, y in d.items() if x != k}
        with pytest.raises(ContractError, match=k):
            sleeper.validate_state(bad)


def test_league_normalizes_and_hides_owners(load):
    out = sleeper.normalize_league(load("sleeper_league.json"), load("sleeper_rosters.json"), load("sleeper_users.json"), "u1")
    assert out["name"] and out["teamCount"] == 12 and out["season"] == 2026
    assert out["scoring"]["rec"] == 1.0 and "QB" in out["rosterPositions"]
    mine = [t for t in out["teams"] if t["isMine"]]
    assert len(mine) == 1 and mine[0]["teamName"]
    assert any(t["teamName"].startswith("Team ") and t["teamName"].endswith("(no name set)") for t in out["teams"]), \
        "null team_name should fall back to 'Team N (no name set)'"
    blob = repr(out)
    assert "display_name" not in blob and "owner_id" not in blob and "user1" not in blob


@pytest.mark.parametrize("key", ["roster_positions", "scoring_settings", "total_rosters", "status"])
def test_league_missing_key_fails(load, key):
    d = load("sleeper_league.json")
    del d[key]
    with pytest.raises(ContractError, match=key):
        sleeper.validate_league(d)


def test_league_scoring_rename_fails(load):
    d = load("sleeper_league.json")
    d["scoring_settings"]["receptions"] = d["scoring_settings"].pop("rec")
    with pytest.raises(ContractError, match="rec"):
        sleeper.validate_league(d)


def test_rosters_users(load):
    sleeper.validate_rosters(load("sleeper_rosters.json"))
    sleeper.validate_users(load("sleeper_users.json"))
    r = load("sleeper_rosters.json")
    r[0]["players"] = "x"
    with pytest.raises(ContractError, match="players"):
        sleeper.validate_rosters(r)


def test_players(load):
    d = load("sleeper_players.json")
    out = sleeper.normalize_players(d)
    assert {p["pos"] for p in out.values()} <= {"QB", "RB", "WR", "TE", "K", "DEF"}
    assert "LB" not in {p["pos"] for p in out.values()}
    first = next(iter(d))
    del d[first]["position"]
    with pytest.raises(ContractError, match="position"):
        sleeper.validate_players(d)


def test_projections(load):
    rows = load("sleeper_projections.json")
    sleeper.validate_rows(rows, "projections", season=2026, week=11, min_with_points=10)
    out = sleeper.normalize_rows(rows, "projections")
    assert out and all("pts_ppr" in r["stats"] for r in out), "placeholder rows must be dropped"
    assert not any(k.startswith("adp_") for r in out for k in r["stats"])
    assert {r["pos"] for r in out} >= {"QB", "RB", "WR", "TE", "K", "DEF"}


def test_projection_provider_change_fails_loudly(load):
    rows = load("sleeper_projections.json")
    for r in rows:
        r["company"] = "sleeper"
    with pytest.raises(ContractError, match="provider changed"):
        sleeper.validate_rows(rows, "projections")


def test_projection_points_field_removed_fails(load):
    rows = load("sleeper_projections.json")
    for r in rows:
        r["stats"].pop("pts_ppr", None)
    with pytest.raises(ContractError, match="pts_ppr"):
        sleeper.validate_rows(rows, "projections")


def test_projection_wrong_week_fails(load):
    with pytest.raises(ContractError, match="week"):
        sleeper.validate_rows(load("sleeper_projections.json"), "projections", week=3)


def test_stats(load):
    rows = load("sleeper_stats.json")
    sleeper.validate_rows(rows, "stats", season=2026, min_with_points=10)
    assert sleeper.normalize_rows(rows, "stats")
    for r in rows:
        r["stats"] = {}
    with pytest.raises(ContractError, match="pts_ppr"):
        sleeper.validate_rows(rows, "stats")


def test_league_keeps_faab_settings(load):
    out = sleeper.normalize_league(load("sleeper_league.json"), load("sleeper_rosters.json"), load("sleeper_users.json"), "u1")
    assert out["waiverType"] == 2 and out["waiverBudget"] == 100
    assert all(isinstance(t["faabUsed"], int) for t in out["teams"])


def test_faab_keys_are_optional_but_checked_when_present(load):
    d = load("sleeper_league.json")
    del d["settings"]["waiver_type"]
    del d["settings"]["waiver_budget"]
    sleeper.validate_league(d)                                # an older or non FAAB league still passes
    d = load("sleeper_league.json")
    d["settings"]["waiver_budget"] = "100"
    with pytest.raises(ContractError, match="waiver_budget"):
        sleeper.validate_league(d)
    r = load("sleeper_rosters.json")
    r[0]["settings"]["waiver_budget_used"] = "x"
    with pytest.raises(ContractError, match="waiver_budget_used"):
        sleeper.validate_rosters(r)
    r = load("sleeper_rosters.json")
    del r[0]["settings"]["waiver_budget_used"]
    sleeper.validate_rosters(r)


def test_league_keeps_playoff_settings(load):
    raw = load("sleeper_league.json")
    out = sleeper.normalize_league(raw, load("sleeper_rosters.json"), load("sleeper_users.json"), "u1")
    st = raw["settings"]
    assert out["playoffWeekStart"] == st.get("playoff_week_start") and out["playoffTeams"] == st.get("playoff_teams")


def test_traded_picks(load):
    rows = load("sleeper_traded_picks.json")
    sleeper.validate_traded_picks(rows)
    out = sleeper.normalize_traded_picks(rows)
    assert len(out) == len(rows) and {p["season"] for p in out} >= {"2026", "2027"}
    assert all(isinstance(p["rosterId"], int) and isinstance(p["ownerId"], int) for p in out)
    rows[0].pop("owner_id")
    with pytest.raises(ContractError, match="owner_id"):
        sleeper.validate_traded_picks(rows)


def test_traded_picks_season_shape_change_fails(load):
    rows = load("sleeper_traded_picks.json")
    rows[0]["season"] = "2027 draft"
    with pytest.raises(ContractError, match="season"):
        sleeper.validate_traded_picks(rows)
