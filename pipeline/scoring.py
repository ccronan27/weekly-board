"""Scoring engine: re-score raw projected stats with each league's exact scoring.

Model (docs/BACKTEST.md): projection = equal average of ESPN and Rotowire, each re-scored
under the league's scoring. No weights, no calibration, no Vegas multiplier.

Canonical stat keys are Sleeper's. ESPN stats are converted with pipeline.statmap. For the
ESPN league, ESPN's own projections are scored natively by ESPN stat id, which reproduces
ESPN's appliedTotal exactly (checked by scripts/check_scoring.py).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import yaml

from pipeline import statmap
from pipeline.common import CONFIG
from pipeline.statmap import espn_to_canon

# ---------------------------------------------------------------- league scoring


@dataclass
class League:
    key: str
    name: str
    platform: str                      # "sleeper" or "espn"
    scoring: dict                      # canonical stat key -> points
    starters: list                     # lineup slots, e.g. ["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF"]
    espn_points: dict | None = None    # ESPN league only: stat id -> points, used for native scoring
    espn_dst_points: dict | None = None  # same plus the D/ST slot overrides. Only D/ST uses these
    notes: list = field(default_factory=list)

    @property
    def slot_counts(self) -> dict:
        out: dict = {}
        for s in self.starters:
            out[s] = out.get(s, 0) + 1
        return out


FLEX_ELIGIBLE = {
    "FLEX": {"RB", "WR", "TE"}, "REC_FLEX": {"WR", "TE"}, "WRRB_FLEX": {"RB", "WR"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
NOT_STARTERS = {"BN", "IR", "TAXI"}


def load_overrides(key: str) -> dict:
    p = CONFIG / "leagues" / f"{key}.overrides.yaml"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def league_from_sleeper(key: str, norm: dict, overrides: dict | None = None) -> League:
    """norm is the output of sleeper.normalize_league. Scoring comes straight from the API."""
    ov = overrides if overrides is not None else load_overrides(key)
    scoring = {k: float(v) for k, v in norm["scoring"].items() if v}
    scoring.update({k: float(v) for k, v in (ov.get("scoring") or {}).items()})
    starters = ov.get("starters") or [p for p in norm["rosterPositions"] if p not in NOT_STARTERS]
    return League(key=key, name=norm["name"], platform="sleeper", scoring=scoring, starters=list(starters))


_ESPN_SLOT_NAMES = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "DEF", 17: "K", 23: "FLEX"}
_ESPN_SLOT_ORDER = [0, 2, 4, 6, 23, 17, 16]


def league_from_espn(key: str, rosters: dict, overrides: dict | None = None) -> League:
    """rosters is data/espn/rosters.json. Overrides can add stat ids the sync file drops."""
    ov = overrides if overrides is not None else load_overrides(key)
    base = {int(k): float(v) for k, v in rosters["settings"]["scoringByStatId"].items()}
    synced_dst = rosters["settings"].get("dstScoringByStatId")
    if synced_dst:   # the league's real D/ST values, saved by the sync skill. Beats the config defaults
        extra = {int(k): float(v) for k, v in synced_dst.items()}
        dst_source = "sync"
    else:
        extra = {int(k): float(v) for k, v in (ov.get("espnScoringByStatId") or {}).items()}
        dst_source = "config" if extra else None
    pts = {**base, **extra}   # used to build canonical scoring. Offense ids never appear in the extras
    counts = {int(k): v for k, v in rosters["settings"]["lineupSlotCounts"].items()}
    starters = ov.get("starters")
    if not starters:
        starters = [n for sid in _ESPN_SLOT_ORDER for n in [_ESPN_SLOT_NAMES[sid]] * counts.get(sid, 0)]

    scoring: dict = {}
    notes: list = []
    unmapped = []
    for sid, p in pts.items():
        if not p:
            continue
        keys = statmap.SCORING_ID_TO_KEYS.get(sid)
        if keys is None:
            if sid not in statmap.IGNORED_SCORING_IDS:
                unmapped.append(sid)
            continue
        for k in keys:
            if k in scoring and scoring[k] != p:
                notes.append(f"stat {k} has conflicting ESPN points ({scoring[k]} vs {p}), using {p}")
            scoring[k] = p          # several ids can feed one key with the same value. Never summed
    if unmapped:
        notes.append(f"ESPN scoring ids with points but no Rotowire equivalent, ignored for Rotowire: {sorted(unmapped)}")
    if dst_source == "config":
        notes.append("D/ST scored with ESPN's default values from config. The sync file does not carry this league's D/ST scoring yet")
    elif dst_source is None:
        notes.append("no D/ST scoring overrides configured, D/ST scored with the default zeros in the sync file")
    return League(key=key, name=rosters["settings"]["name"], platform="espn", scoring=scoring,
                  starters=list(starters), espn_points=base, espn_dst_points=pts, notes=notes)


# ---------------------------------------------------------------- canonical stat vectors

_PA_ESPN_EDGES = [(0, 0, "espn_pa_0"), (1, 6, "espn_pa_1_6"), (7, 13, "espn_pa_7_13"), (14, 17, "espn_pa_14_17"),
                  (18, 21, "espn_pa_18_21"), (22, 27, "espn_pa_22_27"), (28, 34, "espn_pa_28_34"),
                  (35, 45, "espn_pa_35_45"), (46, 10**6, "espn_pa_46p")]
_PA_SLEEPER_EDGES = [(0, 0, "pts_allow_0"), (1, 6, "pts_allow_1_6"), (7, 13, "pts_allow_7_13"), (14, 20, "pts_allow_14_20"),
                     (21, 27, "pts_allow_21_27"), (28, 34, "pts_allow_28_34"), (35, 10**6, "pts_allow_35p")]
_YDS_EDGES = [(0, 99, "yds_allow_0_99"), (100, 199, "yds_allow_100_199"), (200, 299, "yds_allow_200_299"),
              (300, 349, "yds_allow_300_349"), (350, 399, "yds_allow_350_399"), (400, 449, "yds_allow_400_449"),
              (450, 499, "yds_allow_450_499"), (500, 549, "yds_allow_500_549"), (550, 10**6, "yds_allow_550p")]


def _bucket(value: float, edges) -> dict:
    out = {k: 0.0 for _, _, k in edges}
    v = round(value)
    for lo, hi, k in edges:
        if lo <= v <= hi:
            out[k] = 1.0
    return out


def rotowire_to_canon(stats: dict, pos: str) -> dict[str, float]:
    """Sleeper/Rotowire stats are already canonical. Add derived keys Rotowire does not give."""
    s = dict(stats)
    if pos in ("RB", "WR", "TE"):
        rec = s.get("rec", 0.0)
        s.setdefault("bonus_rec_te", rec if pos == "TE" else 0.0)
        s.setdefault("bonus_rec_rb", rec if pos == "RB" else 0.0)
        s.setdefault("bonus_rec_wr", rec if pos == "WR" else 0.0)
    elif pos == "K":
        # Rotowire has 20-29, 30-39, 40-49, 50+ makes. Treat 50+ as 50-59 (60+ is under 2 percent of them)
        if "fgm_50p" in s:
            s.setdefault("fgm_50_59", s["fgm_50p"])
        if "fga" in s and "fgm" in s:
            miss = max(0.0, s["fga"] - s["fgm"])
            s.setdefault("fgmiss", miss)
            rest = miss - s.get("fgmiss_30_39", 0.0) - s.get("fgmiss_40_49", 0.0) - s.get("fgmiss_50p", 0.0)
            s.setdefault("fgmiss_20_29", max(0.0, rest))   # whatever Rotowire misses are not 30+ are shorter
    elif pos == "DEF":
        pa = s.get("pts_allow")
        if pa is not None:
            if not any(k.startswith("pts_allow_") for k in s):
                s.update(_bucket(pa, _PA_SLEEPER_EDGES))
            s.update(_bucket(pa, _PA_ESPN_EDGES))
        ya = s.get("yds_allow")
        if ya is not None:
            s.update(_bucket(ya, _YDS_EDGES))
    return s


def actual_to_canon(stats: dict, pos: str) -> dict[str, float]:
    """Sleeper actual stats use the same keys. Same derivations apply."""
    return rotowire_to_canon(stats, pos)


def score(canon: dict, scoring: dict) -> float:
    return sum(canon.get(k, 0.0) * p for k, p in scoring.items())


def score_espn_native(raw: dict, espn_points: dict) -> float:
    return sum(espn_points.get(int(k), 0.0) * v for k, v in raw.items())


# ---------------------------------------------------------------- blending

@dataclass
class Support:
    """Which stat keys each source projects at all, per position. Used to fill gaps fairly."""
    rotowire: dict = field(default_factory=dict)   # pos -> set(keys)
    espn: dict = field(default_factory=dict)

    @staticmethod
    def build(rotowire_canon: list, espn_canon: list) -> "Support":
        """Each list holds (pos, canon stats) pairs from the whole player pool."""
        sup = Support()
        for pos, s in rotowire_canon:
            sup.rotowire.setdefault(pos, set()).update(s.keys())
        for pos, s in espn_canon:
            sup.espn.setdefault(pos, set()).update(s.keys())
        return sup


def _fill(own: dict, other: dict, pos: str, scoring: dict, own_support: dict, other_support: dict) -> tuple[dict, list]:
    """If this source never projects a stat that the league scores and the other source does,
    use the other source's value. Keeps the equal average honest on stats only one source has."""
    out, filled = dict(own), []
    for k, p in scoring.items():
        if not p or k in own_support.get(pos, ()) or k not in other_support.get(pos, ()):
            continue
        if k in other:
            out[k] = other[k]
            filled.append(k)
    return out, filled


def project_player(league: League, pos: str, rotowire_stats: dict | None, espn_raw: dict | None,
                   support: Support) -> dict:
    """Return per-source and averaged league points for one player.

    rotowire_stats: Sleeper projection stat map, or None. espn_raw: ESPN raw stat map, or None.
    """
    rw = rotowire_to_canon(rotowire_stats, pos) if rotowire_stats else None
    es = espn_to_canon(espn_raw, pos) if espn_raw else None
    rw_pts = es_pts = None
    filled: list = []
    if rw is not None:
        rw_f, f = (_fill(rw, es, pos, league.scoring, support.rotowire, support.espn) if es is not None else (rw, []))
        filled += [f"rotowire:{k}" for k in f]
        rw_pts = score(rw_f, league.scoring)
    if es is not None:
        if league.platform == "espn" and league.espn_points is not None:
            native = league.espn_dst_points if pos == "DEF" else league.espn_points   # slot overrides are D/ST only
            es_pts = score_espn_native(espn_raw, native)   # exact, no mapping involved
        else:
            es_f, f = (_fill(es, rw, pos, league.scoring, support.espn, support.rotowire) if rw is not None else (es, []))
            filled += [f"espn:{k}" for k in f]
            es_pts = score(es_f, league.scoring)
    parts = [p for p in (es_pts, rw_pts) if p is not None]
    return {
        "espn": es_pts, "rotowire": rw_pts,
        "points": statistics.fmean(parts) if parts else None,   # equal average, or the one source we have
        "sources": [n for n, p in (("espn", es_pts), ("rotowire", rw_pts)) if p is not None],
        "filled": filled,
    }


# ---------------------------------------------------------------- volatility

MIN_GAMES_FOR_SD = 3


def weekly_points_by_week(league: League, pos: str, weekly_stats: dict) -> list[tuple[int, float]]:
    """(week, points) for each played week, oldest first. Stat map is week -> Sleeper stat map."""
    return [(int(w), score(actual_to_canon(s, pos), league.scoring))
            for w, s in sorted(weekly_stats.items(), key=lambda kv: int(kv[0]))
            if s.get("gp", 1) and s.get("gp", 1) > 0]


def weekly_points(league: League, pos: str, weekly_stats: dict) -> list[float]:
    """Re-score one player's actual stat lines (week -> Sleeper stat map) under the league."""
    return [pts for _, pts in weekly_points_by_week(league, pos, weekly_stats)]


def floor_ceiling(projection: float | None, weekly: list[float]) -> dict:
    """Floor and ceiling are one weekly SD below and above the projection (this season, own games)."""
    n = len(weekly)
    if projection is None or n < MIN_GAMES_FOR_SD:
        return {"sd": None, "floor": None, "ceiling": None, "games": n}
    sd = statistics.stdev(weekly)
    return {"sd": round(sd, 2), "floor": round(max(0.0, projection - sd), 1), "ceiling": round(projection + sd, 1), "games": n}
