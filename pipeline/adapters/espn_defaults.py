"""ESPN default projections (leaguedefaults). No login, no league endpoints, ever.

Only this one URL pattern is used:
  lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3
The spec filter covers QB, RB, WR, TE (slots 0,2,4,6). A second call with slots 16,17 adds
K and D/ST from the same endpoint. Raw stat lines stay keyed by ESPN stat id for re-scoring.
"""
from __future__ import annotations

import json

from pipeline import http
from pipeline.common import ESPN_TEAMS, require, require_keys

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3"
LIMIT = 1200
SLOT_GROUPS = ([0, 2, 4, 6], [16, 17])
POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
PROJECTION, ACTUAL = 1, 0  # statSourceId
WEEKLY = 1  # statSplitTypeId


def _filter(slots) -> str:
    return json.dumps({"players": {"limit": LIMIT, "filterSlotIds": {"value": list(slots)},
                                   "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}},
                      separators=(",", ":"))


def fetch(season: int, week: int) -> dict:
    players = []
    for slots in SLOT_GROUPS:
        d = http.get_json(BASE.format(season=season),
                          params={"view": "kona_player_info", "scoringPeriodId": week},
                          headers={"X-Fantasy-Filter": _filter(slots)})
        validate(d, week=week, season=season)
        players.extend(d["players"])
    return {"players": players}


def validate(d, week: int | None = None, season: int | None = None, min_players: int = 1) -> None:
    require_keys(d, ["players"], "espn defaults")
    ps = d["players"]
    require(isinstance(ps, list) and len(ps) >= min_players, f"espn defaults: expected >= {min_players} players")
    require(len(ps) < LIMIT, f"espn defaults: {len(ps)} players hit the {LIMIT} limit, results may be truncated")
    for p in ps:
        require_keys(p, ["id", "player"], "espn defaults entry")
        pl = p["player"]
        require_keys(pl, ["fullName", "defaultPositionId", "proTeamId", "stats"], "espn defaults player")
        require(pl["defaultPositionId"] in POS, f"espn defaults: unknown defaultPositionId {pl['defaultPositionId']!r}")
        require(isinstance(pl["stats"], list), "espn defaults: player.stats not a list")
        for s in pl["stats"]:
            require_keys(s, ["scoringPeriodId", "statSourceId", "statSplitTypeId", "seasonId"], "espn defaults stat entry")
            # Some placeholder entries (e.g. season total, period 0) have no stats map at all
            st = s.get("stats", {})
            require(isinstance(st, dict), "espn defaults: stat entry stats not an object")
            if st:
                require("appliedTotal" in s, "espn defaults: appliedTotal missing")
    if week is not None:
        proj = [s for p in ps for s in p["player"]["stats"]
                if s["scoringPeriodId"] == week and s["statSourceId"] == PROJECTION
                and s["statSplitTypeId"] == WEEKLY and s.get("stats")
                and (season is None or s["seasonId"] == season)]
        require(proj, f"espn defaults: no weekly projection found for week {week} (statSourceId=1, statSplitTypeId=1)")


def normalize(d: dict, season: int, week: int) -> list:
    """One record per player: this week's projection plus actuals for weeks before it."""
    validate(d, week=week, season=season)
    out = []
    for p in d["players"]:
        pl = p["player"]
        proj = None
        actuals = {}
        for s in pl["stats"]:
            if s["seasonId"] != season or s["statSplitTypeId"] != WEEKLY or not s.get("stats"):
                continue
            wk = s["scoringPeriodId"]
            if s["statSourceId"] == PROJECTION and wk == week:
                proj = {"stats": s["stats"], "appliedTotal": s["appliedTotal"]}
            elif s["statSourceId"] == ACTUAL and 1 <= wk < week:
                actuals[str(wk)] = s["appliedTotal"]  # default PPR points only, keeps the cache small
        out.append({
            "espnId": p["id"],
            "name": pl["fullName"],
            "pos": POS[pl["defaultPositionId"]],
            "proTeamId": pl["proTeamId"],
            "team": ESPN_TEAMS.get(pl["proTeamId"]),
            "injuryStatus": pl.get("injuryStatus") or "ACTIVE",  # absent on D/ST and some free agents
            "projection": proj,
            "actuals": actuals,
        })
    return out
