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

from pipeline import lineup, odds, players as pm, recap, scoring, trades, waivers
from pipeline.adapters import espn_rosters
from pipeline.common import BUILD, ESPN_TEAMS, RAW, ContractError, norm_team, normalize_name, next_refresh, now_iso, read_json, source_state, write_json
from pipeline.ingest import load_config, load_rosters, rosters_status

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
        "schedule": (_load(d, "nflverse_schedule") or {}).get("data") or [],
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


def week_matchups(schedule: list[dict]) -> dict:
    """week -> team -> (opponent, home). A team missing from a week is on a bye."""
    out: dict = {}
    for g in schedule:
        out.setdefault(g["week"], {})[g["home"]] = (g["away"], True)
        out[g["week"]][g["away"]] = (g["home"], False)
    return out


def defense_ranks(stats: dict, lg) -> dict:
    """(team, pos) -> rank by fantasy points allowed to that position per game this season,
    under this league's scoring. 1 allows the most. For DEF it ranks the offense DEFs faced.
    Context for playoff matchups only. It never changes a score."""
    week_pts: dict = {}
    for w, rows in stats.items():
        for r in rows:
            if not r.get("opponent") or not r["stats"].get("gp", 1):
                continue
            k = (r["opponent"], r["pos"], w)
            week_pts[k] = week_pts.get(k, 0.0) + scoring.score(scoring.actual_to_canon(r["stats"], r["pos"]), lg.scoring)
    per: dict = {}
    for (team, pos, _), v in week_pts.items():
        per.setdefault((team, pos), []).append(v)
    avg = {k: sum(v) / len(v) for k, v in per.items()}
    ranks = {}
    for pos in {k[1] for k in avg}:
        for i, k in enumerate(sorted((k for k in avg if k[1] == pos), key=lambda k: (-avg[k], k[0]))):
            ranks[k] = i + 1
    return ranks


def long_term_rate(p: dict) -> tuple[float, str | None]:
    """Expected points in a playoff week the player's team plays. No tuned weights, just a rule:
    - DEF and K: season average. Their weekly projection is mostly this week's opponent.
    - Everyone else: this week's projection when healthy now, since it reflects the current role
      (a season average still carries the weeks before a promotion). Hurt or on bye now: season average.
    Season averages need 3 games. IR, taxi and IR status count 0, nobody knows if they return in time."""
    if p.get("slot") in ("IR", "TAXI") or p["status"] == "IR":
        return 0.0, None
    enough = bool(p["ppg"]) and (p["games"] or 0) >= scoring.MIN_GAMES_FOR_SD
    if p["pos"] in ("DEF", "K"):
        return (p["ppg"], "season") if enough else (0.0, None)
    if p["points"] and "BYE" not in p["flags"] and p["status"] not in OUT_STATUSES:
        return p["points"], "projection"
    if enough:
        return p["ppg"], "season"
    return 0.0, None


DEFAULT_PLAYOFF_WEEKS = [15, 16, 17]


def season_phase(week: int, playoff_weeks: list[int]) -> str:
    """regular before the fantasy playoffs, playoffs during them, over after the last playoff week."""
    if week < playoff_weeks[0]:
        return "regular"
    return "playoffs" if week <= playoff_weeks[-1] else "over"


def _league_games(lc, norm, rosters, week, last_week):
    """(records, division, n_divisions, history, schedule, playoff teams) from Sleeper, or from the
    ESPN sync file when it carries standings and schedule. None when the platform gives neither."""
    if lc["platform"] == "sleeper":
        if not norm.get("matchups"):
            return None
        name = {t["rosterId"]: t["teamName"] for t in norm["teams"]}
        records = {t["teamName"]: t["record"] for t in norm["teams"]}
        division = {t["teamName"]: t["record"].get("division") for t in norm["teams"]}
        history: dict = {}
        schedule = []
        for w_s, rows in norm["matchups"].items():
            w = int(w_s)
            if w < week:
                for r in rows:
                    if r["points"] > 0:
                        history.setdefault(name[r["rosterId"]], []).append(r["points"])
            elif w <= last_week:
                pairs: dict = {}
                for r in rows:
                    if r["matchupId"] is not None:
                        pairs.setdefault(r["matchupId"], []).append(name[r["rosterId"]])
                schedule += [(w, p[0], p[1]) for p in pairs.values() if len(p) == 2]
        return records, division, norm.get("divisions") or 0, history, schedule, norm.get("playoffTeams") or 6
    if not rosters.get("standings") or not rosters.get("schedule"):
        return None
    name = {t["teamId"]: t["name"] for t in rosters["teams"]}
    records = {name[r["teamId"]]: {"wins": r["wins"], "losses": r["losses"], "ties": r["ties"], "pointsFor": r["pointsFor"],
                                   "pointsAgainst": r.get("pointsAgainst")} for r in rosters["standings"] if r["teamId"] in name}
    schedule = [(g["week"], name[g["homeTeamId"]], name[g["awayTeamId"]]) for g in rosters["schedule"]
                if week <= g["week"] <= last_week and g["homeTeamId"] in name and g["awayTeamId"] in name]
    return records, {}, 0, {}, schedule, rosters["settings"].get("playoffTeams") or 6


def standings_block(lc, norm, rosters, week, pw, slots, rosters_t, team_name, plays, this_week):
    """Standings with simulated playoff and bye odds for one league, or None when there is no data."""
    games = _league_games(lc, norm, rosters, week, pw[0] - 1)
    if games is None:
        return None
    records, division, n_div, history, schedule, n_playoff = games
    players = {r["name"]: r["players"] for r in rosters_t}
    teams = [n for n in records if n in players]
    schedule = [g for g in schedule if g[1] in players and g[2] in players]
    means = {}
    for w in sorted({g[0] for g in schedule}):
        for n in teams:   # this week from projections, later weeks from the long term rates
            means[(w, n)] = this_week(players[n]) if w == week else trades.playoff_total(slots, [w], players[n], plays)[0]
    sd = odds.weekly_sd(history)
    byes = odds.playoff_byes(n_playoff)
    sim = odds.simulate(teams, records, schedule, means, sd, n_playoff, division, n_div, byes, focus=team_name)
    mine_sim = sim.get(team_name, {})
    swing = {k: mine_sim.pop(k) for k in ("ifWin", "ifLose") if k in mine_sim}   # kept out of the team rows
    now = odds.seed_order(teams, {n: records[n]["wins"] + 0.5 * records[n]["ties"] for n in teams},
                          {n: records[n]["pointsFor"] for n in teams}, division, n_div)
    rows = [{"name": n, "isMine": n == team_name, "seed": i + 1, "division": division.get(n),
             **{k: records[n].get(k) for k in ("wins", "losses", "ties", "pointsFor", "pointsAgainst")}, **sim[n]}
            for i, n in enumerate(now)]
    mine = [{"week": w, "opp": b if a == team_name else a,
             "myMean": round(means[(w, team_name)], 1), "oppMean": round(means[(w, b if a == team_name else a)], 1),
             "winPct": round(100 * odds.head_to_head(means[(w, team_name)], means[(w, b if a == team_name else a)], sd), 1),
             **(swing if w == week else {})}
            for w, a, b in sorted(schedule) if team_name in (a, b)]
    return {"teams": rows, "myGames": mine, "weeksLeft": sorted({g[0] for g in schedule}), "sd": sd, "sims": odds.SIMS,
            "playoffTeams": n_playoff, "byes": byes, "divisions": n_div}


def _r(x, n=1):
    return None if x is None else round(x, n)


def iso_from_ms(ms) -> str | None:
    """Sleeper epoch milliseconds to ISO UTC with a Z. None when missing."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ------------------------------------------------------------------ main build

def build(season: int, week: int, raw_root=RAW, out_dir=BUILD, rosters_path=None, save_idmap: bool = True,
          now: datetime | None = None, recommended_root=None) -> dict:
    """recommended_root: where recommended-{league}.json is written. Defaults to raw_root. Tests point it at tmp_path."""
    rec_root = recommended_root or raw_root
    cfg = load_config()
    raw = load_raw(season, week, raw_root)
    if not raw["players"]:
        raise BuildError("no Sleeper player data cached, cannot identify anyone")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    generated = now_iso()
    # every entry carries state (fresh, stale or missing), also when status.json predates it
    sources = {k: {**v, "state": source_state(v)} for k, v in raw["status"]["sources"].items()}
    sleeper_players = raw["players"]
    games = game_context(raw["lines"])
    matchups = week_matchups(raw["schedule"])

    # The committed roster file, or the last good copy ingest cached when the file is unusable.
    # The build decides which one is used, so it also writes the espn_rosters status the site shows.
    # With no usable file at all (rosters is None) the ESPN league is skipped and the Sleeper leagues still publish.
    rosters, roster_error = load_rosters(raw_root, season, week, rosters_path)
    sources["espn_rosters"] = rosters_status(rosters, roster_error, week, now)

    # ---- identity: ESPN id <-> Sleeper id
    espn_rows = {p["espnId"]: p for p in raw["espn"]}
    entries = [{"espnId": p["espnId"], "name": p["name"], "pos": p["pos"], "team": p["team"]} for p in raw["espn"]]
    for t in (rosters or {}).get("teams", []):
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
    skipped = []
    for lc in cfg["leagues"]:
        if lc["platform"] == "espn":
            if rosters is None:
                skipped.append({"key": lc["key"], "name": lc.get("name") or lc["key"], "reason": "no usable ESPN roster file"})
                continue
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
        weekly_by_week = scoring.weekly_points_by_week(lg, pos, actuals.get(pid, {})) if pos and pid else []
        weekly = [pts for _, pts in weekly_by_week]
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
            "newsUpdated": iso_from_ms(sp.get("newsUpdated")) if sp else None,
            "recent": [{"week": w, "pts": round(pts, 1)} for w, pts in weekly_by_week[-4:]],   # last 4 played weeks, oldest first
            "_filled": proj["filled"],
        }

    outputs = {}
    n_filled = 0
    for entry in leagues:
        lc, lg = entry[0], entry[1]
        slots = lg.starters
        rostered: dict = {}   # player id -> (team name, slot)
        rostered_names: set = set()   # (normalized name, pos). Guards the free agent list against unmatched ESPN ids
        team_recs: dict = {}          # team name -> player records, every team, for the v3 trade analyzer
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
                    team_recs.setdefault(t["name"], []).append(rec)
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
                for pid in t["players"]:
                    rec = player_record(pid, espn_of.get(pid), lg)
                    rec["slot"] = "IR" if pid in t["reserve"] else "TAXI" if pid in t["taxi"] else \
                        "START" if pid in t["starters"] else "BN"
                    team_recs.setdefault(t["teamName"], []).append(rec)
                    if t is mine:
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
                                      "eligible", "game", "injuryNotes", "locked", "ppg", "games", "newsUpdated", "recent")}

        # ---- lineup context: next best per slot, backups for flagged starters, late risk
        cur_ids = [c for c in cur if c]
        view = [{"id": p["id"], "name": p["name"], "pos": p["pos"], "points": p["points"], "eligible": p["eligible"],
                 "locked": p["locked"], "kickoff": (p["game"] or {}).get("kickoff")} for p in my_players]
        alerts, watch = [], []
        for i, (s, pid) in enumerate(zip(slots, cur)):
            if not pid:
                continue
            p = by_id[pid]
            cands = lineup.backup_candidates(slots, i, view, cur_ids)
            if any(f in ("BYE", *OUT_STATUSES) for f in p["flags"]):
                alerts.append({"player": p["name"], "slot": s, "flags": p["flags"],
                               "backup": lineup.backup_for(cands, p["points"], flagged=False)})
            if p["status"] in ("QUESTIONABLE", "DOUBTFUL"):
                kick = (p["game"] or {}).get("kickoff")
                watch.append({"player": p["name"], "slot": s, "flags": p["flags"], "kickoff": kick,
                              "injuryNotes": p["injuryNotes"], "backup": lineup.backup_for(cands, p["points"]),
                              "lateRisk": lineup.late_risk(kick, cands)})

        cur_total = round(sum(pts.get(c, 0.0) for c in cur if c), 1)
        rec_total = round(sum(pts.get(r, 0.0) for r in rec_slots if r), 1)
        if rec_total < cur_total:
            raise BuildError(f"{lc['key']}: recommended {rec_total} below current {cur_total}, optimizer bug")
        for p in my_players:
            n_filled += len(p["_filled"])
            p.pop("_filled")
        src_used = ["sleeper_projections", "espn_defaults", "nflverse_lines"] + (["espn_rosters"] if lc["platform"] == "espn" else ["sleeper_leagues", "sleeper_players"])
        if lc["platform"] == "espn":
            app_name, app_url = "ESPN", f"https://fantasy.espn.com/football/team?leagueId={lc['id']}&teamId={cfg['espnTeamId']}"
        else:
            app_name, app_url = "Sleeper", f"https://sleeper.com/leagues/{lc['id']}/team"
        out = {
            "generatedAt": generated, "season": season, "week": week,
            "league": {"key": lc["key"], "name": lg.name, "platform": lg.platform, "teamName": team_name,
                       "appName": app_name, "appUrl": app_url},
            "sources": {k: sources[k] for k in src_used if k in sources},
            "lineup": {
                "slots": [{"slot": slots[i], "current": brief(cur[i]), "recommended": brief(rec_slots[i]),
                           "changed": cur[i] != rec_slots[i],
                           "nextBest": lineup.next_best(slots, i, view, rec_slots)} for i in range(len(slots))],
                "currentPoints": cur_total, "recommendedPoints": rec_total, "gain": round(rec_total - cur_total, 1),
                "moves": [{"in": brief(m["in"]), "out": brief(m["out"]), "slot": m["slot"], "gain": m["gain"]} for m in mv],
                "alerts": alerts,
                "watch": watch,
            },
            "roster": sorted(my_players, key=lambda p: (-(p["points"] or 0), p["name"])),
            "scoringNotes": lg.notes,
        }
        # ---- P3 recap: store this run's recommended lineup, then last week's recap (pipeline/recap.py)
        recap.write_recommended(rec_root, season, week, lc["key"], slots, rec_slots, generated)
        sleeper_norm = entry[2] if len(entry) > 2 else None
        out["recap"] = recap.league_recap(
            season=season, week=week, lg=lg, roster=my_players, stats=raw["stats"],
            matchups=(sleeper_norm or {}).get("matchups"),
            my_roster_id=next((t["rosterId"] for t in sleeper_norm["teams"] if t["isMine"]), None) if sleeper_norm else None,
            raw_root=rec_root)
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
                                      "eligible", "game", "injuryNotes", "locked", "ppg", "games", "newsUpdated", "recent")}

        mine_in = [{"id": p["id"], "pos": p["pos"], "points": p["points"], "eligible": p["eligible"]} for p in my_players]
        fa_in = [{"id": p["id"], "pos": p["pos"], "points": p["points"], "eligible": p["eligible"], "locked": p["locked"]} for p in fas]
        rec_set = {r for r in rec_slots if r}
        positions = list(dict.fromkeys(s for s in slots if s not in scoring.FLEX_ELIGIBLE))
        dynasty = bool(lc.get("dynasty"))
        drop = None if dynasty else waivers.drop_candidate(
            [p for p in my_players if p["id"] not in rec_set and p["slot"] not in ("IR", "TAXI")])
        faab = waivers.faab_summary(entry[2], team_name) if lc["platform"] == "sleeper" else None
        out["waivers"] = {
            "freeAgents": len(fas), "dynasty": dynasty, "faab": faab,
            "targets": [{"player": fa_brief(t["id"]), "gain": t["gain"], "slot": t["slot"],
                         "replaces": brief(t["replaces"])}
                        for t in waivers.diversify(waivers.targets(slots, mine_in, fa_in, fixed), {p["id"]: p["pos"] for p in fas})],
            "byPosition": {pos: [fa_brief(i) for i in ids] for pos, ids in waivers.best_by_position(positions, fa_in).items()},
            "drop": brief(drop),
            "longTerm": None,
        }

        # ---- long term: who raises your best lineup across the fantasy playoff weeks still ahead
        # playoff weeks: the platform first (Sleeper API, or the ESPN sync file when it carries them), then config
        norm = entry[2] if len(entry) > 2 else {"playoffWeekStart": rosters["settings"].get("playoffWeekStart"),
                                                 "playoffTeams": rosters["settings"].get("playoffTeams"), "playoffRoundType": 0}
        pw = waivers.playoff_weeks(norm.get("playoffWeekStart"), norm.get("playoffTeams"), norm.get("playoffRoundType")) \
            or lc.get("playoffWeeks") or DEFAULT_PLAYOFF_WEEKS
        lt_weeks = [w for w in pw if w > week]
        out["seasonPhase"] = season_phase(week, pw)
        stretch_weeks = [w for w in range(week + 1, pw[0])]   # regular season weeks left after this one
        out["waivers"]["stretch"] = None
        ros_gain = None   # free agent -> points added over stretch + playoff weeks, when there is a schedule
        if matchups:
            rates = {p["id"]: long_term_rate(p) for p in my_players + fas}
            mine_lt = [{"id": p["id"], "pos": p["pos"], "team": p["team"], "rate": rates[p["id"]][0]} for p in my_players]
            fa_lt = [{"id": p["id"], "pos": p["pos"], "team": p["team"], "rate": rates[p["id"]][0]} for p in fas]
            ranks = defense_ranks(raw["stats"], lg) if (lt_weeks or stretch_weeks) else {}
            n_teams = len(ranks and {k[0] for k in ranks}) or 32

            def wk(p, x):
                opp, home = matchups.get(x["week"], {}).get(p["team"], (None, None))
                return {**x, "opp": opp, "home": home, "rank": ranks.get((opp, p["pos"]))}

            def horizon(weeks):
                """Free agents ranked by points added to your best lineup over these weeks."""
                ranked = waivers.diversify(waivers.long_term(slots, weeks, mine_lt, fa_lt, lambda w, t: t in matchups.get(w, {})),
                                           {p["id"]: p["pos"] for p in fas})
                return [{"player": fa_brief(t["id"]), "gain": t["gain"], "rate": round(rates[t["id"]][0], 1),
                         "rateFrom": rates[t["id"]][1], "weeks": [wk(fa_by[t["id"]], x) for x in t["weeks"]]} for t in ranked]

            out["waivers"]["longTerm"] = {"weeks": lt_weeks, "playoffWeeks": pw, "teams": n_teams, "targets": horizon(lt_weeks)}
            out["waivers"]["stretch"] = {"weeks": stretch_weeks, "teams": n_teams, "targets": horizon(stretch_weeks)}
            ros_gain = {t["id"]: t["gain"] for t in waivers.long_term(
                slots, stretch_weeks + lt_weeks, mine_lt, fa_lt, lambda w, t: t in matchups.get(w, {}))}
        # rosGain and FAAB bid on every waiver target (this week, stretch and playoff lists)
        for lst in [out["waivers"]["targets"]] + [h["targets"] for h in (out["waivers"]["stretch"], out["waivers"]["longTerm"]) if h]:
            for t in lst:
                t["rosGain"] = None if ros_gain is None else round(ros_gain.get(t["player"]["id"], 0.0), 1)
                t["bid"] = waivers.bid(faab["left"] if faab else None, t["rosGain"])
        # ---- v3 trades: every roster with playoff rates, plus 1 for 1 ideas that help both teams
        out["trade"] = None
        out["standings"] = None
        if matchups:
            def trade_player(p):
                sp = sleeper_players.get(p["id"]) or {}
                rate, src = long_term_rate(p)
                return {"id": p["id"], "name": p["name"], "pos": p["pos"], "team": p["team"], "points": p["points"],
                        "eligible": p["eligible"], "flags": p["flags"], "slot": p.get("slot"), "ppg": p["ppg"],
                        "games": p["games"], "rate": round(rate, 1), "rateFrom": src, "age": sp.get("age"),
                        "yearsExp": sp.get("yearsExp")}

            plays = lambda w, t: t in matchups.get(w, {})
            rosters_t = [{"name": n, "isMine": n == team_name,
                          "players": sorted((trade_player(p) for p in recs), key=lambda p: (-(p["rate"] or 0), p["name"]))}
                         for n, recs in team_recs.items()]
            mine_t = next(r for r in rosters_t if r["isMine"])["players"]
            others = [r for r in rosters_t if not r["isMine"]]
            all_weeks = stretch_weeks + lt_weeks    # rest of season, every week counts the same
            ideas = trades.suggest(slots, all_weeks, mine_t, others, plays)
            by_team = {r["name"]: {p["id"]: p for p in r["players"]} for r in rosters_t}
            mine_by = by_team[team_name]

            def this_week(players):
                return waivers.best_lineup(slots, [{"id": p["id"], "pos": p["pos"], "points": p["points"],
                                                    "eligible": p["eligible"]} for p in players])[0]
            base_now = this_week(mine_t)
            for i in ideas:
                theirs = by_team[i["team"]]
                after = [p for p in mine_t if p["id"] not in i["give"]] + [theirs[x] for x in i["get"]]
                i["thisWeek"] = round(this_week(after) - base_now, 1)
                ev = trades.evaluate(slots, all_weeks, mine_t, list(theirs.values()), i["give"], i["get"], plays)
                i["stretchGain"] = round(sum(x["gain"] for x in ev["weeks"] if x["week"] in stretch_weeks), 1)
                i["playoffGain"] = round(sum(x["gain"] for x in ev["weeks"] if x["week"] in lt_weeks), 1)
                i["youthFlag"] = dynasty and trades.youth_flag([mine_by[x] for x in i["give"]], [theirs[x] for x in i["get"]])
            write_json(out_dir / f"trade-{lc['key']}.json", {
                "generatedAt": generated, "season": season, "week": week, "league": lc["key"], "dynasty": dynasty,
                "slots": slots, "weeks": all_weeks, "stretchWeeks": stretch_weeks, "playoffWeeks": lt_weeks, "flexEligible": {k: sorted(v) for k, v in scoring.FLEX_ELIGIBLE.items()},
                "plays": {str(w): sorted(matchups.get(w, {})) for w in all_weeks}, "rosters": rosters_t, "ideas": ideas,
                "sources": out["sources"]})
            out["trade"] = {"file": f"trade-{lc['key']}.json", "ideas": len(ideas)}

            # ---- v4 standings and playoff odds
            out["standings"] = standings_block(lc, norm, rosters, week, pw, slots, rosters_t, team_name, plays, this_week)
        outputs[lc["key"]] = out
        write_json(out_dir / f"{lc['key']}.json", out)

    # Never publish a board with no league in it
    if not outputs:
        raise BuildError("no league could be built, refusing to publish")

    # ---- meta
    if rosters is not None:
        sync_age = espn_rosters.age_days(rosters, now)
        espn_meta = {"syncedAt": rosters["syncedAt"], "ageDays": round(sync_age, 2), "stale": espn_rosters.is_stale(rosters, now),
                     "staleAfterDays": espn_rosters.STALE_AFTER_DAYS, "fromCache": roster_error is not None,
                     "state": sources["espn_rosters"]["state"], "week": rosters["week"], "weekMismatch": rosters["week"] != week}
    else:
        espn_meta = {"syncedAt": None, "ageDays": None, "stale": True, "staleAfterDays": espn_rosters.STALE_AFTER_DAYS,
                     "fromCache": False, "state": "missing", "week": None, "weekMismatch": False}
    meta = {
        "generatedAt": generated, "season": season, "week": week,
        "nextRefresh": next_refresh(generated),
        "sources": sources,
        # stale here is the age rule only. The site checks it again against its own clock.
        # fromCache: the committed file was unusable and the last good sync is in use.
        # skippedLeagues: ESPN leagues left off because there was no usable roster file at all.
        "espnRosters": espn_meta,
        "skippedLeagues": skipped,
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
