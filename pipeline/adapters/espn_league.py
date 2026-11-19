"""ESPN league data from the public league endpoint. No login, no credentials.

The league was made viewable to the public on 11/19/26, so its rosters, settings, standings,
schedule and past lineups are readable without credentials. If the league goes private again,
these calls fail, the run marks the source stale, and the board falls back to
data/espn/rosters.json (which the Claude espn-roster-sync skill can still write).

Owner identities are never read or stored. The response carries a `members` list and team
`owners` ids. Both are dropped here, before anything is cached. Teams keep their name only.

Two calls:
  league(season, league_id)          rosters, settings, standings, schedule with scores
  week_lineups(season, league_id, w) every team's starters and points for a past week (Shotguns)
"""
from __future__ import annotations

from datetime import datetime, timezone

from pipeline import http
from pipeline.common import ESPN_TEAMS, require, require_keys

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leagues/{league_id}"
LEAGUE_VIEWS = ["mTeam", "mRoster", "mSettings", "mMatchup"]
WEEK_VIEWS = ["mBoxscore", "mMatchupScore"]

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "D/ST"}
SLOT = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 20: "BN", 21: "IR", 23: "FLEX"}
BENCH = {20, 21}
DST_SLOT = "16"   # pointsOverrides key for D/ST
ACTUAL = 0        # statSourceId
PROJECTION = 1


def _url(season: int, league_id: int) -> str:
    return BASE.format(season=season, league_id=league_id)


def fetch_league(season: int, league_id: int) -> dict:
    return http.get_json(_url(season, league_id), params=[("view", v) for v in LEAGUE_VIEWS])


def fetch_week(season: int, league_id: int, week: int) -> dict:
    return http.get_json(_url(season, league_id), params=[("view", v) for v in WEEK_VIEWS] + [("scoringPeriodId", week)])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


# ---------------------------------------------------------------- league

def validate_league(d) -> None:
    require(isinstance(d, dict), "espn league: response is not an object")
    require_keys(d, ["id", "seasonId", "scoringPeriodId", "settings", "teams", "schedule", "status"], "espn league")
    s = d["settings"]
    require_keys(s, ["name", "rosterSettings", "scoringSettings", "scheduleSettings"], "espn league settings")
    require_keys(s["rosterSettings"], ["lineupSlotCounts"], "espn league rosterSettings")
    require(s["scoringSettings"].get("scoringItems"), "espn league: no scoringItems")
    for i in s["scoringSettings"]["scoringItems"]:
        require_keys(i, ["statId", "points"], "espn league scoringItem")
    require_keys(s["scheduleSettings"], ["matchupPeriodCount", "playoffTeamCount"], "espn league scheduleSettings")
    require(isinstance(d["teams"], list) and d["teams"], "espn league: no teams")
    for t in d["teams"]:
        require_keys(t, ["id", "name", "record", "roster"], "espn league team")
        require_keys(t["record"].get("overall") or {}, ["wins", "losses", "ties", "pointsFor", "pointsAgainst"], "espn league team record")
        require(isinstance(t["roster"].get("entries"), list), f"espn league: team {t['id']} has no roster entries")
        for e in t["roster"]["entries"]:
            require_keys(e, ["playerId", "lineupSlotId", "playerPoolEntry"], "espn league roster entry")
            require(e["lineupSlotId"] in SLOT, f"espn league: unknown lineupSlotId {e['lineupSlotId']}")
            p = e["playerPoolEntry"].get("player") or {}
            require_keys(p, ["fullName", "defaultPositionId", "proTeamId"], "espn league player")
            require(p["defaultPositionId"] in POS, f"espn league: unknown defaultPositionId {p['defaultPositionId']}")
    for g in d["schedule"]:
        require_keys(g, ["matchupPeriodId", "home", "winner"], "espn league schedule row")


def normalize_league(d: dict) -> dict:
    """The data/espn/rosters.json schema (docs/SPEC.md), built from the public league response.
    Only team ids and names are kept. members and owners are never read."""
    validate_league(d)
    s = d["settings"]
    items = s["scoringSettings"]["scoringItems"]
    teams = sorted(d["teams"], key=lambda t: t["id"])
    week = d["scoringPeriodId"]
    schedule = []
    for g in d["schedule"]:
        if not g.get("away"):   # byes have no away side
            continue
        row = {"week": g["matchupPeriodId"], "homeTeamId": g["home"]["teamId"], "awayTeamId": g["away"]["teamId"]}
        if g["winner"] != "UNDECIDED":
            row["homePoints"] = round(float(g["home"].get("totalPoints") or 0), 2)
            row["awayPoints"] = round(float(g["away"].get("totalPoints") or 0), 2)
        schedule.append(row)
    return {
        "ok": True,
        "platform": "espn",
        "source": "espn_public_api",
        "leagueId": int(d["id"]),
        "season": int(d["seasonId"]),
        "week": int(week),
        "syncedAt": _now_iso(),
        "settings": {
            "name": s["name"],
            "teams": len(teams),
            "lineupSlotCounts": {str(k): int(v) for k, v in s["rosterSettings"]["lineupSlotCounts"].items()},
            "scoringByStatId": {str(i["statId"]): i["points"] for i in items},
            "dstScoringByStatId": {str(i["statId"]): (i.get("pointsOverrides") or {}).get(DST_SLOT, i["points"]) for i in items},
            "playoffWeekStart": int(s["scheduleSettings"]["matchupPeriodCount"]) + 1,
            "playoffTeams": int(s["scheduleSettings"]["playoffTeamCount"]),
        },
        "teams": [{
            "teamId": t["id"],
            "name": (t.get("name") or f"Team {t['id']}").strip(),
            "roster": [{
                "espnId": e["playerId"],
                "name": e["playerPoolEntry"]["player"]["fullName"],
                "pos": POS[e["playerPoolEntry"]["player"]["defaultPositionId"]],
                "proTeamId": e["playerPoolEntry"]["player"]["proTeamId"] if e["playerPoolEntry"]["player"]["proTeamId"] in ESPN_TEAMS else 0,
                "slot": SLOT[e["lineupSlotId"]],
                "injuryStatus": e.get("injuryStatus") or e["playerPoolEntry"]["player"].get("injuryStatus") or "ACTIVE",
            } for e in t["roster"]["entries"]],
        } for t in teams],
        "standings": [{"teamId": t["id"], **{k: t["record"]["overall"][k] for k in ("wins", "losses", "ties", "pointsFor", "pointsAgainst")}}
                      for t in teams],
        "schedule": schedule,
    }


# ---------------------------------------------------------------- past week lineups

def validate_week(d, week: int) -> None:
    require(isinstance(d, dict), "espn week: response is not an object")
    require_keys(d, ["scoringPeriodId", "schedule"], "espn week")
    require(d["scoringPeriodId"] == week, f"espn week: asked for week {week}, got {d['scoringPeriodId']}")
    rows = [g for g in d["schedule"] if g.get("matchupPeriodId") == week]
    require(rows, f"espn week: no matchups for week {week}")
    for g in rows:
        for side in ("home", "away"):
            h = g.get(side)
            if not h:
                continue
            r = h.get("rosterForCurrentScoringPeriod")
            require(isinstance(r, dict) and isinstance(r.get("entries"), list), f"espn week {week}: team {h.get('teamId')} has no lineup")
            for e in r["entries"]:
                require_keys(e, ["lineupSlotId", "playerPoolEntry"], "espn week entry")
                require("appliedStatTotal" in e["playerPoolEntry"], "espn week entry: no appliedStatTotal")


def _projected(player: dict, week: int):
    for st in player.get("stats") or []:
        if st.get("scoringPeriodId") == week and st.get("statSourceId") == PROJECTION:
            return round(float(st.get("appliedTotal") or 0), 1)
    return None


def normalize_week(d: dict, week: int) -> list[dict]:
    """Every team's starters for one week with their points in this league's scoring.
    [{teamId, points, starters: [{espnId, name, pos, slot, points, projected}]}]"""
    validate_week(d, week)
    out = []
    for g in d["schedule"]:
        if g.get("matchupPeriodId") != week:
            continue
        for side in ("home", "away"):
            h = g.get(side)
            if not h:
                continue
            starters = []
            for e in h["rosterForCurrentScoringPeriod"]["entries"]:
                if e["lineupSlotId"] in BENCH:
                    continue
                p = e["playerPoolEntry"].get("player") or {}
                starters.append({
                    "espnId": e.get("playerId", p.get("id")),
                    "name": p.get("fullName", "Unknown"),
                    "pos": POS.get(p.get("defaultPositionId"), "?"),
                    "slot": SLOT.get(e["lineupSlotId"], str(e["lineupSlotId"])),
                    "points": round(float(e["playerPoolEntry"]["appliedStatTotal"] or 0), 2),
                    "projected": _projected(p, week),
                })
            out.append({"teamId": h["teamId"], "points": round(float(h.get("totalPoints") or 0), 2), "starters": starters})
    return out
