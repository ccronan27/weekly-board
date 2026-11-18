"""v4 standings and playoff odds. Pure functions, no I/O.

Each remaining regular season week, every team scores a normal draw around its own expected
score that week (its best lineup under the board's projections and rates) with one league
wide spread (the average week to week SD of team scores this season). Higher score wins.
The season is played out many times with a fixed seed, so the same inputs give the same odds.

Seeding: with divisions, each division winner is in and seeded first (best record, then points
for), then the rest by record and points for. Without divisions, record then points for.
"""
from __future__ import annotations

import math
import statistics

import numpy as np

DEFAULT_SD = 25.0
SIMS = 10000
SEED = 20261118


def win_pct(w: int, l: int, t: int) -> float:
    g = w + l + t
    return (w + 0.5 * t) / g if g else 0.0


def weekly_sd(history: dict) -> float:
    """history: team -> [weekly points]. Average of each team's own SD, teams with 3+ games."""
    sds = [statistics.stdev(v) for v in history.values() if len(v) >= 3]
    return round(statistics.fmean(sds), 2) if sds else DEFAULT_SD


def head_to_head(mean_a: float, mean_b: float, sd: float) -> float:
    """Chance team A outscores team B in one week."""
    z = (mean_a - mean_b) / (sd * math.sqrt(2))
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def seed_order(names: list[str], wins, points, division: dict | None, n_div: int) -> list[str]:
    """Teams in seed order. wins and points are dicts name -> number (wins may include half ties)."""
    key = lambda n: (-wins[n], -points[n], n)
    if not n_div or not division:
        return sorted(names, key=key)
    winners = []
    for d in sorted({division.get(n) for n in names} - {None}):
        members = [n for n in names if division.get(n) == d]
        winners.append(sorted(members, key=key)[0])
    rest = [n for n in names if n not in winners]
    return sorted(winners, key=key) + sorted(rest, key=key)


def simulate(teams: list[str], records: dict, schedule: list[tuple[int, str, str]], means: dict, sd: float,
             playoff_teams: int, division: dict | None = None, n_div: int = 0, byes: int = 2,
             sims: int = SIMS, seed: int = SEED) -> dict:
    """Play out the rest of the regular season many times.

    records: name -> {"wins", "losses", "ties", "pointsFor"}
    schedule: (week, team a, team b) for every remaining game
    means: (week, name) -> expected points
    Returns name -> {"playoffPct", "byePct", "projWins", "avgSeed"}.
    """
    rng = np.random.default_rng(seed)
    idx = {n: i for i, n in enumerate(teams)}
    k = len(teams)
    base_w = np.array([records[n]["wins"] + 0.5 * records[n]["ties"] for n in teams], dtype=float)
    base_pf = np.array([records[n]["pointsFor"] for n in teams], dtype=float)
    wins = np.tile(base_w, (sims, 1))
    pf = np.tile(base_pf, (sims, 1))
    for week, a, b in schedule:
        ia, ib = idx[a], idx[b]
        sa = rng.normal(means[(week, a)], sd, sims)
        sb = rng.normal(means[(week, b)], sd, sims)
        wins[:, ia] += sa > sb
        wins[:, ib] += sb > sa
        pf[:, ia] += sa
        pf[:, ib] += sb
    made = np.zeros(k)
    bye = np.zeros(k)
    seed_sum = np.zeros(k)
    # Ties in the sort key are broken by points for, then name, the same as seed_order
    for s in range(sims):
        order = seed_order(teams, dict(zip(teams, wins[s])), dict(zip(teams, pf[s])), division, n_div)
        for pos, n in enumerate(order):
            i = idx[n]
            seed_sum[i] += pos + 1
            if pos < playoff_teams:
                made[i] += 1
            if pos < byes:
                bye[i] += 1
    return {n: {"playoffPct": round(100 * made[idx[n]] / sims, 1), "byePct": round(100 * bye[idx[n]] / sims, 1),
                "projWins": round(float(wins[:, idx[n]].mean()), 1), "avgSeed": round(float(seed_sum[idx[n]] / sims), 1)}
            for n in teams}


def playoff_byes(playoff_teams: int) -> int:
    """First round byes: enough to make the second round a power of two (6 teams -> 2 byes)."""
    if playoff_teams < 2:
        return 0
    nxt = 2 ** math.floor(math.log2(playoff_teams))
    return 0 if nxt == playoff_teams else 2 * nxt - playoff_teams
