"""Shotgun rule, Fantasizing 2026 (the ESPN league) only: every starter, kicker or D/ST in your lineup who
scores 0 or less in a week means one shotgun. Bench and IR do not count. Shotguns not done by the end of
Monday night football double. The board does not track that, so these are the raw counts per week.

Input is the espn_lineups cache per completed week (pipeline.adapters.espn_league.normalize_week),
which carries ESPN's own league-scored points, so the counts match what the league app shows.
"""
from __future__ import annotations

THRESHOLD = 0.0   # a starter at or below this owes a shotgun


def week_counts(lineups: list[dict], names: dict, mine_id) -> list[dict]:
    """One week. Every team, most shotguns first, then by name.
    [{name, isMine, count, players: [{name, pos, slot, points, projected}]}]"""
    rows = []
    for t in lineups:
        if t["teamId"] not in names:
            continue
        hits = [{k: s.get(k) for k in ("name", "pos", "slot", "points", "projected")}
                for s in t["starters"] if s["points"] is not None and s["points"] <= THRESHOLD]
        hits.sort(key=lambda s: (s["points"], s["name"]))
        rows.append({"name": names[t["teamId"]], "isMine": t["teamId"] == mine_id, "count": len(hits), "players": hits})
    rows.sort(key=lambda r: (-r["count"], r["name"].lower()))
    return rows


def season_block(weekly: dict, names: dict, mine_id) -> dict | None:
    """weekly: week -> lineups. Weeks newest first, plus season totals per team.
    None when no completed week is cached."""
    if not weekly:
        return None
    weeks = [{"week": w, "teams": week_counts(weekly[w], names, mine_id)} for w in sorted(weekly, reverse=True)]
    totals = {n: {"name": n, "isMine": tid == mine_id, "total": 0, "weeksHit": 0} for tid, n in names.items()}
    for wk in weeks:
        for r in wk["teams"]:
            totals[r["name"]]["total"] += r["count"]
            totals[r["name"]]["weeksHit"] += 1 if r["count"] else 0
    table = sorted(totals.values(), key=lambda r: (-r["total"], r["name"].lower()))
    return {"threshold": THRESHOLD, "weeks": weeks, "totals": table,
            "seasonTotal": sum(r["total"] for r in table)}
