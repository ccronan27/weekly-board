"""v2 waiver targets. Pure functions, no I/O.

A free agent is worth adding this week by exactly how much he raises your best possible
lineup. That one number covers weak slots, byes and injuries at once: a slot held by a bye or
OUT player scores 0, so any healthy free agent who fits it shows a gain. Same optimizer as the
lineup board (pipeline.lineup), same locks: a free agent whose game has started cannot help.
"""
from __future__ import annotations

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
