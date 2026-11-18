"""Projection backtest, rebuilt from docs/BACKTEST.md. Run it before any model change ships.

    python scripts/backtest.py                 # Part 1 (this season) and Part 3 (last season -> this season)
    python scripts/backtest.py --part 1
    python scripts/backtest.py --part 3 --train 2025 --test 2026
    python scripts/backtest.py --refresh       # re-pull instead of using the cache

Part 1: ESPN vs Rotowire vs their equal average, weeks 1 to last completed, under the ESPN
league's scoring, using the production model code (pipeline.scoring.project_player).
Part 3: fit the Vegas multiplier and weighting variants on the train season (default PPR),
score them on the test season. Prints markdown tables in the layout of docs/BACKTEST.md.

Definitions (docs/BACKTEST.md): relevant = average projection 5+, startable = 8+. Start/sit
accuracy = for every pair of startable players at one position in one week, how often the
higher projection scored more. FLEX pick = the same over RB/WR/TE pairs at different positions.
Pairs whose projections or actuals tie are skipped. The relevant and startable sets come from
the equal average, so every model is judged on the same player-weeks.

Pulls are cached to data/raw/{season}/{week}/backtest_espn.json and backtest_rotowire.json.
Only skill positions with a projection of 3+ points are kept, to keep the cache small.
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import http, scoring  # noqa: E402
from pipeline.adapters import espn_defaults, espn_rosters, nflverse_lines, sleeper  # noqa: E402
from pipeline.common import ESPN_TEAMS, RAW, norm_team, normalize_name, read_json, write_json  # noqa: E402

SKILL = ["QB", "RB", "WR", "TE"]
FLEX = {"RB", "WR", "TE"}
RELEVANT, STARTABLE, KEEP = 5.0, 8.0, 3.0
GRID = [round(x * 0.05, 2) for x in range(21)]
BOOT = 2000


# ---------------------------------------------------------------- pulls, cached per week

def _cache(season: int, week: int, name: str) -> Path:
    return RAW / str(season) / str(week) / f"backtest_{name}.json"


def pull_espn(season: int, weeks: list[int], refresh: bool = False) -> dict:
    """week -> [{espnId, name, pos, team, proj: {stats, applied}, actual: {stats, applied} | None}]"""
    if not refresh and all(_cache(season, w, "espn").exists() for w in weeks):
        return {w: read_json(_cache(season, w, "espn")) for w in weeks}
    d = http.get_json(espn_defaults.BASE.format(season=season),
                      params={"view": "kona_player_info", "scoringPeriodId": max(weeks)},
                      headers={"X-Fantasy-Filter": espn_defaults._filter([0, 2, 4, 6])})
    # Past seasons can carry position ids the live contract does not know (e.g. 9). Skip them here
    if not isinstance(d.get("players"), list) or not d["players"]:
        raise SystemExit(f"ESPN leaguedefaults returned no players for {season}")
    out: dict = {w: [] for w in weeks}
    for p in d["players"]:
        pl = p["player"]
        pos = espn_defaults.POS.get(pl["defaultPositionId"])
        if pos not in SKILL:
            continue
        by = {}
        for s in pl["stats"]:
            if s["seasonId"] == season and s["statSplitTypeId"] == 1 and s.get("stats"):
                by[(s["scoringPeriodId"], s["statSourceId"])] = {"stats": s["stats"], "applied": s["appliedTotal"]}
        for w in weeks:
            proj = by.get((w, 1))
            if proj and proj["applied"] >= KEEP:
                out[w].append({"espnId": p["id"], "name": pl["fullName"], "pos": pos, "team": ESPN_TEAMS.get(pl["proTeamId"]),
                               "proj": proj, "actual": by.get((w, 0))})
    for w in weeks:
        write_json(_cache(season, w, "espn"), out[w])
    return out


def pull_rotowire(season: int, weeks: list[int], refresh: bool = False) -> dict:
    """week -> [{name, pos, team, stats}] from Sleeper's Rotowire projections."""
    out = {}
    for w in weeks:
        path = _cache(season, w, "rotowire")
        if path.exists() and not refresh:
            out[w] = read_json(path)
            continue
        rows = sleeper.fetch_projections(season, w, positions=SKILL)
        keep = [{"name": f"{r['player']['first_name']} {r['player']['last_name']}".strip(), "pos": r["player"]["position"],
                 "team": norm_team(r.get("team")), "stats": {k: v for k, v in r["stats"].items() if not k.startswith(("adp_", "pos_"))}}
                for r in rows if r.get("company") == "rotowire" and r["player"].get("position") in SKILL
                and r["stats"].get("pts_ppr", 0) >= KEEP]
        write_json(path, keep)
        out[w] = keep
    return out


def implied_totals(season: int) -> tuple[dict, float]:
    """(week, team) -> implied team total from nflverse closing lines, and the season mean."""
    rows = list(csv.DictReader(io.StringIO(nflverse_lines.fetch())))
    imp = {}
    for w in range(1, 19):
        for g in nflverse_lines.normalize(rows, season, w):
            imp[(w, g["home"])] = g["impliedHome"]
            imp[(w, g["away"])] = g["impliedAway"]
    vals = [v for v in imp.values() if v is not None]
    return imp, (statistics.fmean(vals) if vals else 22.0)


# ---------------------------------------------------------------- joining the sources

def join(espn_week: list, rw_week: list) -> list:
    """Match ESPN and Rotowire rows on normalized name + position. Ambiguous names are dropped."""
    rw: dict = {}
    for r in rw_week:
        rw.setdefault((normalize_name(r["name"]), r["pos"]), []).append(r)
    out = []
    for e in espn_week:
        cands = rw.get((normalize_name(e["name"]), e["pos"]), [])
        if len(cands) == 1 and e["actual"] is not None:
            out.append((e, cands[0]))
    return out


def rows_league(season: int, weeks: list[int], espn: dict, rw: dict, lg) -> list[dict]:
    """Part 1 rows under the league's scoring, through the production model code."""
    out = []
    for w in weeks:
        pairs = join(espn[w], rw[w])
        support = scoring.Support.build([(r["pos"], scoring.rotowire_to_canon(r["stats"], r["pos"])) for _, r in pairs],
                                        [(e["pos"], scoring.espn_to_canon(e["proj"]["stats"], e["pos"])) for e, _ in pairs])
        for e, r in pairs:
            pr = scoring.project_player(lg, e["pos"], r["stats"], e["proj"]["stats"], support)
            out.append({"season": season, "week": w, "pos": e["pos"], "team": r["team"] or e["team"], "espn": pr["espn"],
                        "rw": pr["rotowire"], "actual": scoring.score_espn_native(e["actual"]["stats"], lg.espn_points)})
    return out


def rows_ppr(season: int, weeks: list[int], espn: dict, rw: dict) -> list[dict]:
    """Part 3 rows in default PPR: ESPN appliedTotal and Rotowire pts_ppr, as in the original study."""
    return [{"season": season, "week": w, "pos": e["pos"], "team": r["team"] or e["team"], "espn": e["proj"]["applied"],
             "rw": r["stats"]["pts_ppr"], "actual": e["actual"]["applied"]} for w in weeks for e, r in join(espn[w], rw[w])]


# ---------------------------------------------------------------- metrics

def _pairs(rows: list[dict], flex: bool):
    groups: dict = {}
    for i, r in enumerate(rows):
        if r["avg"] >= STARTABLE and (not flex or r["pos"] in FLEX):
            groups.setdefault((r["week"],) if flex else (r["week"], r["pos"]), []).append(i)
    for g in groups.values():
        for a in range(len(g)):
            for b in range(a + 1, len(g)):
                i, j = g[a], g[b]
                if flex and rows[i]["pos"] == rows[j]["pos"]:
                    continue
                yield i, j


def pair_accuracy(rows: list[dict], pred: list[float], flex: bool = False, by_week: bool = False):
    """Share of startable pairs ordered correctly. by_week returns {week: (correct, total)}."""
    tally: dict = {}
    for i, j in _pairs(rows, flex):
        dp, da = pred[i] - pred[j], rows[i]["actual"] - rows[j]["actual"]
        if dp == 0 or da == 0:
            continue
        c, t = tally.get(rows[i]["week"], (0, 0))
        tally[rows[i]["week"]] = (c + ((dp > 0) == (da > 0)), t + 1)
    if by_week:
        return tally
    c = sum(v[0] for v in tally.values())
    t = sum(v[1] for v in tally.values())
    return c / t if t else float("nan")


def summary(rows: list[dict], pred: list[float]) -> dict:
    act = np.array([r["actual"] for r in rows])
    p = np.array(pred)
    return {"mae": float(np.mean(np.abs(p - act))), "r": float(np.corrcoef(p, act)[0, 1]),
            "startsit": pair_accuracy(rows, pred), "flex": pair_accuracy(rows, pred, flex=True), "bias": float(np.mean(p - act))}


def relevant(rows: list[dict]) -> list[dict]:
    for r in rows:
        r["avg"] = (r["espn"] + r["rw"]) / 2
    return [r for r in rows if r["avg"] >= RELEVANT]


# ---------------------------------------------------------------- models for Part 3

def vegas(rows, imp, mean_imp, b_of):
    out = []
    for r in rows:
        t = imp.get((r["week"], r["team"]))
        out.append(r["avg"] * ((t / mean_imp) ** b_of(r["pos"]) if t else 1.0))
    return out


def fit_b(rows, imp, mean_imp, positions=None):
    """Grid search the Vegas exponent for the best start/sit accuracy on these rows."""
    sub = rows if positions is None else [r for r in rows if r["pos"] in positions]
    return max(GRID, key=lambda b: (pair_accuracy(sub, vegas(sub, imp, mean_imp, lambda _: b)), -b))


def fit_m3(rows):
    """ESPN weight by start/sit accuracy, then a per position calibration slope (least squares through 0)."""
    w = max(GRID, key=lambda w: (pair_accuracy(rows, [w * r["espn"] + (1 - w) * r["rw"] for r in rows]), -abs(w - 0.5)))
    cal = {}
    for pos in SKILL:
        sub = [r for r in rows if r["pos"] == pos]
        p = np.array([w * r["espn"] + (1 - w) * r["rw"] for r in sub])
        a = np.array([r["actual"] for r in sub])
        cal[pos] = float((p @ a) / (p @ p)) if len(sub) else 1.0
    return w, cal


def m3(rows, w, cal):
    return [cal[r["pos"]] * (w * r["espn"] + (1 - w) * r["rw"]) for r in rows]


def bootstrap_diff(rows, pred_a, pred_b, n=BOOT, seed=7):
    """Week bootstrap of start/sit accuracy (a minus b), in percentage points: (low, high) 95%."""
    ta, tb = pair_accuracy(rows, pred_a, by_week=True), pair_accuracy(rows, pred_b, by_week=True)
    weeks = sorted(set(ta) & set(tb))
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        pick = rng.choice(weeks, len(weeks))
        ca = sum(ta[w][0] for w in pick) / sum(ta[w][1] for w in pick)
        cb = sum(tb[w][0] for w in pick) / sum(tb[w][1] for w in pick)
        diffs.append(100 * (ca - cb))
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


# ---------------------------------------------------------------- report

def pct(x):
    return f"{100 * x:.1f}%"


def part1(season: int, through: int, refresh: bool) -> None:
    weeks = list(range(1, through + 1))
    espn, rw = pull_espn(season, weeks, refresh), pull_rotowire(season, weeks, refresh)
    lg = scoring.league_from_espn("fantasizing", espn_rosters.load())
    rows = relevant(rows_league(season, weeks, espn, rw, lg))
    n_start = sum(1 for r in rows if r["avg"] >= STARTABLE)
    print(f"## Part 1: ESPN vs Rotowire, {season} Weeks 1-{through} (ESPN league scoring)")
    print(f"{len(rows):,} relevant player-weeks, {n_start:,} startable.\n")
    print("| Source | MAE | r | Start/sit | Bias |\n|---|---|---|---|---|")
    for name, pred in (("ESPN", [r["espn"] for r in rows]), ("Rotowire", [r["rw"] for r in rows]),
                       ("Average", [r["avg"] for r in rows])):
        s = summary(rows, pred)
        bias = "n/a" if name == "Average" else f"{s['bias']:+.2f}"
        print(f"| {name} | {s['mae']:.2f} | {s['r']:.3f} | {pct(s['startsit'])} | {bias} |")
    spread = [abs(r["espn"] - r["rw"]) for r in rows]
    q1, q3 = np.percentile(spread, 25), np.percentile(spread, 75)
    lo = [r["actual"] - r["avg"] for r, s in zip(rows, spread) if s <= q1]
    hi = [r["actual"] - r["avg"] for r, s in zip(rows, spread) if s >= q3]
    print(f"\nSource disagreement vs boom/bust (low vs high spread quartiles): outcome SD {statistics.stdev(lo):.2f} vs {statistics.stdev(hi):.2f}\n")


def part3(train: int, test: int, test_through: int, refresh: bool) -> None:
    tr_weeks, te_weeks = list(range(1, 18)), list(range(1, test_through + 1))
    tr = relevant(rows_ppr(train, tr_weeks, pull_espn(train, tr_weeks, refresh), pull_rotowire(train, tr_weeks, refresh)))
    te = relevant(rows_ppr(test, te_weeks, pull_espn(test, te_weeks, refresh), pull_rotowire(test, te_weeks, refresh)))
    imp_tr, mean_tr = implied_totals(train)
    imp_te, _ = implied_totals(test)
    b1 = fit_b(tr, imp_tr, mean_tr)
    b2 = {pos: fit_b(tr, imp_tr, mean_tr, {pos}) for pos in SKILL}
    w3, c3 = fit_m3(tr)
    models = {
        "M0 Equal average": (lambda rs, im: [r["avg"] for r in rs]),
        "M1 + Vegas, one b": (lambda rs, im: vegas(rs, im, mean_tr, lambda _: b1)),
        "M2 + Vegas, b by position": (lambda rs, im: vegas(rs, im, mean_tr, lambda p: b2[p])),
        "M3 + weights + calibration": (lambda rs, im: m3(rs, w3, c3)),
    }
    print(f"## Part 3: Fit on {train} (Weeks 1-17), scored on {test} (Weeks 1-{test_through})")
    print(f"- Train {len(tr):,} relevant player-weeks ({train}). Test {len(te):,} relevant, "
          f"{sum(1 for r in te if r['avg'] >= STARTABLE):,} startable ({test})")
    print(f"- Implied total scaled against the {train} league mean ({mean_tr:.2f}), so no {test} information leaks in\n")
    print(f"### Fitted on {train}\n| Parameter | Value |\n|---|---|")
    print(f"| Vegas exponent b, all players | {b1:.2f} |")
    print("| b by position | " + ", ".join(f"{p} {b2[p]:.2f}" for p in SKILL) + " |")
    print(f"| M3 ESPN weight | {w3:.2f} |")
    print("| M3 calibration | " + ", ".join(f"{p} {c3[p]:.2f}" for p in SKILL) + " |\n")
    print(f"### Results\n| Model | {train} start/sit (in sample) | {test} MAE | {test} r | {test} start/sit | {test} FLEX pick |")
    print("|---|---|---|---|---|---|")
    preds = {}
    for name, f in models.items():
        p_tr, p_te = f(tr, imp_tr), f(te, imp_te)
        preds[name] = p_te
        s = summary(te, p_te)
        print(f"| {name} | {pct(pair_accuracy(tr, p_tr))} | {s['mae']:.3f} | {s['r']:.3f} | {pct(s['startsit'])} | {pct(s['flex'])} |")
    m0 = preds["M0 Equal average"]
    act: dict = {}
    for i, r in enumerate(te):
        act.setdefault(r["week"], []).append(i)
    print()
    winners = []
    for name, p in preds.items():
        if name.startswith("M0"):
            continue
        lo, hi = bootstrap_diff(te, p, m0)
        wins = sum(1 for idx in act.values()
                   if statistics.fmean(abs(p[i] - te[i]["actual"]) for i in idx) < statistics.fmean(abs(m0[i] - te[i]["actual"]) for i in idx))
        print(f"- {name.split()[0]} minus M0, {test} start/sit, week-bootstrap 95% range: {lo:+.2f} to {hi:+.2f} points. "
              f"Beat M0 on MAE in {wins} of {len(act)} weeks")
        if lo > 0:
            winners.append(name)
    if winners:
        print(f"- Verdict: {', '.join(winners)} beat M0 with the whole bootstrap range above zero. Review before shipping\n")
    else:
        print("- Verdict: no model beats M0 with the whole bootstrap range above zero. The equal average stays\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", type=int, choices=(1, 3))
    ap.add_argument("--season", type=int, help="Part 1 season (default: this season)")
    ap.add_argument("--through", type=int, help="last completed week (default: current week minus 1)")
    ap.add_argument("--train", type=int)
    ap.add_argument("--test", type=int)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    from pipeline.ingest import resolve_week
    season, week = resolve_week(None, None)
    through = a.through or week - 1
    if a.part in (None, 1):
        part1(a.season or season, through, a.refresh)
    if a.part in (None, 3):
        part3(a.train or season - 1, a.test or season, through, a.refresh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
