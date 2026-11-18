"""v2 waiver targets: pure engine tests on small synthetic rosters."""
from pipeline import waivers as wv

SLOTS = ["QB", "RB", "WR", "TE", "FLEX", "K", "DEF"]


def P(pid, pos, pts, eligible=True, locked=False, ppg=None):
    return {"id": pid, "pos": pos, "points": pts, "eligible": eligible, "locked": locked, "ppg": ppg}


def team():
    return [P("qb", "QB", 18), P("rb", "RB", 12), P("wr", "WR", 11), P("te", "TE", 7), P("flex", "WR", 9),
            P("k", "K", 8), P("def", "DEF", 5), P("bn", "RB", 6)]


def test_free_agent_worse_than_starters_is_not_a_target():
    assert wv.targets(SLOTS, team(), [P("fa", "TE", 6)]) == []


def test_gain_is_exact_and_names_who_leaves():
    [t] = wv.targets(SLOTS, team(), [P("fa", "DEF", 9)])
    assert t == {"id": "fa", "gain": 4.0, "slot": "DEF", "replaces": "def"}


def test_bye_or_out_starter_makes_the_slot_a_need():
    mine = team()
    mine[3] = P("te", "TE", 7, eligible=False)      # TE on bye, no other TE on the roster
    [t] = wv.targets(SLOTS, mine, [P("fa", "TE", 4)])
    assert t["gain"] == 4.0 and t["slot"] == "TE" and t["replaces"] is None


def test_flex_upgrade_counts_through_reshuffle():
    [t] = wv.targets(SLOTS, team(), [P("fa", "RB", 13)])
    # the new RB takes RB, the old RB moves to FLEX, the 9 point WR leaves the lineup
    assert t["gain"] == 4.0 and t["replaces"] == "flex"


def test_locked_ineligible_and_unprojected_free_agents_are_skipped():
    fas = [P("a", "DEF", 20, locked=True), P("b", "DEF", 20, eligible=False), P("c", "DEF", None)]
    assert wv.targets(SLOTS, team(), fas) == []


def test_locked_starter_stays_fixed():
    mine = team()
    fixed = {6: "def"}                                # DEF already kicked off
    assert wv.targets(SLOTS, mine, [P("fa", "DEF", 9)], fixed) == []


def test_sorted_by_gain_and_diversified():
    fas = [P(f"d{i}", "DEF", 10 - i * 0.1) for i in range(5)] + [P("w", "WR", 10)]
    ranked = wv.targets(SLOTS, team(), fas)
    assert [t["gain"] for t in ranked] == sorted((t["gain"] for t in ranked), reverse=True)
    pos = {p["id"]: p["pos"] for p in fas}
    top = wv.diversify(ranked, pos, per_pos=2, limit=8)
    assert [pos[t["id"]] for t in top].count("DEF") == 2 and any(t["id"] == "w" for t in top)


def test_best_by_position_respects_order_and_limits():
    fas = [P("a", "WR", 5), P("b", "WR", 9), P("c", "WR", 7), P("d", "WR", 6), P("e", "TE", 3, eligible=False)]
    out = wv.best_by_position(["WR", "TE"], fas, per=3)
    assert out == {"WR": ["b", "c", "d"], "TE": []}


def test_drop_candidate_uses_season_average_for_bye_players():
    bench = [P("bye", "WR", None, eligible=False, ppg=12.0), P("low", "RB", 4.0, ppg=3.0), P("mid", "TE", 6.0, ppg=2.0)]
    assert wv.drop_candidate(bench) == "low"
    assert wv.drop_candidate([]) is None


# ---------------------------------------------------------------- long term

def R(pid, pos, team, rate):
    return {"id": pid, "pos": pos, "team": team, "rate": rate}


def test_playoff_weeks_from_sleeper_settings():
    assert wv.playoff_weeks(15, 6, 0) == [15, 16, 17]
    assert wv.playoff_weeks(15, 4, 0) == [15, 16]
    assert wv.playoff_weeks(14, 6, 1) == [14, 15, 16, 17]       # two week final
    assert wv.playoff_weeks(14, 4, 2) == [14, 15, 16, 17]       # two weeks a round
    assert wv.playoff_weeks(None, 6, 0) == [] and wv.playoff_weeks(15, None, 0) == []


def mine_lt():
    return [R("qb", "QB", "AAA", 18), R("rb", "RB", "AAA", 12), R("wr", "WR", "BBB", 11), R("te", "TE", "BBB", 7),
            R("flex", "WR", "CCC", 9), R("k", "K", "AAA", 8), R("def", "DEF", "CCC", 5)]


def test_long_term_sums_weekly_gains_and_skips_bye_weeks():
    plays = lambda w, t: not (w == 16 and t == "DDD")          # DDD is off in week 16
    [t] = wv.long_term(SLOTS, [15, 16, 17], mine_lt(), [R("fa", "DEF", "DDD", 9)], plays)
    assert t["weeks"] == [{"week": 15, "gain": 4.0}, {"week": 16, "gain": 0.0}, {"week": 17, "gain": 4.0}]
    assert t["gain"] == 8.0


def test_long_term_fills_my_own_playoff_bye():
    plays = lambda w, t: not (w == 15 and t == "BBB")          # my WR and TE are off in week 15
    [t] = wv.long_term(SLOTS, [15], mine_lt(), [R("fa", "TE", "EEE", 4)], plays)
    assert t["gain"] == 4.0


def test_long_term_ignores_zero_rate_and_no_gain_players():
    plays = lambda w, t: True
    fas = [R("hurt", "QB", "EEE", 0.0), R("meh", "TE", "EEE", 5)]
    assert wv.long_term(SLOTS, [15, 16], mine_lt(), fas, plays) == []
