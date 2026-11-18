"""Lineup optimizer and current-vs-recommended comparison. Pure functions, no I/O.

Slots are names like QB, RB, WR, TE, K, DEF, FLEX, REC_FLEX, SUPER_FLEX. Eligibility sets are
nested (position slot, then REC_FLEX or FLEX, then SUPER_FLEX), so filling the most
restrictive slots first with the best remaining player is optimal.
"""
from __future__ import annotations

from pipeline.scoring import FLEX_ELIGIBLE


def eligible_for(slot: str, pos: str | None) -> bool:
    if pos is None:
        return False
    return slot == pos or pos in FLEX_ELIGIBLE.get(slot, ())


def _width(slot: str) -> int:
    return len(FLEX_ELIGIBLE.get(slot, ())) or 1


def recommend(slots: list[str], players: list[dict], fixed: dict[int, str] | None = None) -> list[str | None]:
    """Best set of players for the slots. Returns player ids, one per slot index (None if no one fits).

    players: dicts with id, pos, points (float), eligible (bool). Ineligible players are never picked.
    fixed: slot index -> player id that must stay there (locked starters). Those players are kept
    whatever their eligibility, and the other slots are filled from the rest of the pool.
    """
    fixed = fixed or {}
    locked = set(fixed.values())
    pool = [p for p in players if p["eligible"] and p["id"] not in locked]
    pool.sort(key=lambda p: (-(p["points"] or 0.0), str(p["id"])))
    taken: set = set(locked)
    out: list = [fixed.get(i) for i in range(len(slots))]
    for i in sorted(range(len(slots)), key=lambda i: (_width(slots[i]), i)):
        if i in fixed:
            continue
        for p in pool:
            if p["id"] not in taken and eligible_for(slots[i], p["pos"]):
                out[i] = p["id"]
                taken.add(p["id"])
                break
    return out


def arrange(slots: list[str], chosen: list[str | None], current: list[str | None], pos_of: dict,
            fixed: dict[int, str] | None = None) -> list[str | None]:
    """Place the chosen players into slots so as many as possible stay in their current slot.

    Bitmask DP over slots. Primary goal is to place every chosen player, then to keep players
    where they already are. Same total points as `chosen`, fewer pointless moves.
    fixed: slot index -> player id that must stay in that slot (see recommend).
    """
    fixed = fixed or {}
    ids = [c for c in chosen if c is not None]
    n = len(ids)
    assert all(p in ids for p in fixed.values()), "fixed players must be in chosen"
    start = sum(1 << j for j, pid in enumerate(ids) if pid in fixed.values())
    memo: dict = {}

    def solve(i: int, mask: int):
        """Best (placed, kept, picks) for slots i.. given players in mask are used."""
        if i == len(slots):
            return (0, 0, ())
        key = (i, mask)
        if key in memo:
            return memo[key]
        if i in fixed:
            options = [(fixed[i], mask)]
        else:
            options = [(None, mask)]
            options += [(ids[j], mask | (1 << j)) for j in range(n)
                        if not mask & (1 << j) and eligible_for(slots[i], pos_of[ids[j]])]
        best = None
        for pid, nmask in options:
            placed, kept, picks = solve(i + 1, nmask)
            cand = (placed + (pid is not None), kept + (pid is not None and pid == current[i]), (pid,) + picks)
            if best is None or cand[:2] > best[:2]:
                best = cand
        memo[key] = best
        return best

    placed, _, picks = solve(0, start)
    assert placed == n, "chosen players do not all fit the slots"
    return list(picks)


def moves(slots: list[str], current: list, recommended: list, pts: dict, pos_of: dict) -> list[dict]:
    """Bench-in and starter-out pairs, matched to the slot the incoming player takes."""
    cur_set = {c for c in current if c}
    rec_set = {r for r in recommended if r}
    ins = sorted(rec_set - cur_set, key=lambda p: -pts.get(p, 0.0))
    outs = [c for c in current if c and c not in rec_set]
    result = []
    for pid in ins:
        slot_i = recommended.index(pid)
        # the starter leaving: prefer the one who held this slot, then same position, then anyone
        cands = [o for o in outs if current.index(o) == slot_i] or [o for o in outs if pos_of[o] == pos_of[pid]] or outs
        out = cands[0] if cands else None
        if out is not None:
            outs.remove(out)
        result.append({"in": pid, "out": out, "slot": slots[slot_i],
                       "gain": round(pts.get(pid, 0.0) - (pts.get(out, 0.0) if out else 0.0), 1)})
    for out in outs:   # starters leaving with nobody to replace them
        result.append({"in": None, "out": out, "slot": slots[current.index(out)], "gain": round(-pts.get(out, 0.0), 1)})
    return result
