"""Sleeper adapter: state, leagues, rosters, players, projections (Rotowire), actual stats.

Official v1 API is read-only and needs no auth. The projections and stats endpoints are
unofficial, so their validators are strict. Owner identity never leaves this module:
only team_name is kept, plus an isMine flag.
"""
from __future__ import annotations

from pipeline import http
from pipeline.common import ContractError, norm_pos, norm_team, require, require_keys

V1 = "https://api.sleeper.app/v1"
UNOFFICIAL = "https://api.sleeper.app"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
EXPECTED_PROVIDER = "rotowire"


# ---------- fetch ----------

def fetch_state() -> dict:
    return http.get_json(f"{V1}/state/nfl")


def fetch_league(league_id: str) -> dict:
    return http.get_json(f"{V1}/league/{league_id}")


def fetch_rosters(league_id: str) -> list:
    return http.get_json(f"{V1}/league/{league_id}/rosters")


def fetch_users(league_id: str) -> list:
    return http.get_json(f"{V1}/league/{league_id}/users")


def fetch_matchups(league_id: str, week: int) -> list:
    return http.get_json(f"{V1}/league/{league_id}/matchups/{week}")


def fetch_players() -> dict:
    return http.get_json(f"{V1}/players/nfl")


def _pos_params(positions):
    return [("season_type", "regular")] + [("position[]", p) for p in positions]


def fetch_projections(season: int, week: int, positions=POSITIONS) -> list:
    return http.get_json(f"{UNOFFICIAL}/projections/nfl/{season}/{week}", params=_pos_params(positions))


def fetch_stats(season: int, week: int, positions=POSITIONS) -> list:
    return http.get_json(f"{UNOFFICIAL}/stats/nfl/{season}/{week}", params=_pos_params(positions))


# ---------- validate (contract) ----------

def validate_state(d) -> None:
    require_keys(d, ["week", "season", "season_type", "leg"], "sleeper state")
    require(isinstance(d["week"], int) and 0 <= d["week"] <= 25, f"sleeper state: bad week {d['week']!r}")
    require(str(d["season"]).isdigit(), f"sleeper state: bad season {d['season']!r}")


def validate_league(d) -> None:
    require_keys(d, ["league_id", "name", "season", "status", "total_rosters", "roster_positions",
                     "scoring_settings", "settings"], "sleeper league")
    require(isinstance(d["roster_positions"], list) and d["roster_positions"], "sleeper league: roster_positions empty")
    ss = d["scoring_settings"]
    require(isinstance(ss, dict), "sleeper league: scoring_settings not an object")
    for k in ("rec", "pass_yd", "pass_td", "rush_yd", "rush_td", "rec_yd", "rec_td"):
        require(k in ss, f"sleeper league: scoring_settings missing {k!r}")
        require(isinstance(ss[k], (int, float)), f"sleeper league: scoring_settings[{k!r}] not numeric")


def validate_rosters(d) -> None:
    require(isinstance(d, list) and d, "sleeper rosters: expected non-empty list")
    for r in d:
        require_keys(r, ["roster_id", "owner_id", "players"], "sleeper roster")
        require(isinstance(r["players"], list), "sleeper roster: players not a list")
        for k in ("starters", "reserve", "taxi"):
            require(r.get(k) is None or isinstance(r[k], list), f"sleeper roster: {k} not a list")


def validate_users(d) -> None:
    require(isinstance(d, list) and d, "sleeper users: expected non-empty list")
    for u in d:
        require_keys(u, ["user_id", "metadata"], "sleeper user")


def validate_matchups(d) -> None:
    require(isinstance(d, list), "sleeper matchups: expected list")
    for m in d:
        require_keys(m, ["roster_id", "matchup_id", "points"], "sleeper matchup")
        require(m["points"] is None or isinstance(m["points"], (int, float)), "sleeper matchups: points not numeric")


def normalize_matchups(d) -> list:
    """One row per roster: rosterId, matchupId (None when unpaired), points (0 before the game)."""
    validate_matchups(d)
    return [{"rosterId": m["roster_id"], "matchupId": m["matchup_id"], "points": float(m["points"] or 0.0)} for m in d]


def validate_players(d, min_players: int = 1) -> None:
    require(isinstance(d, dict) and len(d) >= min_players, f"sleeper players: expected object with >= {min_players} entries")
    for pid, p in list(d.items())[:50]:
        require_keys(p, ["position", "team", "first_name", "last_name"], f"sleeper player {pid}")


def validate_rows(d, kind: str, min_rows: int = 1, season: int | None = None, week: int | None = None,
                  min_with_points: int = 1) -> None:
    """Shared validator for projections and stats rows.

    Most rows are placeholders that carry only ADP keys. A row has a real stat line only when
    pts_ppr is present, so the contract is a minimum count of rows with numeric pts_ppr.
    """
    require(isinstance(d, list) and len(d) >= min_rows, f"sleeper {kind}: expected >= {min_rows} rows, got {len(d) if isinstance(d, list) else type(d).__name__}")
    for r in d:
        require_keys(r, ["player_id", "stats", "player", "team", "week", "season"], f"sleeper {kind} row")
        require(isinstance(r["stats"], dict), f"sleeper {kind}: stats not an object")
        require_keys(r["player"], ["position", "first_name", "last_name"], f"sleeper {kind} player")
        if season is not None:
            require(str(r["season"]) == str(season), f"sleeper {kind}: season {r['season']!r} != {season}")
        if week is not None:
            require(r["week"] == week, f"sleeper {kind}: week {r['week']!r} != {week}")
    with_pts = [r for r in d if "pts_ppr" in r["stats"]]
    require(len(with_pts) >= min_with_points,
            f"sleeper {kind}: only {len(with_pts)} rows have pts_ppr, expected >= {min_with_points}")
    require(all(isinstance(r["stats"]["pts_ppr"], (int, float)) for r in with_pts),
            f"sleeper {kind}: pts_ppr is not numeric on some row")
    if kind == "projections":
        providers = {r.get("company") for r in d}
        require(providers == {EXPECTED_PROVIDER},
                f"sleeper projections: provider changed, expected only {EXPECTED_PROVIDER!r}, saw {sorted(map(str, providers))}")


# ---------- normalize ----------

def normalize_league(league: dict, rosters: list, users: list, my_user_id: str | None) -> dict:
    validate_league(league)
    validate_rosters(rosters)
    validate_users(users)
    names = {}
    mine = set()
    for u in users:
        meta = u.get("metadata") or {}
        names[u["user_id"]] = meta.get("team_name")
        if my_user_id and u["user_id"] == str(my_user_id):
            mine.add(u["user_id"])
    teams = []
    for r in rosters:
        rid = r["roster_id"]
        st = r.get("settings") or {}
        teams.append({
            "record": {"wins": st.get("wins", 0), "losses": st.get("losses", 0), "ties": st.get("ties", 0),
                       "pointsFor": st.get("fpts", 0) + st.get("fpts_decimal", 0) / 100,
                       "pointsAgainst": st.get("fpts_against", 0) + st.get("fpts_against_decimal", 0) / 100,
                       "division": st.get("division")},
            "rosterId": rid,
            "teamName": names.get(r["owner_id"]) or f"Team {rid}",
            "isMine": r["owner_id"] in mine,
            "players": [str(p) for p in r["players"]],
            "starters": [str(p) for p in (r.get("starters") or [])],
            "reserve": [str(p) for p in (r.get("reserve") or [])],
            "taxi": [str(p) for p in (r.get("taxi") or [])],
        })
    return {
        "leagueId": str(league["league_id"]),
        "name": league["name"],
        "season": int(league["season"]),
        "status": league["status"],
        "teamCount": league["total_rosters"],
        "rosterPositions": league["roster_positions"],
        "playoffWeekStart": (league.get("settings") or {}).get("playoff_week_start"),
        "playoffTeams": (league.get("settings") or {}).get("playoff_teams"),
        "playoffRoundType": (league.get("settings") or {}).get("playoff_round_type"),
        "divisions": (league.get("settings") or {}).get("divisions") or 0,   # 0 one week a round, 1 two week final, 2 two weeks a round
        "scoring": league["scoring_settings"],
        "teams": teams,
    }


def normalize_players(d: dict) -> dict:
    """Keep fantasy positions only. Drops the rest of the 14 MB dump."""
    validate_players(d)
    out = {}
    for pid, p in d.items():
        pos = p.get("position")
        if pos not in POSITIONS:
            continue
        out[str(pid)] = {
            "name": f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip() or str(pid),
            "pos": norm_pos(pos),
            "team": norm_team(p.get("team")),
            "status": p.get("status"),
            "injuryStatus": p.get("injury_status"),
            "injuryNotes": p.get("injury_notes"),
            "active": bool(p.get("active")),
            "newsUpdated": p.get("news_updated"),
            "age": p.get("age"),
            "yearsExp": p.get("years_exp"),
        }
    return out


_DROP_PREFIXES = ("adp_", "pos_adp", "pos_rank")


def normalize_rows(d: list, kind: str) -> list:
    """Keep fantasy positions that have a stat line. Drops ranking noise from the stat map."""
    validate_rows(d, kind)
    out = []
    for r in d:
        pos = r["player"].get("position")
        if pos not in POSITIONS or "pts_ppr" not in r["stats"]:
            continue
        stats = {k: v for k, v in r["stats"].items() if not k.startswith(_DROP_PREFIXES)}
        out.append({
            "playerId": str(r["player_id"]),
            "name": f"{r['player']['first_name']} {r['player']['last_name']}".strip(),
            "pos": norm_pos(pos),
            "team": norm_team(r.get("team")),
            "opponent": norm_team(r.get("opponent")),
            "week": r["week"],
            "injuryStatus": r["player"].get("injury_status"),
            "stats": stats,
            "updatedAt": r.get("updated_at") or r.get("last_modified"),
        })
    return out
