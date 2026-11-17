"""Fetch every source, cache raw pulls, and record per-source status.

Each source is isolated. If one fails the others still run, the last good cache is kept,
and the source is marked stale. Raw files live in data/raw/{season}/{week}/.

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
from pipeline.common import CONFIG, RAW, ContractError, now_iso, read_json, write_json


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
        status[name] = {"ok": True, "stale": False, "lastUpdated": fetched, "error": None}
    except Exception as e:  # noqa: BLE001 - isolate every failure, report it, keep going
        kind = "contract" if isinstance(e, ContractError) else type(e).__name__
        msg = f"{kind}: {e}"[:500]
        print(f"[ingest] {name} FAILED: {msg}", file=sys.stderr)
        if not isinstance(e, ContractError):
            traceback.print_exc(file=sys.stderr)
        if path.exists():
            old = read_json(path)
            status[name] = {"ok": False, "stale": True, "lastUpdated": old.get("fetchedAt"), "error": msg}
        else:
            status[name] = {"ok": False, "stale": True, "lastUpdated": None, "error": msg}


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
            out[lg["key"]] = sleeper.normalize_league(
                sleeper.fetch_league(lid), sleeper.fetch_rosters(lid), sleeper.fetch_users(lid),
                cfg.get("sleeperUserId"))
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

    # ESPN rosters come from the committed file only. Never the network.
    try:
        r = espn_rosters.load()
        status["espn_rosters"] = {"ok": True, "stale": espn_rosters.is_stale(r), "lastUpdated": r["syncedAt"],
                                  "error": None if r["week"] == week else f"roster file is for week {r['week']}"}
    except Exception as e:  # noqa: BLE001
        status["espn_rosters"] = {"ok": False, "stale": True, "lastUpdated": None, "error": f"{type(e).__name__}: {e}"[:500]}

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
        flag = "ok " if v["ok"] else ("STALE" if v["lastUpdated"] else "MISSING")
        print(f"{flag:8}{k:24}{v['lastUpdated'] or '-'}  {v['error'] or ''}")
    # Fail the run only if nothing usable exists at all. A single stale source still publishes.
    essential = ("sleeper_leagues", "sleeper_players", "sleeper_projections")
    usable = [k for k in essential if out["sources"][k]["lastUpdated"]]
    return 0 if usable else 1


if __name__ == "__main__":
    sys.exit(main())
