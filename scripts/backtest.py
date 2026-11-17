"""Cross-season projection backtest. Rebuilds the numbers in docs/BACKTEST.md.

Part 1: ESPN vs Rotowire vs their equal average for one season to date, ESPN league scoring.
Part 3: fit candidate models on last season, score them on this season (default PPR scoring),
        with a week-bootstrap 95% range for each model's start/sit difference vs the equal average.

    python scripts/backtest.py                          # this season to date, last season 1-17
    python scripts/backtest.py --season 2026 --weeks 1-10 --train-season 2025 --train-weeks 1-17
    python scripts/backtest.py --part 1                 # Part 1 only (re-run weekly)
    python scripts/backtest.py --offline                # cache only, no network

Raw pulls are cached under data/raw/{season}/{week}/ like the pipeline:
  espn_weekly.json          ESPN leaguedefaults, that week's projection and actual stat lines
  sleeper_projections.json  Rotowire via Sleeper (same shape the pipeline writes)
  nflverse_lines.json       closing spread and total (same shape the pipeline writes)
A cached week is never fetched again unless --refresh is given. No credentials are used and
no ESPN league endpoint is ever called: leaguedefaults is ESPN's public default player pool.

Definitions (docs/BACKTEST.md):
  Relevant   = average projection (ESPN + Rotowire) / 2 of 5+ pts. MAE, r and bias use these
  Startable  = average projection of 8+ pts
  Start/sit  = for every pair of startable players at the same position in the same week, the
               share where the higher projection scored more. Pairs that tie on actual points are
               dropped. A tie in projection counts as half right
  FLEX pick  = the same over pairs of startable RB/WR/TE at different positions in the same week
  Bias       = mean of projection minus actual
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import http, scoring  # noqa: E402
from pipeline.adapters import espn_defaults, espn_rosters, nflverse_lines, sleeper  # noqa: E402
from pipeline.common import ESPN_TEAMS, RAW, now_iso, read_json, write_json  # noqa: E402
from pipeline.players import index_sleeper, match_one  # noqa: E402

POSITIONS = ("QB", "RB", "WR", "TE")
FLEX_POS = {"RB", "WR", "TE"}
RELEVANT, STARTABLE = 5.0, 8.0
GRID_B = [round(0.05 * i, 2) for i in range(0, 21)]          # Vegas exponent 0.00 to 1.00
GRID_W = [round(0.05 * i, 2) for i in range(0, 21)]          # ESPN weight 0.00 to 1.00
GRID_C = [round(0.70 + 0.01 * i, 2) for i in range(0, 61)]   # calibration 0.70 to 1.30
BOOT_REPS, BOOT_SEED = 5000, 2026


# ====================================================================== data and caching

def _cache(season: int, week: int, name: str, root: Path) -> Path:
    return root / str(season) / str(week) / f"{name}.json"


def _save(path: Path, name: str, data) -> None:
    write_json(path, {"source": name, "fetchedAt": now_iso(), "data": data})


def _espn_split(raw: dict, season: int, weeks: list[int]) -> dict[int, list]:
    """One leaguedefaults pull carries every week of the season. Split it into per-week records."""
    out: dict[int, list] = {w: [] for w in weeks}
    for p in raw["players"]:
        pl = p["player"]
        by_week: dict[int, dict] = {}
        for s in pl["stats"]:
            if s["seasonId"] != season or s["statSplitTypeId"] != espn_defaults.WEEKLY or not s.get("stats"):
                continue
            wk = s["scoringPeriodId"]
            if wk not in out:
                continue
            kind = {espn_defaults.PROJECTION: "projection", espn_defaults.ACTUAL: "actual"}.get(s["statSourceId"])
            if kind:
                by_week.setdefault(wk, {})[kind] = {"stats": s["stats"], "appliedTotal": s["appliedTotal"]}
        for wk, rec in by_week.items():
            out[wk].append({
                "espnId": p["id"], "name": pl["fullName"], "pos": espn_defaults.POS[pl["defaultPositionId"]],
                "team": ESPN_TEAMS.get(pl["proTeamId"]),
                "projection": rec.get("projection"), "actual": rec.get("actual"),
            })
    return out


def _fetch_espn_skill(season: int, week: int) -> dict:
    """leaguedefaults for QB/RB/WR/TE only. Same URL, filter and contract as the pipeline adapter,
    minus the K and D/ST call, which the backtest does not use.

    The skill pool can hold a non-fantasy player, e.g. 2025 has a DT who lined up at FB
    (defaultPositionId 9). Those are dropped, with a note, before the adapter's contract runs.
    """
    d = http.get_json(espn_defaults.BASE.format(season=season),
                      params={"view": "kona_player_info", "scoringPeriodId": week},
                      headers={"X-Fantasy-Filter": espn_defaults._filter(espn_defaults.SLOT_GROUPS[0])})
    if isinstance(d, dict) and isinstance(d.get("players"), list):
        keep = []
        for p in d["players"]:
            pl = p.get("player") or {}
            if pl.get("defaultPositionId") in espn_defaults.POS:
                keep.append(p)
            else:
                print(f"[backtest] ESPN {season}: dropped {pl.get('fullName')!r}, "
                      f"defaultPositionId {pl.get('defaultPositionId')!r}", file=sys.stderr)
        d = {**d, "players": keep}
    espn_defaults.validate(d, week=week, season=season)
    return d


def load_espn(season: int, weeks: list[int], root: Path, refresh: bool, offline: bool) -> dict[int, list]:
    need = [w for w in weeks if refresh or not _cache(season, w, "espn_weekly", root).exists()]
    if need:
        if offline:
            raise SystemExit(f"offline: no cached ESPN data for {season} weeks {need}")
        print(f"[backtest] fetching ESPN leaguedefaults {season} (weeks {need})", file=sys.stderr)
        raw = _fetch_espn_skill(season, max(need))
        for w, recs in _espn_split(raw, season, need).items():
            _save(_cache(season, w, "espn_weekly", root), "espn_weekly", recs)
    return {w: read_json(_cache(season, w, "espn_weekly", root))["data"] for w in weeks}


def load_rotowire(season: int, weeks: list[int], root: Path, refresh: bool, offline: bool) -> dict[int, list]:
    out = {}
    for w in weeks:
        path = _cache(season, w, "sleeper_projections", root)
        if refresh or not path.exists():
            if offline:
                raise SystemExit(f"offline: no cached Sleeper projections for {season} week {w}")
            print(f"[backtest] fetching Sleeper projections {season} week {w}", file=sys.stderr)
            _save(path, "sleeper_projections", sleeper.normalize_rows(sleeper.fetch_projections(season, w), "projections"))
        out[w] = read_json(path)["data"]
    return out


def load_lines(season: int, weeks: list[int], root: Path, refresh: bool, offline: bool) -> dict[int, list]:
    need = [w for w in weeks if refresh or not _cache(season, w, "nflverse_lines", root).exists()]
    if need:
        if offline:
            raise SystemExit(f"offline: no cached nflverse lines for {season} weeks {need}")
        print(f"[backtest] fetching nflverse lines {season} (weeks {need})", file=sys.stderr)
        rows = nflverse_lines.parse(nflverse_lines.fetch())
        for w in need:
            _save(_cache(season, w, "nflverse_lines", root), "nflverse_lines", nflverse_lines.normalize(rows, season, w))
    return {w: read_json(_cache(season, w, "nflverse_lines", root))["data"] for w in weeks}


# ====================================================================== player-weeks

@dataclass
class PlayerWeek:
    week: int
    pos: str
    name: str
    team: str | None
    espn: float
    rotowire: float
    actual: float
    implied: float | None = None     # Vegas implied team total

    @property
    def avg(self) -> float:
        return (self.espn + self.rotowire) / 2


@dataclass
class Season:
    season: int
    weeks: list[int]
    scoring: str
    rows: list[PlayerWeek] = field(default_factory=list)
    unmatched: int = 0
    no_actual: int = 0


def _implied_by_team(games: list) -> dict[str, float]:
    out = {}
    for g in games:
        if g["impliedHome"] is not None:
            out[g["home"]] = g["impliedHome"]
            out[g["away"]] = g["impliedAway"]
    return out


def build_season(season: int, weeks: list[int], mode: str, root: Path, refresh: bool = False,
                 offline: bool = False) -> Season:
    """Match ESPN and Rotowire projections to ESPN actuals, one row per player-week.

    mode "league" (Part 1): ESPN projection and actual scored natively by stat id with the ESPN
    league's points (data/espn/rosters.json), as the pipeline does. mode "ppr" (Part 3): ESPN
    appliedTotal, which is ESPN's default PPR. Rotowire is Sleeper's pts_ppr in both modes.

    A player ESPN projected who has no actual stat line that week (inactive) scored 0. ESPN
    players with no Rotowire projection that week are left out and counted in unmatched.
    """
    espn = load_espn(season, weeks, root, refresh, offline)
    rw = load_rotowire(season, weeks, root, refresh, offline)
    lines = load_lines(season, weeks, root, refresh, offline)
    points = scoring.league_from_espn("fantasizing", espn_rosters.load()).espn_points if mode == "league" else None

    def pts(line: dict | None) -> float | None:
        if not line:
            return None
        return scoring.score_espn_native(line["stats"], points) if points is not None else line["appliedTotal"]

    out = Season(season, weeks, mode)
    for w in weeks:
        implied = _implied_by_team(lines[w])
        rw_by_id = {r["playerId"]: r for r in rw[w]}
        players = {pid: {"name": r["name"], "pos": r["pos"], "team": r["team"], "active": True}
                   for pid, r in rw_by_id.items()}
        idx = index_sleeper(players)
        for e in espn[w]:
            if e["pos"] not in POSITIONS or not e["projection"]:
                continue
            pid = match_one(e["name"], e["pos"], e["team"], players, idx)
            if pid is None:
                out.unmatched += 1
                continue
            r = rw_by_id[pid]
            act = pts(e["actual"])
            if act is None:
                out.no_actual += 1
                act = 0.0
            out.rows.append(PlayerWeek(w, e["pos"], e["name"], r["team"], pts(e["projection"]),
                                       r["stats"]["pts_ppr"], act, implied.get(r["team"])))
    return out


# ====================================================================== metrics

def mae(pred, actual) -> float:
    return float(np.mean(np.abs(np.asarray(pred, float) - np.asarray(actual, float))))


def pearson(pred, actual) -> float:
    return float(np.corrcoef(np.asarray(pred, float), np.asarray(actual, float))[0, 1])


def bias(pred, actual) -> float:
    return float(np.mean(np.asarray(pred, float) - np.asarray(actual, float)))


_CODES: dict = {}


def _code(key) -> int:
    """Stable integer for any hashable group or kind label (numpy cannot hold tuple labels)."""
    return _CODES.setdefault(key, len(_CODES))


def pair_counts(pred, actual, groups, kinds=None) -> tuple[float, int]:
    """(right, pairs) over every pair of items in the same group.

    The higher prediction is right when it scored more. Pairs that tie on actual points are
    dropped. A prediction tie counts as half right. With kinds, only pairs whose kinds differ
    count (FLEX: RB vs WR, RB vs TE, WR vs TE).
    """
    pred, actual = np.asarray(pred, float), np.asarray(actual, float)
    groups = np.array([_code(g) for g in groups], dtype=np.int64) if len(pred) else np.zeros(0, np.int64)
    kinds = None if kinds is None else np.array([_code(k) for k in kinds], dtype=np.int64)
    right, n = 0.0, 0
    for g in np.unique(groups):
        ix = np.flatnonzero(groups == g)
        if len(ix) < 2:
            continue
        i, j = np.triu_indices(len(ix), k=1)
        i, j = ix[i], ix[j]
        da = np.sign(actual[i] - actual[j])
        keep = da != 0
        if kinds is not None:
            keep &= kinds[i] != kinds[j]
        dp = np.sign(pred[i] - pred[j])[keep]
        da = da[keep]
        right += float(np.sum(dp * da > 0) + 0.5 * np.sum(dp == 0))
        n += int(keep.sum())
    return right, n


def pair_accuracy(pred, actual, groups, kinds=None) -> float:
    right, n = pair_counts(pred, actual, groups, kinds)
    return right / n if n else float("nan")


def _startable(rows):
    return [r for r in rows if r.avg >= STARTABLE]


def _relevant(rows):
    return [r for r in rows if r.avg >= RELEVANT]


def start_sit(rows, preds) -> float:
    """rows and preds aligned. Pairs come from startable rows (by the equal average)."""
    sel = [(r, p) for r, p in zip(rows, preds) if r.avg >= STARTABLE]
    return pair_accuracy([p for _, p in sel], [r.actual for r, _ in sel], [(r.week, r.pos) for r, _ in sel])


def flex_pick(rows, preds) -> float:
    sel = [(r, p) for r, p in zip(rows, preds) if r.avg >= STARTABLE and r.pos in FLEX_POS]
    return pair_accuracy([p for _, p in sel], [r.actual for r, _ in sel], [r.week for r, _ in sel],
                         [r.pos for r, _ in sel])


def weekly_pair_counts(rows, preds) -> dict[int, tuple[float, int]]:
    out = {}
    for w in sorted({r.week for r in rows}):
        sel = [(r, p) for r, p in zip(rows, preds) if r.week == w and r.avg >= STARTABLE]
        out[w] = pair_counts([p for _, p in sel], [r.actual for r, _ in sel], [r.pos for r, _ in sel])
    return out


def week_bootstrap(rows, pred_a, pred_b, reps=BOOT_REPS, seed=BOOT_SEED) -> tuple[float, float]:
    """95% range of start/sit(a) minus start/sit(b), in percentage points, resampling whole weeks."""
    ca, cb = weekly_pair_counts(rows, pred_a), weekly_pair_counts(rows, pred_b)
    weeks = sorted(ca)
    ra = np.array([ca[w][0] for w in weeks])
    rb = np.array([cb[w][0] for w in weeks])
    n = np.array([ca[w][1] for w in weeks], float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(weeks), size=(reps, len(weeks)))
    tot = n[pick].sum(axis=1)
    diff = 100 * (ra[pick].sum(axis=1) - rb[pick].sum(axis=1)) / tot
    lo, hi = np.percentile(diff, [2.5, 97.5])
    return float(lo), float(hi)


# ====================================================================== models (Part 3)

def m0(rows):
    return [r.avg for r in rows]


def vegas(rows, b_by_pos: dict, mean_implied: float):
    return [r.avg * (r.implied / mean_implied) ** b_by_pos[r.pos] for r in rows]


def weighted(rows, w: float, cal: dict):
    return [cal[r.pos] * (w * r.espn + (1 - w) * r.rotowire) for r in rows]


def _best(grid, score_fn):
    """Grid value with the highest score. Ties keep the first one seen, so callers order the
    grid from "no change" outward."""
    best, best_s = None, -math.inf
    for v in grid:
        s = score_fn(v)
        if s > best_s + 1e-12:
            best, best_s = v, s
    return best


def fit_models(train: list[PlayerWeek], mean_implied: float) -> dict:
    """Fit on the training season only. Exponents and weight maximise training start/sit
    accuracy. Calibration minimises training MAE per position (it cannot change start/sit)."""
    b_all = _best(GRID_B, lambda b: start_sit(train, vegas(train, {p: b for p in POSITIONS}, mean_implied)))
    b_pos = {}
    for pos in POSITIONS:
        sub = [r for r in train if r.pos == pos]
        b_pos[pos] = _best(GRID_B, lambda b: start_sit(sub, vegas(sub, {p: b for p in POSITIONS}, mean_implied)))
    w = _best(sorted(GRID_W, key=lambda v: abs(v - 0.5)), lambda w: start_sit(train, weighted(train, w, {p: 1.0 for p in POSITIONS})))
    cal = {}
    rel = _relevant(train)
    for pos in POSITIONS:
        sub = [r for r in rel if r.pos == pos]
        cal[pos] = _best(sorted(GRID_C, key=lambda c: abs(c - 1)),
                         lambda c: -mae([c * (w * r.espn + (1 - w) * r.rotowire) for r in sub], [r.actual for r in sub]))
    return {"b_all": b_all, "b_pos": b_pos, "w": w, "cal": cal}


# ====================================================================== report

def _bold_best(rows: list[list[str]], cols: dict[int, str]) -> list[list[str]]:
    """Bold the best cell per column as displayed. cols maps column index to "min" or "max".
    Ties at the shown precision are all bolded."""
    out = [list(r) for r in rows]
    for c, how in cols.items():
        vals = [float(r[c].rstrip("%")) for r in rows]
        target = min(vals) if how == "min" else max(vals)
        for r, v in zip(out, vals):
            if v == target:
                r[c] = f"**{r[c]}**"
    return out


def part1(s: Season) -> str:
    rel, st = _relevant(s.rows), _startable(s.rows)
    act = [r.actual for r in rel]
    lines = [f"## Part 1: ESPN vs Rotowire, {s.season} Weeks {s.weeks[0]}-{s.weeks[-1]} (ESPN league scoring)",
             f"{len(rel):,} relevant player-weeks, {len(st):,} startable.", "",
             "| Source | MAE | r | Start/sit | Bias |", "|---|---|---|---|---|"]
    cells = []
    for name, get in (("ESPN", lambda r: r.espn), ("Rotowire", lambda r: r.rotowire), ("Average", lambda r: r.avg)):
        p = [get(r) for r in rel]
        cells.append([name, f"{mae(p, act):.2f}", f"{pearson(p, act):.3f}", f"{100 * start_sit(rel, p):.1f}%",
                      "n/a" if name == "Average" else f"{bias(p, act):+.2f}"])
    lines += ["| " + " | ".join(c) + " |" for c in _bold_best(cells, {1: "min", 2: "max", 3: "max"})]

    # Does source disagreement predict boom/bust? Compare outcome spread in the lowest and
    # highest quartile of |ESPN - Rotowire|.
    spread = np.array([abs(r.espn - r.rotowire) for r in rel])
    resid = np.array([r.actual - r.avg for r in rel])
    q1, q3 = np.percentile(spread, [25, 75])
    lo, hi = resid[spread <= q1].std(ddof=1), resid[spread >= q3].std(ddof=1)
    verdict = "does NOT predict" if hi < 1.05 * lo else "may predict"
    lines += ["", f"Source disagreement {verdict} boom/bust (low vs high spread quartiles: outcome SD {lo:.2f} vs {hi:.2f})."]
    return "\n".join(lines)


def part3(train: Season, test: Season) -> str:
    tr = [r for r in train.rows if r.implied is not None]
    te = [r for r in test.rows if r.implied is not None]
    # Scale against the training season's mean implied team total, one value per team-game, so
    # no test season information leaks in.
    mean_implied = statistics.fmean({(r.week, r.team): r.implied for r in tr}.values())
    fit = fit_models(tr, mean_implied)
    models = {
        "M0 Equal average": lambda rows: m0(rows),
        "M1 + Vegas, one b": lambda rows: vegas(rows, {p: fit["b_all"] for p in POSITIONS}, mean_implied),
        "M2 + Vegas, b by position": lambda rows: vegas(rows, fit["b_pos"], mean_implied),
        "M3 + weights + calibration": lambda rows: weighted(rows, fit["w"], fit["cal"]),
    }
    tr_rel, te_rel, te_st = _relevant(tr), _relevant(te), _startable(te)
    te_act = [r.actual for r in te_rel]
    w0, w1 = train.weeks, test.weeks
    out = [f"## Part 3: Fit on {train.season} (Weeks {w0[0]}-{w0[-1]}), scored on {test.season} (Weeks {w1[0]}-{w1[-1]})",
           "- Sources: ESPN default PPR projections + Rotowire. Lines: nflverse closing spread/total",
           f"- Train {len(tr_rel):,} relevant player-weeks ({train.season}). Test {len(te_rel):,} relevant, "
           f"{len(te_st):,} startable ({test.season})",
           f"- Implied total scaled against the {train.season} league mean ({mean_implied:.2f}), so no "
           f"{test.season} information leaks in", "",
           f"### Fitted on {train.season}", "| Parameter | Value |", "|---|---|",
           f"| Vegas exponent b, all players | {fit['b_all']:.2f} |",
           "| b by position | " + ", ".join(f"{p} {fit['b_pos'][p]:.2f}" for p in POSITIONS) + " |",
           f"| M3 ESPN weight | {fit['w']:.2f} |",
           "| M3 calibration | " + ", ".join(f"{p} {fit['cal'][p]:.2f}" for p in POSITIONS) + " |", "",
           "### Results",
           f"| Model | {train.season} start/sit (in sample) | {test.season} MAE | {test.season} r | "
           f"{test.season} start/sit | {test.season} FLEX pick |",
           "|---|---|---|---|---|---|"]
    cells = []
    for name, f in models.items():
        p = f(te_rel)
        cells.append([f"**{name}**" if name.startswith("M0") else name, f"{100 * start_sit(tr_rel, f(tr_rel)):.2f}%",
                      f"{mae(p, te_act):.3f}", f"{pearson(p, te_act):.3f}", f"{100 * start_sit(te_rel, p):.2f}%",
                      f"{100 * flex_pick(te_rel, p):.2f}%"])
    out += ["| " + " | ".join(c) + " |" for c in _bold_best(cells, {2: "min", 3: "max", 4: "max", 5: "max"})]

    base = models["M0 Equal average"](te_rel)
    out.append("")
    for name in list(models)[1:]:
        lo, hi = week_bootstrap(te_rel, models[name](te_rel), base)
        out.append(f"- {name.split()[0]} minus M0, {test.season} start/sit, week-bootstrap 95% range: "
                   f"{lo:+.2f} to {hi:+.2f} points")
    m2 = models["M2 + Vegas, b by position"](te_rel)
    wins = sum(1 for w in w1 if mae([p for r, p in zip(te_rel, m2) if r.week == w], [r.actual for r in te_rel if r.week == w])
               < mae([r.avg for r in te_rel if r.week == w], [r.actual for r in te_rel if r.week == w]))
    out.append(f"- M2 beat M0 on MAE in {wins} of {len(w1)} weeks")
    return "\n".join(out)


# ====================================================================== cli

def _weeks(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a), int(b or a) + 1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, help="test season (default: current season)")
    ap.add_argument("--weeks", help="test weeks, e.g. 1-10 (default: completed weeks this season)")
    ap.add_argument("--train-season", type=int, help="fit season for Part 3 (default: season - 1)")
    ap.add_argument("--train-weeks", default="1-17", help="fit weeks for Part 3 (default 1-17)")
    ap.add_argument("--part", choices=["1", "3", "all"], default="all")
    ap.add_argument("--refresh", action="store_true", help="refetch even when a week is cached")
    ap.add_argument("--offline", action="store_true", help="use cached raw data only")
    ap.add_argument("--root", type=Path, default=RAW, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    season, weeks = a.season, _weeks(a.weeks) if a.weeks else None
    if season is None or weeks is None:
        if a.offline:   # no network: take the current week from the committed ESPN roster file
            r = espn_rosters.load()
            cur_season, cur_week = r["season"], r["week"]
        else:
            from pipeline.ingest import resolve_week
            cur_season, cur_week = resolve_week(season, None)
        season = season or cur_season
        weeks = weeks or list(range(1, cur_week))
    train_season = a.train_season or season - 1
    common = dict(root=a.root, refresh=a.refresh, offline=a.offline)

    print(f"# Projection Backtest (run {now_iso()[:10]})\n")
    if a.part in ("1", "all"):
        s = build_season(season, weeks, "league", **common)
        print(part1(s))
        print(f"\n<!-- {s.unmatched} ESPN player-weeks had no Rotowire match, {s.no_actual} had no ESPN actual -->\n")
    if a.part in ("3", "all"):
        train = build_season(train_season, _weeks(a.train_weeks), "ppr", **common)
        test = build_season(season, weeks, "ppr", **common)
        print(part3(train, test))
    return 0


if __name__ == "__main__":
    sys.exit(main())
