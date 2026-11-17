"""ESPN leaguedefaults contract. Only the leaguedefaults endpoint is ever called."""
import pytest

from pipeline.adapters import espn_defaults as ed
from pipeline.common import ContractError

W, S = 11, 2026


def test_normalize(load):
    out = ed.normalize(load("espn_defaults.json"), S, W)
    assert {p["pos"] for p in out} >= {"QB", "RB", "WR", "TE", "K", "DEF"}
    proj = [p for p in out if p["projection"]]
    assert proj and all(isinstance(p["projection"]["appliedTotal"], float) for p in proj)
    assert all(p["team"] for p in proj), "proTeamId must map to a team code"
    assert all(p["injuryStatus"] for p in out), "missing injuryStatus defaults to ACTIVE"
    assert any(p["actuals"] for p in out)
    assert all(int(wk) < W for p in out for wk in p["actuals"]), "actuals only for weeks before the current one"


def test_week_projection_selection_rule(load):
    """Projection is statSourceId 1 + statSplitTypeId 1 at the requested scoringPeriodId, never an actual."""
    d = load("espn_defaults.json")
    def has(x, wk, src):
        return any(s["scoringPeriodId"] == wk and s["statSourceId"] == src and s.get("stats") for s in x["player"]["stats"])
    p = next(x for x in d["players"] if has(x, W, 1) and has(x, W - 1, 0))  # needs both entries to test the rule
    for s in p["player"]["stats"]:
        if s["scoringPeriodId"] == W and s["statSourceId"] == 1:
            s["appliedTotal"], s["stats"] = 99.0, {"24": 1.0}
        if s["scoringPeriodId"] == W - 1 and s["statSourceId"] == 0:
            s["appliedTotal"] = 7.5
    out = {x["espnId"]: x for x in ed.normalize(d, S, W)}[p["id"]]
    assert out["projection"]["appliedTotal"] == 99.0
    assert out["actuals"][str(W - 1)] == 7.5


@pytest.mark.parametrize("path", [("players",), ("player", "fullName"), ("player", "defaultPositionId"), ("player", "proTeamId"), ("player", "stats")])
def test_missing_key_fails(load, path):
    d = load("espn_defaults.json")
    if path == ("players",):
        d = {"athletes": d["players"]}
    else:
        del d["players"][0][path[0]][path[1]]
    with pytest.raises(ContractError):
        ed.validate(d, week=W, season=S)


def test_stat_entry_field_rename_fails(load):
    d = load("espn_defaults.json")
    s = d["players"][0]["player"]["stats"][0]
    s["sourceId"] = s.pop("statSourceId")
    with pytest.raises(ContractError, match="statSourceId"):
        ed.validate(d)


def test_no_weekly_projection_fails(load):
    d = load("espn_defaults.json")
    for p in d["players"]:
        for s in p["player"]["stats"]:
            if s["statSourceId"] == 1:
                s["statSourceId"] = 2
    with pytest.raises(ContractError, match="no weekly projection"):
        ed.validate(d, week=W, season=S)


def test_unknown_position_fails(load):
    d = load("espn_defaults.json")
    d["players"][0]["player"]["defaultPositionId"] = 99
    with pytest.raises(ContractError, match="defaultPositionId"):
        ed.validate(d)


def test_truncation_guard(load):
    d = load("espn_defaults.json")
    d["players"] = d["players"][:1] * ed.LIMIT
    with pytest.raises(ContractError, match="limit"):
        ed.validate(d)


def test_filter_header_shape():
    import json
    f = json.loads(ed._filter([0, 2, 4, 6]))
    assert f["players"]["limit"] == 1200 and f["players"]["filterSlotIds"]["value"] == [0, 2, 4, 6]
