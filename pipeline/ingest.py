"""Fetch every source, cache raw pulls, and record per-source status.

Each source is isolated. If one fails the others still run, the last good cache is kept,
and the source is marked stale. Raw files live in data/raw/{season}/{week}/.
Every source ends a run fresh, stale or missing (see pipeline.common and docs/STATES.md).

    python -m pipeline.ingest              # current week from Sleeper state
    python -m pipeline.ingest --week 11
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import yaml

from pipeline.adapters import espn_defaults, espn_rosters, nflverse_lines, sleeper
from pipeline.common import CONFIG, MISSING, RAW, ContractError, now_iso, read_json, source_status, source_state, write_json


def load_config() -> dict:
    with open(CONFIG / "leagues.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _cache_path(root: Path, season: int, week: int, name: str) -> Path:
    return root / str(season) / str(week) / f"{name}.json"


def _run_source(status: dict, root: Path, season: int, week: int, name: str, fn, wk_dir: int | None = None) -> None:
    """Run one fetch. On success write the cache. On failure keep the old cache and mark stale."""
    path = _cache_path(root, season, wk_dir if wk_dir is not None else week, name)
    try:
        data = fn()
        fetched = now_iso()
        write_json(path, {"source": name, "fetchedAt": fetched, "data": data})
        status[name] = source_status(True, fetched)
    except Exception as e:  # noqa: BLE001 - isolate every failure, report it, keep going
        kind = "contract" if isinstance(e, ContractError) else type(e).__name__
        msg = f"{kind}: {e}"[:500]
        print(f"[ingest] {name} FAILED: {msg}", file=sys.stderr)
        if not isinstance(e, ContractError):
            traceback.print_exc(file=sys.stderr)
        last = read_json(path).get("fetchedAt") if path.exists() else None
        status[name] = source_status(False, last, msg)    # stale with a cache, missing without one


def load_rosters(root: Path, season: int, week: int, path: Path | None = None) -> tuple[dict | None, str | None]:
    """The ESPN roster file, or the last good copy an earlier run cached when the file is unusable
    (the sync wrote ok: false, or a broken file). Returns (rosters, error):
      (rosters, None)   the committed file is good
      (rosters, error)  the committed file is bad, rosters is the newest cached copy this season
      (None, error)     nothing usable"""
    try:
        return (espn_rosters.load(path) if path else espn_rosters.load()), None
    except Exception as e:  # noqa: BLE001 - any unusable file falls back the same way
        error = f"{type(e).__name__}: {e}"[:500]
    for w in range(week, 0, -1):
        p = _cache_path(root, season, w, "espn_rosters")
        if not p.exists():
            continue
        try:
            d = read_json(p)["data"]
            espn_rosters.validate(d)
            return d, error
        except Exception:  # noqa: BLE001 - a bad cache is skipped, try an older week
            continue
    return None, error


def rosters_status(rosters: dict | None, error: str | None, week: int, now=None) -> dict:
    """Status entry for espn_rosters. A cached copy is stale. A good file is stale once the sync is old."""
    if rosters is None:
        return source_status(False, None, error)
    if error:
        return source_status(False, rosters["syncedAt"], f"{error}. Using the last good sync")
    mismatch = None if rosters["week"] == week else f"roster file is for week {rosters['week']}"
    return source_status(True, rosters["syncedAt"], mismatch, stale=espn_rosters.is_stale(rosters, now))


def resolve_week(season: int | None, week: int | None) -> tuple[int, int]:
    if season and week:
        return season, week
    try:
        st = sleeper.fetch_state()
        sleeper.validate_state(st)
        return season or int(st["season"]), week or st["week"]
    except Exception as e:  # noqa: BLE001
        print(f"[ingest] sleeper state failed ({e}), falling back to ESPN roster file", file=sys.stderr)
        r = espn_rosters.load()
        return season or r["season"], week or r["week"]


def run(season: int | None = None, week: int | None = None, root: Path = RAW) -> dict:
    cfg = load_config()
    season, week = resolve_week(season, week)
    status: dict = {}

    def leagues():
        out = {}
        for lg in cfg["leagues"]:
            if lg["platform"] != "sleeper":
                continue
            lid = str(lg["id"])
            norm = sleeper.normalize_league(
                sleeper.fetch_league(lid), sleeper.fetch_rosters(lid), sleeper.fetch_users(lid),
                cfg.get("sleeperUserId"))
            # every regular season week: past scores for the spread, future pairings for the odds
            last = (norm.get("playoffWeekStart") or 15) - 1
            norm["matchups"] = {str(w): sleeper.normalize_matchups(sleeper.fetch_matchups(lid, w)) for w in range(1, last + 1)}
            out[lg["key"]] = norm
        return out

    _run_source(status, root, season, week, "sleeper_leagues", leagues)
    _run_source(status, root, season, week, "sleeper_players", lambda: sleeper.normalize_players(sleeper.fetch_players()))
    _run_source(status, root, season, week, "sleeper_projections",
                lambda: sleeper.normalize_rows(sleeper.fetch_projections(season, week), "projections"))
    # Actual stats are cached under the week they belong to. Completed weeks are fetched once.
    # The most recent completed week is refetched each run to pick up stat corrections.
    for w in range(1, week):
        cached = _cache_path(root, season, w, "sleeper_stats").exists()
        if cached and w < week - 1:
            continue
        key = f"sleeper_stats_w{w}"
        _run_source(status, root, season, week, "sleeper_stats",
                    lambda w=w: sleeper.normalize_rows(sleeper.fetch_stats(season, w), "stats"), wk_dir=w)
        status[key] = status.pop("sleeper_stats")
    _run_source(status, root, season, week, "espn_defaults",
                lambda: espn_defaults.normalize(espn_defaults.fetch(season, week), season, week))

    def lines():
        rows = nflverse_lines.parse(nflverse_lines.fetch())
        return nflverse_lines.normalize(rows, season, week)

    _run_source(status, root, season, week, "nflverse_lines", lines)
    _run_source(status, root, season, week, "nflverse_schedule",
                lambda: nflverse_lines.normalize_schedule(nflverse_lines.parse(nflverse_lines.fetch()), season))

    # ESPN rosters come from the committed file only. Never the network. A good file is cached
    # like any other pull, so a bad sync later falls back to it instead of stopping the build.
    rosters, err = load_rosters(root, season, week)
    if rosters is not None and err is None:
        write_json(_cache_path(root, season, week, "espn_rosters"),
                   {"source": "espn_rosters", "fetchedAt": rosters["syncedAt"], "data": rosters})
    status["espn_rosters"] = rosters_status(rosters, err, week)

    out = {"generatedAt": now_iso(), "season": season, "week": week, "sources": status}
    write_json(root / str(season) / str(week) / "status.json", out)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    a = ap.parse_args(argv)
    out = run(a.season, a.week)
    for k, v in out["sources"].items():
        flag = {"fresh": "ok", "stale": "STALE", "missing": "MISSING"}[source_state(v)]
        print(f"{flag:8}{k:24}{v['lastUpdated'] or '-'}  {v['error'] or ''}")
    # Fail the run only if nothing usable exists at all. A single stale source still publishes.
    essential = ("sleeper_leagues", "sleeper_players", "sleeper_projections")
    usable = [k for k in essential if source_state(out["sources"][k]) != MISSING]
    return 0 if usable else 1


if __name__ == "__main__":
    sys.exit(main())
