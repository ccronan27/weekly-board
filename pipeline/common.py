"""Shared helpers: paths, errors, time, team codes, name normalization."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
BUILD = DATA / "build"
CONFIG = ROOT / "config"


class ContractError(Exception):
    """A source changed shape. Raised by adapter validators so tests fail loudly."""


# ------------------------------------------------------------------ source freshness
# One vocabulary for every reader of a source status (ingest log, run summary, build, site).
# See docs/STATES.md.
#   fresh    pulled this run and current
#   stale    usable but old: the pull failed and the last good copy is in use,
#            or (ESPN rosters) the sync is older than STALE_AFTER_DAYS
#   missing  nothing usable: the pull failed and there is no cached copy
FRESH, STALE, MISSING = "fresh", "stale", "missing"


def source_status(ok: bool, last_updated: str | None, error: str | None = None, stale: bool | None = None) -> dict:
    """A source status entry. The ok/stale booleans stay for older readers. state is the one to read."""
    stale = (not ok) if stale is None else stale
    entry = {"ok": ok, "stale": stale, "lastUpdated": last_updated, "error": error}
    entry["state"] = source_state(entry)
    return entry


def source_state(s: dict) -> str:
    """fresh, stale or missing. Derived from the booleans for entries written before state existed."""
    if not s.get("lastUpdated"):
        return MISSING
    if not s.get("ok") or s.get("stale"):
        return STALE
    return FRESH


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise ContractError(msg)


def require_keys(obj, keys, where: str) -> None:
    require(isinstance(obj, dict), f"{where}: expected object, got {type(obj).__name__}")
    missing = [k for k in keys if k not in obj]
    require(not missing, f"{where}: missing keys {missing}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")


# Canonical team codes are Sleeper's. nflverse uses LA for the Rams.
_TEAM_ALIASES = {
    "LA": "LAR", "WSH": "WAS", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LAR",
}


def norm_team(code: str | None) -> str | None:
    if not code:
        return None
    code = code.upper()
    return _TEAM_ALIASES.get(code, code)


# ESPN pro team ids to canonical codes
ESPN_TEAMS = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET",
    9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR", 15: "MIA", 16: "MIN",
    17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC",
    25: "SF", 26: "SEA", 27: "TB", 28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str) -> str:
    """Lowercase, strip .'’-, drop generational suffixes, collapse spaces."""
    s = name.lower()
    s = re.sub(r"[.'’\-]", "", s)
    parts = [p for p in s.split() if p not in _SUFFIX]
    return " ".join(parts)


def norm_pos(pos: str) -> str:
    """Canonical position labels. Sleeper DEF and ESPN D/ST both become DEF."""
    return "DEF" if pos in ("DEF", "D/ST", "DST") else pos


# ------------------------------------------------------------------ refresh schedule
# Scheduled runs of .github/workflows/refresh.yml. tests/test_refresh_schedule.py parses that file
# and fails when it and this table disagree. Times are America/Chicago.
REFRESH_TZ = "America/Chicago"
REFRESH_RUNS = [   # (day, hour, minute) in 24 hour time
    ("Tue", 21, 7),    # post-MNF baseline
    ("Thu", 14, 7),    # TNF injury reports
    ("Fri", 17, 7),    # final injury designations
    ("Sun", 9, 7),     # morning news
    ("Sun", 10, 47),   # inactives for noon games
    ("Sun", 13, 7),    # inactives for late games
    ("Sun", 17, 47),   # SNF inactives
    ("Mon", 17, 47),   # MNF inactives
]
_DAY_INDEX = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}   # datetime.weekday()


def next_refresh(generated_at) -> str:
    """The first scheduled run after generated_at (ISO string or datetime), as ISO UTC with a Z."""
    start = datetime.fromisoformat(generated_at) if isinstance(generated_at, str) else generated_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    tz = ZoneInfo(REFRESH_TZ)
    local = start.astimezone(tz)
    best = None
    for offset in range(8):   # one full week covers every weekly run
        day = local.date() + timedelta(days=offset)
        for name, hour, minute in REFRESH_RUNS:
            if day.weekday() != _DAY_INDEX[name]:
                continue
            cand = datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)
            if cand > start and (best is None or cand < best):
                best = cand
    return best.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
