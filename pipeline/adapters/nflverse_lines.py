"""nflverse Vegas lines. spread_line = home expected margin, total_line = game total."""
from __future__ import annotations

import csv
import functools
import io

from pipeline import http
from pipeline.common import norm_team, require

URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
REQUIRED_COLUMNS = ["game_id", "season", "game_type", "week", "gameday", "gametime",
                    "away_team", "home_team", "spread_line", "total_line"]


@functools.lru_cache(maxsize=1)   # lines and schedule share one download per run
def fetch() -> str:
    return http.get(URL).text


def parse(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text)))


def validate(rows: list[dict], season: int | None = None) -> None:
    require(rows, "nflverse games: empty file")
    missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
    require(not missing, f"nflverse games: missing columns {missing}")
    if season is not None:
        require(any(r["season"] == str(season) for r in rows), f"nflverse games: no rows for season {season}")


def _num(v: str):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        raise ValueError(f"nflverse games: non-numeric line value {v!r}")


def normalize(rows: list[dict], season: int, week: int) -> list[dict]:
    """Games for one week with implied team totals. Lines may be None if not posted yet."""
    validate(rows, season)
    out = []
    for r in rows:
        if r["season"] != str(season) or r["week"] != str(week) or r["game_type"] != "REG":
            continue
        spread, total = _num(r["spread_line"]), _num(r["total_line"])
        implied_home = implied_away = None
        if spread is not None and total is not None:
            implied_home, implied_away = (total + spread) / 2, (total - spread) / 2
        out.append({
            "gameId": r["game_id"],
            "week": week,
            "gameday": r["gameday"],
            "gametime": r["gametime"] or None,
            "away": norm_team(r["away_team"]),
            "home": norm_team(r["home_team"]),
            "homeSpread": spread,   # positive = home favored
            "total": total,
            "impliedHome": implied_home,
            "impliedAway": implied_away,
        })
    return out


def normalize_schedule(rows: list[dict], season: int) -> list[dict]:
    """Every regular season game this season, for playoff week matchups and byes. No lines."""
    validate(rows, season)
    return [{"week": int(r["week"]), "away": norm_team(r["away_team"]), "home": norm_team(r["home_team"])}
            for r in rows if r["season"] == str(season) and r["game_type"] == "REG"]
