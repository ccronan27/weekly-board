"""v2 waiver targets. Pure functions, no I/O.

A free agent is worth adding this week by exactly how much he raises your best possible
lineup. That one number covers weak slots, byes and injuries at once: a slot held by a bye or
OUT player scores 0, so any healthy free agent who fits it shows a gain. Same optimizer as the
lineup board (pipeline.lineup), same locks: a free agent whose game has started cannot help.
"""
from __future__ import annotations

import math

from pipeline import lineup


def _pts(p: dict) -> float:
    return (p.get("points") or 0.0) if p.get("eligible") else 0.0


def best_lineup(slots: list[str], players: list[dict], fixed: dict | None = None) -> tuple[float, list]:
    """(total points, player id per slot) of the best lineup. players: id, pos, points, eligible."""
    by_id = {p["id"]: p for p in players}
    ids = lineup.recommend(slots, players, fixed=fixed)
    return round(sum(_pts(by_id[i]) for i in ids if i is not None), 1), ids


def targets(slots: list[str], mine: list[dict], free_agents: list[dict], fixed: dict | None = None) -> list[dict]:
    """Free agents who raise your best lineup this week, best gain first.

    Each result: {"id", "gain", "slot", "replaces"}. replaces is the id of your player who
    drops out of the best lineup, or None when the free agent fills an otherwise empty slot.
    """
    base, base_ids = best_lineup(slots, mine, fixed)
    base_set = {i for i in base_ids if i}
    out = []
    for fa in free_agents:
        if not fa.get("eligible") or fa.get("locked") or not fa.get("points"):
            continue
        total, ids = best_lineup(slots, mine + [fa], fixed)
        gain = round(total - base, 1)
        if gain <= 0 or fa["id"] not in ids:
            continue
        gone = sorted(base_set - set(ids))
        out.append({"id": fa["id"], "gain": gain, "slot": slots[ids.index(fa["id"])], "replaces": gone[0] if gone else None})
    out.sort(key=lambda t: (-t["gain"], str(t["id"])))
    return out


def best_by_position(positions: list[str], free_agents: list[dict], per: int = 3) -> dict:
    """Top healthy free agents at each position this league starts, by this week's projection."""
    ok = [p for p in free_agents if p.get("eligible") and not p.get("locked") and p.get("points")]
    ok.sort(key=lambda p: (-p["points"], str(p["id"])))
    return {pos: [p["id"] for p in ok if p["pos"] == pos][:per] for pos in positions}


def drop_candidate(bench: list[dict]) -> str | None:
    """Your least useful bench player: lowest of this week's projection and season points per game.

    bench: your players outside the best lineup, already without IR and taxi players.
    A player on bye has no projection this week, so his season average decides.
    """
    if not bench:
        return None

    def value(p):
        return max(p.get("points") or 0.0, p.get("ppg") or 0.0)

    return min(bench, key=lambda p: (value(p), str(p["id"])))["id"]


def diversify(ranked: list[dict], pos_of: dict, per_pos: int = 2, limit: int = 8) -> list[dict]:
    """Keep the ranking but allow at most per_pos targets at one position, so one position
    (often DEF streamers) cannot crowd out every other add."""
    out, count = [], {}
    for t in ranked:
        pos = pos_of[t["id"]]
        if count.get(pos, 0) < per_pos:
            out.append(t)
            count[pos] = count.get(pos, 0) + 1
        if len(out) == limit:
            break
    return out


# ---------------------------------------------------------------- long term: the fantasy playoffs

def playoff_weeks(start: int | None, teams: int | None, round_type: int | None = 0) -> list[int]:
    """Fantasy playoff weeks from Sleeper settings. 6 teams is 3 rounds (top 2 get a bye).
    round_type 0 is one week a round, 1 adds a second week to the final, 2 is two weeks a round."""
    if not start or not teams or teams < 2:
        return []
    rounds = math.ceil(math.log2(teams))
    n = rounds * 2 if round_type == 2 else rounds + (1 if round_type == 1 else 0)
    return list(range(start, start + n))


def long_term(slots: list[str], weeks: list[int], mine: list[dict], free_agents: list[dict], plays) -> list[dict]:
    """Free agents who raise your best lineup across the playoff weeks, best total first.

    mine, free_agents: dicts with id, pos, team and rate (expected points in a week he plays).
    plays(week, team) says whether that team has a game that week. No locks: these weeks are ahead.
    Each result: {"id", "gain", "weeks": [{"week", "gain"}]}.
    """
    totals: dict = {}
    for w in weeks:
        def avail(p):
            return {"id": p["id"], "pos": p["pos"], "points": p["rate"], "eligible": bool(p["rate"]) and plays(w, p["team"])}
        m = [avail(p) for p in mine]
        base, _ = best_lineup(slots, m)
        for fa in free_agents:
            if not fa.get("rate"):
                continue
            f = avail(fa)
            gain = 0.0
            if f["eligible"]:
                total, _ = best_lineup(slots, m + [f])
                gain = max(0.0, round(total - base, 1))
            totals.setdefault(fa["id"], []).append({"week": w, "gain": gain})
    out = [{"id": pid, "gain": round(sum(x["gain"] for x in ws), 1), "weeks": ws} for pid, ws in totals.items()]
    out = [r for r in out if r["gain"] > 0]
    out.sort(key=lambda r: (-r["gain"], str(r["id"])))
    return out


# ---------------------------------------------------------------- FAAB

FAAB_TYPE = 2   # Sleeper waiver_type for free agent acquisition budget


def bid(left: int | None, ros_gain: float | None) -> int | None:
    """Suggested FAAB bid in whole dollars. Rough guide, not tested against real bids.

    round(left * min(0.4, rosGain / (rosGain + 40))), at least 1 when rosGain > 0 (never more than
    you have left). None without FAAB data. 0 when the player adds nothing over the remaining weeks.
    """
    if left is None or ros_gain is None:
        return None
    if ros_gain <= 0 or left <= 0:
        return 0
    share = min(0.4, ros_gain / (ros_gain + 40))
    return min(int(left), max(1, round(left * share)))


def faab_summary(norm: dict, team_name: str) -> dict | None:
    """FAAB budget and what every team has left, from a normalized Sleeper league.

    None when the league is not FAAB or any team lacks waiverBudget data (older raw caches).
    leagueMaxLeft is the most any OTHER team has left, None when there are no other teams.
    """
    budget = norm.get("waiverBudget")
    teams = norm.get("teams") or []
    if norm.get("waiverType") != FAAB_TYPE or budget is None or not teams:
        return None
    if any(t.get("faabUsed") is None for t in teams):
        return None
    left = {t["teamName"]: budget - t["faabUsed"] for t in teams}
    if team_name not in left:
        return None
    others = [v for k, v in left.items() if k != team_name]
    return {
        "budget": budget,
        "left": left[team_name],
        "leagueMaxLeft": max(others) if others else None,
        "teams": sorted(({"name": k, "left": v} for k, v in left.items()), key=lambda t: (-t["left"], t["name"])),
    }
