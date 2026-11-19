"""v4 playoff odds: seeding rules and simulation sanity on small leagues."""
import pytest

from pipeline import odds


def rec(w, l, pf, t=0):
    return {"wins": w, "losses": l, "ties": t, "pointsFor": pf}


def test_seed_order_record_then_points():
    wins = {"A": 7, "B": 7, "C": 8}
    pts = {"A": 1000, "B": 1100, "C": 900}
    assert odds.seed_order(["A", "B", "C"], wins, pts, None, 0) == ["C", "B", "A"]


def test_division_winners_seed_first():
    wins = {"A": 9, "B": 8, "C": 6, "D": 7}
    pts = {k: 1000 for k in wins}
    div = {"A": 1, "B": 1, "C": 2, "D": 2}
    # B (8 wins) loses the division to A and drops below division winner D (7 wins)
    assert odds.seed_order(list(wins), wins, pts, div, 2) == ["A", "D", "B", "C"]


def test_playoff_byes():
    assert odds.playoff_byes(6) == 2 and odds.playoff_byes(4) == 0 and odds.playoff_byes(8) == 0
    assert odds.playoff_byes(12) == 4 and odds.playoff_byes(10) == 6 and odds.playoff_byes(1) == 0


def test_head_to_head_symmetry_and_direction():
    assert odds.head_to_head(100, 100, 25) == pytest.approx(0.5)
    assert odds.head_to_head(120, 100, 25) > 0.7
    assert odds.head_to_head(120, 100, 25) + odds.head_to_head(100, 120, 25) == pytest.approx(1.0)


def test_weekly_sd_needs_three_games():
    assert odds.weekly_sd({"A": [100, 120]}) == odds.DEFAULT_SD
    assert odds.weekly_sd({"A": [100, 120, 110], "B": [90, 90, 90]}) == pytest.approx(5.0)


def league():
    teams = ["A", "B", "C", "D"]
    records = {"A": rec(9, 1, 1200), "B": rec(5, 5, 1000), "C": rec(5, 5, 990), "D": rec(1, 9, 800)}
    schedule = [(11, "A", "D"), (11, "B", "C"), (12, "A", "B"), (12, "C", "D")]
    means = {(w, n): m for w in (11, 12) for n, m in (("A", 130), ("B", 110), ("C", 110), ("D", 90))}
    return teams, records, schedule, means


def test_simulation_is_deterministic_and_sane():
    teams, records, schedule, means = league()
    a = odds.simulate(teams, records, schedule, means, 25, 2, sims=2000)
    b = odds.simulate(teams, records, schedule, means, 25, 2, sims=2000)
    assert a == b                                              # fixed seed
    assert a["A"]["playoffPct"] == 100.0                       # 9 wins, nobody can catch up in 2 games
    assert a["D"]["playoffPct"] == 0.0                         # 1 win, can reach 3 at most
    assert 0 < a["B"]["playoffPct"] < 100 and 0 < a["C"]["playoffPct"] < 100
    assert sum(t["playoffPct"] for t in a.values()) == pytest.approx(200.0, abs=0.2)   # two spots
    assert a["A"]["projWins"] == pytest.approx(9 + 2 * 0.6, abs=0.6)


def test_focus_reports_if_win_and_if_lose_on_the_same_draws():
    teams, records, schedule, means = league()
    plain = odds.simulate(teams, records, schedule, means, 25, 2, sims=4000)
    r = odds.simulate(teams, records, schedule, means, 25, 2, sims=4000, focus="B")
    assert "ifWin" not in plain["B"]                          # no focus, output unchanged
    assert r["B"]["playoffPct"] == plain["B"]["playoffPct"]   # same draws, same odds
    assert r["B"]["ifWin"] >= r["B"]["ifLose"]
    assert r["B"]["ifLose"] <= r["B"]["playoffPct"] <= r["B"]["ifWin"]
    assert all("ifWin" not in v for k, v in r.items() if k != "B")


def test_bye_pct_counts_top_seeds_only():
    teams, records, schedule, means = league()
    r = odds.simulate(teams, records, schedule, means, 25, 3, byes=1, sims=1000)
    assert r["A"]["byePct"] == 100.0 and sum(t["byePct"] for t in r.values()) == pytest.approx(100.0, abs=0.2)
