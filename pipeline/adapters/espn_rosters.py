"""ESPN league rosters and settings, read from data/espn/rosters.json only.

The file is written by the Claude espn-roster-sync skill. This module never touches the
network and never logs in to ESPN.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pipeline.common import DATA, ESPN_TEAMS, read_json, require, require_keys

PATH = DATA / "espn" / "rosters.json"
SLOTS = {"QB", "RB", "WR", "TE", "K", "D/ST", "FLEX", "BN", "IR"}
TEAM_KEYS = {"teamId", "name", "roster"}  # anything else (e.g. owner fields) fails the contract
PLAYER_KEYS = {"espnId", "name", "pos", "proTeamId", "slot", "injuryStatus"}
STALE_AFTER_DAYS = 4


def load(path: Path = PATH) -> dict:
    d = read_json(path)
    validate(d)
    return d


def validate(d) -> None:
    require_keys(d, ["ok", "platform", "leagueId", "season", "week", "syncedAt", "settings", "teams"], "espn rosters.json")
    require(d["ok"] is True, "espn rosters.json: ok is not true, the last sync failed")
    require(d["platform"] == "espn", f"espn rosters.json: platform {d['platform']!r}")
    require(isinstance(d["leagueId"], int), "espn rosters.json: leagueId not an int")
    parse_synced_at(d["syncedAt"])
    s = d["settings"]
    require_keys(s, ["name", "teams", "lineupSlotCounts", "scoringByStatId"], "espn rosters.json settings")
    require(isinstance(s["scoringByStatId"], dict) and s["scoringByStatId"], "espn rosters.json: scoringByStatId empty")
    require(all(isinstance(v, (int, float)) for v in s["scoringByStatId"].values()), "espn rosters.json: non numeric scoring value")
    require(isinstance(s["lineupSlotCounts"], dict) and s["lineupSlotCounts"], "espn rosters.json: lineupSlotCounts empty")
    teams = d["teams"]
    require(isinstance(teams, list) and len(teams) == s["teams"], f"espn rosters.json: expected {s['teams']} teams, got {len(teams) if isinstance(teams, list) else teams!r}")
    for t in teams:
        extra = set(t) - TEAM_KEYS
        require(not extra, f"espn rosters.json: unexpected team fields {sorted(extra)} (owner data must not be stored)")
        require_keys(t, sorted(TEAM_KEYS), "espn rosters.json team")
        require(t["roster"], f"espn rosters.json: team {t['teamId']} has an empty roster")
        for p in t["roster"]:
            require_keys(p, sorted(PLAYER_KEYS), "espn rosters.json player")
            require(p["slot"] in SLOTS, f"espn rosters.json: unknown slot {p['slot']!r}")
            require(p["proTeamId"] in ESPN_TEAMS or p["proTeamId"] == 0, f"espn rosters.json: unknown proTeamId {p['proTeamId']!r}")


def parse_synced_at(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        require(False, f"espn rosters.json: bad syncedAt {s!r}")


def age_days(d: dict, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    return (now - parse_synced_at(d["syncedAt"])).total_seconds() / 86400


def is_stale(d: dict, now: datetime | None = None) -> bool:
    return age_days(d, now) > STALE_AFTER_DAYS
