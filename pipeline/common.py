"""Shared helpers: paths, errors, time, team codes, name normalization."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

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
