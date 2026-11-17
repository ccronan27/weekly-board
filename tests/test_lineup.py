import pytest

from pipeline import lineup as lu


def P(i, pos, pts, ok=True):
    return {"id": i, "pos": pos, "points": pts, "eligible": ok}


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]


def roster():
    return [P("q1", "QB", 20), P("q2", "QB", 15), P("r1", "RB", 15), P("r2", "RB", 12), P("r3", "RB", 9), P("r4", "RB", 4),
            P("w1", "WR", 16), P("w2", "WR", 14), P("w3", "WR", 13), P("w4", "WR", 8), P("t1", "TE", 10), P("t2", "TE", 7),
            P("k1", "K", 8), P("d1", "DEF", 6)]


def test_recommend_fills_flex_with_best_remaining():
    rec = lu.recommend(SLOTS, roster())
    assert set(rec) == {"q1", "r1", "r2", "w1", "w2", "t1", "w3", "r3", "k1", "d1"}
    assert sum(p["points"] for p in roster() if p["id"] in rec) == 20 + 15 + 12 + 16 + 14 + 10 + 13 + 9 + 8 + 6


def test_ineligible_players_are_never_recommended():
    rs = roster()
    rs[0]["eligible"] = False          # QB1 is out
    rs[6]["eligible"] = False          # WR1 is on a bye
    rec = lu.recommend(SLOTS, rs)
    assert "q1" not in rec and "w1" not in rec and "q2" in rec


def test_empty_slot_when_nobody_fits():
    rec = lu.recommend(["QB", "K"], [P("q1", "QB", 10)])
    assert rec == ["q1", None]


def test_restrictive_flex_is_filled_after_position_slots():
    slots = ["RB", "REC_FLEX", "SUPER_FLEX"]
    rs = [P("r1", "RB", 10), P("w1", "WR", 9), P("q1", "QB", 25), P("t1", "TE", 8)]
    rec = lu.recommend(slots, rs)
    assert rec == ["r1", "w1", "q1"], "QB must land in SUPER_FLEX, not be wasted"


def test_greedy_matches_brute_force():
    import itertools
    rs = roster()
    slots = ["QB", "RB", "WR", "TE", "FLEX", "K"]
    best = 0
    for combo in itertools.permutations(rs, len(slots)):
        if all(lu.eligible_for(s, p["pos"]) for s, p in zip(slots, combo)):
            best = max(best, sum(p["points"] for p in combo))
    rec = lu.recommend(slots, rs)
    assert sum(p["points"] for p in rs if p["id"] in rec) == best


def test_arrange_keeps_unchanged_starters_in_place():
    pos = {p["id"]: p["pos"] for p in roster()}
    chosen = lu.recommend(SLOTS, roster())
    current = ["q1", "r1", "r2", "w1", "w2", "t1", "w3", "r4", "k1", "d1"]    # only r4 -> r3 should change
    placed = lu.arrange(SLOTS, chosen, current, pos)
    assert [a for a, b in zip(placed, current) if a != b] == ["r3"]
    assert placed[7] == "r3"


def test_arrange_places_everyone_even_when_current_slots_conflict():
    pos = {"r1": "RB", "w1": "WR", "r2": "RB"}
    slots = ["RB", "FLEX", "WR"]
    # r2 currently in FLEX, w1 in WR, r1 on the bench. Recommended set is all three
    placed = lu.arrange(slots, ["r1", "r2", "w1"], [None, "r2", "w1"], pos)
    assert sorted(placed) == ["r1", "r2", "w1"] and placed[1] == "r2" and placed[2] == "w1"


def test_moves_pair_in_and_out_with_gain():
    pts = {"r3": 9.0, "r4": 4.0, "q1": 20.0}
    pos = {"r3": "RB", "r4": "RB", "q1": "QB"}
    cur = ["q1", "r4"]
    rec = ["q1", "r3"]
    mv = lu.moves(["QB", "RB"], cur, rec, pts, pos)
    assert mv == [{"in": "r3", "out": "r4", "slot": "RB", "gain": 5.0}]


def test_moves_for_starter_with_no_replacement():
    mv = lu.moves(["QB", "K"], ["q1", "k1"], ["q1", None], {"k1": 8.0, "q1": 20.0}, {"q1": "QB", "k1": "K"})
    assert mv == [{"in": None, "out": "k1", "slot": "K", "gain": -8.0}]


# ---- locks: fixed slots (starters that have kicked off) ----

def test_locked_starter_is_never_moved_out_even_with_better_bench():
    slots = ["RB", "RB"]
    rs = [P("r1", "RB", 5), P("r2", "RB", 4), P("r3", "RB", 9), P("r4", "RB", 8)]
    pos = {p["id"]: p["pos"] for p in rs}
    cur = ["r1", "r2"]
    assert "r1" not in lu.recommend(slots, rs), "without a lock the 5 point starter is benched"
    fixed = {0: "r1"}
    chosen = lu.recommend(slots, rs, fixed=fixed)
    placed = lu.arrange(slots, chosen, cur, pos, fixed=fixed)
    assert placed == ["r1", "r3"], "r1 stays in slot 0, r2 is replaced by the best free player"


def test_locked_starter_in_flex_keeps_its_slot():
    slots = ["RB", "WR", "FLEX"]
    rs = [P("r1", "RB", 12), P("w1", "WR", 6), P("w2", "WR", 14), P("r2", "RB", 11)]
    pos = {p["id"]: p["pos"] for p in rs}
    cur = ["r1", "w2", "w1"]
    fixed = {2: "w1"}
    chosen = lu.recommend(slots, rs, fixed=fixed)
    placed = lu.arrange(slots, chosen, cur, pos, fixed=fixed)
    assert placed[2] == "w1" and placed[0] == "r1" and placed[1] == "w2"


def test_ineligible_locked_starter_still_holds_slot():
    slots = ["QB", "K"]
    rs = [P("q1", "QB", 20, False), P("q2", "QB", 15), P("k1", "K", 8)]
    fixed = {0: "q1"}
    chosen = lu.recommend(slots, rs, fixed=fixed)
    assert chosen == ["q1", "k1"], "a kicked off player who is now OUT still occupies the slot"


def test_locked_bench_player_is_never_recommended():
    slots = ["RB", "RB"]
    # build marks locked bench players ineligible. r3 is the best, but its game has started
    rs = [P("r1", "RB", 5), P("r2", "RB", 4), P("r3", "RB", 9, False), P("r4", "RB", 8)]
    pos = {p["id"]: p["pos"] for p in rs}
    fixed = {0: "r1"}
    chosen = lu.recommend(slots, rs, fixed=fixed)
    assert "r3" not in chosen and chosen == ["r1", "r4"]
    placed = lu.arrange(slots, chosen, ["r1", "r2"], pos, fixed=fixed)
    assert "r3" not in placed


def test_no_locks_gives_the_same_answer():
    rs = roster()
    pos = {p["id"]: p["pos"] for p in rs}
    cur = ["q1", "r1", "r2", "w1", "w2", "t1", "w3", "r4", "k1", "d1"]
    assert lu.recommend(SLOTS, rs, fixed={}) == lu.recommend(SLOTS, rs)
    chosen = lu.recommend(SLOTS, rs)
    assert lu.arrange(SLOTS, chosen, cur, pos, fixed={}) == lu.arrange(SLOTS, chosen, cur, pos)
