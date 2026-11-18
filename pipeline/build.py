"""Build data/build/*.json from cached raw pulls. The site reads only data/build/.

Outputs (all carry generatedAt and per-source lastUpdated):
  meta.json                 run info, per-source status, notes on the model
  {league}.json             your team: current lineup vs recommended lineup, full roster
  pool-{league}.json        every projected player scored under that league (for v2 waivers)

    python -m pipeline.build [--season 2026 --week 11]
"""
from __future__ import annotations

import argparse
import statistics
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pipeline import lineup, players as pm, scoring, waivers
from pipeline.adapters import espn_rosters
from pipeline.common import BUILD, ESPN_TEAMS, RAW, ContractError, norm_team, normalize_name, now_iso, read_json, write_json
from pipeline.ingest import load_config

EASTERN = ZoneInfo("America/New_York")
OUT_STATUSES = {"OUT", "IR", "SUSPENDED", "INACTIVE"}


class BuildError(Exception):
    """Raised instead of publishing an empty or broken board."""


# ------------------------------------------------------------------ loading

def _load(d, name):
    p = d / f"{name}.json"
    return read_json(p) if p.exists() else None


def load_raw(season: int, week: int, raw_root=RAW) -> dict:
    d = raw_root / str(season) / str(week)
    status = _load(d, "status")
    if status is None:
        raise BuildError(f"no ingest status at {d}. Run python -m pipeline.ingest first")
    stats = {}
    for w in range(1, week):
        f = _load(raw_root / str(season) / str(w), "sleeper_stats")
        if f:
            stats[w] = f["data"]
    return {
        "status": status,
        "leagues": (_load(d, "sleeper_leagues") or {}).get("data"),
        "players": (_load(d, "sleeper_players") or {}).get("data"),
        "projections": (_load(d, "sleeper_projections") or {}).get("data") or [],
        "espn": (_load(d, "espn_defaults") or {}).get("data") or [],
        "lines": (_load(d, "nflverse_lines") or {}).get("data") or [],
        "stats": stats,
    }


# ------------------------------------------------------------------ helpers

def normalize_status(raw: str | None, platform: str, sleeper_status: str | None = None) -> str | None:
    """One status vocabulary: OUT, IR, DOUBTFUL, QUESTIONABLE, SUSPENDED, INACTIVE, or None."""
    s = (raw or "").upper().replace(" ", "_")
    table = {"OUT": "OUT", "IR": "IR", "INJURY_RESERVE": "IR", "DOUBTFUL": "DOUBTFUL", "QUESTIONABLE": "QUESTIONABLE",
             "PUP": "OUT", "NA": "OUT", "SUS": "SUSPENDED", "SUSPENDED": "SUSPENDED", "COV": "OUT", "DNR": "OUT"}
    out = table.get(s)
    if out is None and (sleeper_status or "").lower() in ("inactive", "injured reserve"):
        out = "IR" if (sleeper_status or "").lower() == "injured reserve" else "INACTIVE"
    return out


def game_context(lines: list[dict]) -> dict:
    """team -> game info from this week's nflverse rows. Teams absent from the dict are on a bye."""
    ctx = {}
    for g in lines:
        kickoff = None
        if g.get("gametime") and g.get("gameday"):
            local = datetime.fromisoformat(f"{g['gameday']}T{g['gametime']}").replace(tzinfo=EASTERN)
            kickoff = local.astimezone(timezone.utc).isoformat(timespec="minutes").replace("+00:00", "Z")
        for team, opp, home in ((g["home"], g["away"], True), (g["away"], g["home"], False)):
            imp = g["impliedHome"] if home else g["impliedAway"]
            opp_imp = g["impliedAway"] if home else g["impliedHome"]
            spread = None if g["homeSpread"] is None else (-g["homeSpread"] if home else g["homeSpread"])
            ctx[team] = {"opp": opp, "home": home, "kickoff": kickoff, "total": g["total"],
                         "implied": None if imp is None else round(imp, 1),
                         "oppImplied": None if opp_imp is None else round(opp_imp, 1),
                         "spread": spread}    # from this team's side. Negative means favored
    return ctx


def parse_kickoff(s: str | None) -> datetime | None:
    """game_context kickoff format, e.g. 2026-11-22T18:00Z (UTC, minutes precision)."""
    return None if not s else datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def _r(x, n=1):
    return None if x is None else round(x, n)


# ------------------------------------------------------------------ main build

def build(season: int, week: int, raw_root=RAW, out_dir=BUILD, rosters_path=None, save_idmap: bool = True,
          now: datetime | None = None) -> dict:
    cfg = load_config()
    raw = load_raw(season, week, raw_root)
    if not raw["players"]:
        raise BuildError("no Sleeper player data cached, cannot identify anyone")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    generated = now_iso()
    sources = raw["status"]["sources"]
    sleeper_players = raw["players"]
    games = game_context(raw["lines"])

    rosters = espn_rosters.load(rosters_path) if rosters_path else espn_rosters.load()

    # ---- identity: ESPN id <-> Sleeper id
    espn_rows = {p["espnId"]: p for p in raw["espn"]}
    entries = [{"espnId": p["espnId"], "name": p["name"], "pos": p["pos"], "team": p["team"]} for p in raw["espn"]]
    for t in rosters["teams"]:
        for p in t["roster"]:
            if p["espnId"] not in espn_rows:
                entries.append({"espnId": p["espnId"], "name": p["name"], "pos": p["pos"], "team": ESPN_TEAMS.get(p["proTeamId"])})
    idmap, unmatched = pm.resolve_espn(entries, sleeper_players, pm.load_idmap())
    if save_idmap:
        pm.save_idmap(idmap)
    espn_of = {}
    for eid, pid in idmap.items():
        if pid not in espn_of or eid in espn_rows:
            espn_of[pid] = eid

    # ---- projection pools and which stats each source projects at all
    rw_rows = {r["playerId"]: r for r in raw["projections"]}
    support = scoring.Support.build([(r["pos"], scoring.rotowire_to_canon(r["stats"], r["pos"])) for r in raw["projections"]],
                                    [(p["pos"], scoring.espn_to_canon(p["projection"]["stats"], p["pos"])) for p in raw["espn"] if p["projection"]])

    # ---- weekly actuals by player (Sleeper), for each player's own SD
    actuals: dict = {}
    for w, rows in raw["stats"].items():
        for r in rows:
            actuals.setdefault(r["playerId"], {})[str(w)] = r["stats"]

    # ---- leagues
    leagues = []
    for lc in cfg["leagues"]:
        if lc["platform"] == "espn":
            leagues.append((lc, scoring.league_from_espn(lc["key"], rosters)))
        else:
            norm = (raw["leagues"] or {}).get(lc["key"])
            if norm is None:
                raise BuildError(f"no cached Sleeper league data for {lc['key']}")
            leagues.append((lc, scoring.league_from_sleeper(lc["key"], norm), norm))

    def player_record(pid, espn_id, lg: scoring.League, roster_status=None, roster_meta=None):
        """Everything the board needs about one player under one league's scoring."""
        sp = sleeper_players.get(pid) if pid else None
        er = espn_rows.get(espn_id) if espn_id is not None else None
        rw = rw_rows.get(pid) if pid else None
        pos = (sp or {}).get("pos") or (er or {}).get("pos") or (roster_meta or {}).get("pos")
        name = (sp or {}).get("name") or (er or {}).get("name") or (roster_meta or {}).get("name") or str(pid)
        team = (sp or {}).get("team") or (er or {}).get("team") or (roster_meta or {}).get("team")
        proj = scoring.project_player(lg, pos, rw["stats"] if rw else None,
                                      er["projection"]["stats"] if er and er["projection"] else None, support) if pos else \
            {"points": None, "espn": None, "rotowire": None, "sources": [], "filled": []}
        weekly = scoring.weekly_points(lg, pos, actuals.get(pid, {})) if pos and pid else []
        fc = scoring.floor_ceiling(proj["points"], weekly)
        # Sleeper injury data is refreshed every run, the ESPN roster file can be days old.
        # Use Sleeper when the player is matched, otherwise fall back to the roster file.
        if sp is not None:
            status = normalize_status(sp.get("injuryStatus"), "sleeper", sp.get("status")) or normalize_status((rw or {}).get("injuryStatus"), "sleeper")
        else:
            status = normalize_status(roster_status, lg.platform)
        game = games.get(team) if team else None
        bye = bool(team) and bool(games) and game is None
        flags = [f for f in (("BYE" if bye else None), status) if f]
        eligible = pos is not None and not bye and status not in OUT_STATUSES
        kickoff = parse_kickoff(game["kickoff"]) if game else None
        locked = kickoff is not None and kickoff <= now    # kicked off, the player can no longer be moved
        return {
            "id": pid or f"espn:{espn_id}", "name": name, "pos": pos, "team": team,
            "points": _r(proj["points"]), "espn": _r(proj["espn"]), "rotowire": _r(proj["rotowire"]),
            "sources": proj["sources"], "floor": fc["floor"], "ceiling": fc["ceiling"], "sd": fc["sd"], "games": fc["games"],
            "ppg": round(statistics.fmean(weekly), 1) if weekly else None,   # season points per game, this league's scoring
            "status": status, "flags": flags, "eligible": eligible, "game": game, "locked": locked,
            "injuryNotes": sp.get("injuryNotes") if sp else None,
            "_filled": proj["filled"],
        }

    outputs = {}
    n_filled = 0
    for entry in leagues:
        lc, lg = entry[0], entry[1]
        slots = lg.starters
        rostered: dict = {}   # player id -> (team name, slot)
        rostered_names: set = set()   # (normalized name, pos). Guards the free agent list against unmatched ESPN ids
        my_players: list = []

        if lc["platform"] == "espn":
            for t in rosters["teams"]:
                for p in t["roster"]:
                    pid = idmap.get(p["espnId"])
                    rec = player_record(pid, p["espnId"], lg, roster_status=p["injuryStatus"],
                                        roster_meta={"name": p["name"], "pos": "DEF" if p["pos"] == "D/ST" else p["pos"],
                                                     "team": ESPN_TEAMS.get(p["proTeamId"])})
                    rec["slot"] = {"D/ST": "DEF"}.get(p["slot"], p["slot"])
                    rostered[rec["id"]] = (t["name"], rec["slot"])
                    rostered_names.add((normalize_name(rec["name"]), rec["pos"]))
                    if t["teamId"] == cfg["espnTeamId"]:
                        my_players.append(rec)
            team_name = next(t["name"] for t in rosters["teams"] if t["teamId"] == cfg["espnTeamId"])
            cur = _espn_current(slots, my_players)
        else:
            norm = entry[2]
            mine = next((t for t in norm["teams"] if t["isMine"]), None)
            if mine is None:
                raise BuildError(f"could not find your team in {lc['key']}")
            team_name = mine["teamName"]
            for t in norm["teams"]:
                for pid in t["players"]:
                    rostered[pid] = (t["teamName"], None)
                if t is mine:
                    start_ids = t["starters"]
                    for pid in t["players"]:
                        rec = player_record(pid, espn_of.get(pid), lg)
                        rec["slot"] = "IR" if pid in t["reserve"] else "TAXI" if pid in t["taxi"] else \
                            "START" if pid in start_ids else "BN"
                        my_players.append(rec)
            order = [p for p in norm["rosterPositions"] if p not in scoring.NOT_STARTERS]
            slots = order
            cur = _sleeper_current(order, mine["starters"])

        for p in my_players:   # IR and taxi players cannot start without a roster move. Only real IR gets the flag
            if p["slot"] in ("IR", "TAXI"):
                p["eligible"] = False
                if p["slot"] == "IR" and "IR" not in p["flags"]:
                    p["flags"].append("IR")
        by_id = {p["id"]: p for p in my_players}
        pos_of = {p["id"]: p["pos"] for p in my_players}
        # locked starters stay where they are, bench players that are locked cannot be moved in
        fixed = {i: c for i, c in enumerate(cur) if c is not None and by_id[c]["locked"]}
        for p in my_players:
            if p["locked"] and p["id"] not in fixed.values():
                p["eligible"] = False
        pts = {p["id"]: (p["points"] or 0.0) if p["eligible"] else 0.0 for p in my_players}   # a locked OUT starter scores 0 but keeps the slot
        chosen = lineup.recommend(slots, [{"id": p["id"], "pos": p["pos"], "points": p["points"] or 0.0, "eligible": p["eligible"]} for p in my_players],
                                  fixed=fixed)
        rec_slots = lineup.arrange(slots, chosen, cur, pos_of, fixed=fixed)
        mv = lineup.moves(slots, cur, rec_slots, pts, pos_of)

        def brief(pid):
            if pid is None:
                return None
            p = by_id[pid]
            return {k: p[k] for k in ("id", "name", "pos", "team", "points", "espn", "rotowire", "floor", "ceiling", "flags",
                                      "eligible", "game", "injuryNotes", "locked", "ppg", "games")}

        cur_total = round(sum(pts.get(c, 0.0) for c in cur if c), 1)
        rec_total = round(sum(pts.get(r, 0.0) for r in rec_slots if r), 1)
        if rec_total < cur_total:
            raise BuildError(f"{lc['key']}: recommended {rec_total} below current {cur_total}, optimizer bug")
        for p in my_players:
            n_filled += len(p["_filled"])
            p.pop("_filled")
        src_used = ["sleeper_projections", "espn_defaults", "nflverse_lines"] + (["espn_rosters"] if lc["platform"] == "espn" else ["sleeper_leagues", "sleeper_players"])
        out = {
            "generatedAt": generated, "season": season, "week": week,
            "league": {"key": lc["key"], "name": lg.name, "platform": lg.platform, "teamName": team_name},
            "sources": {k: sources[k] for k in src_used if k in sources},
            "lineup": {
                "slots": [{"slot": slots[i], "current": brief(cur[i]), "recommended": brief(rec_slots[i]),
                           "changed": cur[i] != rec_slots[i]} for i in range(len(slots))],
                "currentPoints": cur_total, "recommendedPoints": rec_total, "gain": round(rec_total - cur_total, 1),
                "moves": [{"in": brief(m["in"]), "out": brief(m["out"]), "slot": m["slot"], "gain": m["gain"]} for m in mv],
                "alerts": [{"player": p["name"], "slot": s, "flags": p["flags"]} for s, pid in zip(slots, cur) if pid
                           for p in [by_id[pid]] if any(f in ("BYE", *OUT_STATUSES) for f in p["flags"])],
                "watch": [{"player": p["name"], "slot": s, "flags": p["flags"], "kickoff": (p["game"] or {}).get("kickoff"),
                           "injuryNotes": p["injuryNotes"]} for s, pid in zip(slots, cur) if pid
                          for p in [by_id[pid]] if p["status"] in ("QUESTIONABLE", "DOUBTFUL")],
            },
            "roster": sorted(my_players, key=lambda p: (-(p["points"] or 0), p["name"])),
            "scoringNotes": lg.notes,
        }
        # ---- full pool for v2: every player either source projects, under this league's scoring
        pool = []
        seen = set()
        ids = list(rw_rows) + [pid for eid, pid in idmap.items() if eid in espn_rows and espn_rows[eid]["projection"]]
        for pid in ids:
            if pid in seen:
                continue
            seen.add(pid)
            rec = player_record(pid, espn_of.get(pid), lg)
            if rec["points"] is None:
                continue
            owner = rostered.get(pid)
            rec["rostered"] = owner is not None
            rec["teamName"] = owner[0] if owner else None
            rec.pop("_filled", None)
            pool.append(rec)
        pool.sort(key=lambda p: -(p["points"] or 0))
        write_json(out_dir / f"pool-{lc['key']}.json", {"generatedAt": generated, "season": season, "week": week,
                                                         "league": lc["key"], "sources": out["sources"], "players": pool})

        # ---- v2 waiver targets: free agents scored by how much they raise your best lineup this week
        fas = [p for p in pool if not p["rostered"] and (normalize_name(p["name"]), p["pos"]) not in rostered_names]
        fa_by = {p["id"]: p for p in fas}

        def fa_brief(pid):
            p = fa_by[pid]
            return {k: p[k] for k in ("id", "name", "pos", "team", "points", "espn", "rotowire", "floor", "ceiling", "flags",
                                      "eligible", "game", "injuryNotes", "locked", "ppg", "games")}

        mine_in = [{"id": p["id"], "pos": p["pos"], "points": p["points"], "eligible": p["eligible"]} for p in my_players]
        fa_in = [{"id": p["id"], "pos": p["pos"], "points": p["points"], "eligible": p["eligible"], "locked": p["locked"]} for p in fas]
        rec_set = {r for r in rec_slots if r}
        positions = list(dict.fromkeys(s for s in slots if s not in scoring.FLEX_ELIGIBLE))
        dynasty = bool(lc.get("dynasty"))
        drop = None if dynasty else waivers.drop_candidate(
            [p for p in my_players if p["id"] not in rec_set and p["slot"] not in ("IR", "TAXI")])
        out["waivers"] = {
            "freeAgents": len(fas), "dynasty": dynasty,
            "targets": [{"player": fa_brief(t["id"]), "gain": t["gain"], "slot": t["slot"],
                         "replaces": brief(t["replaces"])}
                        for t in waivers.diversify(waivers.targets(slots, mine_in, fa_in, fixed), {p["id"]: p["pos"] for p in fas})],
            "byPosition": {pos: [fa_brief(i) for i in ids] for pos, ids in waivers.best_by_position(positions, fa_in).items()},
            "drop": brief(drop),
        }
        outputs[lc["key"]] = out
        write_json(out_dir / f"{lc['key']}.json", out)

    # ---- meta
    sync_age = espn_rosters.age_days(rosters)
    meta = {
        "generatedAt": generated, "season": season, "week": week,
        "sources": sources,
        "espnRosters": {"syncedAt": rosters["syncedAt"], "ageDays": round(sync_age, 2), "stale": espn_rosters.is_stale(rosters),
                        "week": rosters["week"], "weekMismatch": rosters["week"] != week},
        "model": "Equal average of ESPN and Rotowire projections, each re-scored with the league's scoring. Floor and ceiling are one weekly SD below and above.",
        "idmap": {"matched": len(idmap), "unmatchedEspnPlayers": len(unmatched)},
        "gapFills": n_filled,
        "leagues": [{"key": k, "name": o["league"]["name"], "file": f"{k}.json", "gain": o["lineup"]["gain"]} for k, o in outputs.items()],
    }
    write_json(out_dir / "meta.json", meta)

    # Never publish an empty board
    for k, o in outputs.items():
        if not any(s["recommended"] for s in o["lineup"]["slots"]) or o["lineup"]["recommendedPoints"] <= 0 or o["lineup"]["gain"] < 0:
            raise BuildError(f"{k}: recommended lineup is empty, refusing to publish")
    return {"meta": meta, "leagues": outputs}


def _espn_current(slots: list[str], recs: list[dict]) -> list:
    """Current ESPN lineup as a list aligned to slots. FLEX players sit in FLEX slots."""
    cur: list = [None] * len(slots)
    for r in recs:
        if r["slot"] in ("BN", "IR"):
            continue
        for i, s in enumerate(slots):
            if cur[i] is None and s == r["slot"]:
                cur[i] = r["id"]
                break
    return cur


def _sleeper_current(order: list[str], starters: list[str]) -> list:
    """Sleeper starters are index aligned with the non-bench slots. '0' means empty."""
    cur = [None] * len(order)
    for i, pid in enumerate(starters[:len(order)]):
        cur[i] = None if pid in ("0", 0, None) else pid
    return cur


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    a = ap.parse_args(argv)
    from pipeline.ingest import resolve_week
    season, week = resolve_week(a.season, a.week)
    try:
        res = build(season, week)
    except (BuildError, ContractError) as e:
        print(f"[build] REFUSING TO PUBLISH: {e}", file=sys.stderr)
        return 1
    for k, o in res["leagues"].items():
        print(f"{k:18} current {o['lineup']['currentPoints']:6.1f}  recommended {o['lineup']['recommendedPoints']:6.1f}  gain {o['lineup']['gain']:+.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
