"""ESPN stat id to canonical stat key mapping.

Canonical keys are Sleeper's stat keys, because Sleeper leagues score by those keys and
Rotowire projections use them. Every id below was verified against 3,270 matched
player-weeks of ESPN vs Sleeper actual stats (exact match rate 1.000) unless marked.
Where ESPN has two ids for one stat (3 and 22, 24 and 40, 42 and 61, 53 and 41) the id
that ESPN's own league scoring references is used.

Not mapped, because the data could not verify them (and both are rare, under 0.02 pts a game):
  bonus_rush_yd_200 and bonus_rec_yd_200. Neither source projects them, so they score 0.
"""
from __future__ import annotations

# Offense (QB, RB, WR, TE)
OFF = {
    3: "pass_yd", 4: "pass_td", 19: "pass_2pt", 20: "pass_int", 18: "bonus_pass_yd_400", 16: "pass_td_50p",
    24: "rush_yd", 25: "rush_td", 26: "rush_2pt", 36: "rush_td_50p",
    42: "rec_yd", 43: "rec_td", 44: "rec_2pt", 46: "rec_td_50p", 53: "rec",
    72: "fum_lost",
}

# Kicker. ESPN gives made and missed FGs for 0-39 as one bucket (80, 82).
K = {
    83: "fgm", 84: "fga", 77: "fgm_40_49", 198: "fgm_50_59", 74: "fgm_50p",
    85: "fgmiss", 79: "fgmiss_40_49", 76: "fgmiss_50p",
    86: "xpm", 87: "xpa", 88: "xpmiss",
}
K_SPLIT_0_39 = {80: ("fgm_20_29", "fgm_30_39"), 82: ("fgmiss_20_29", "fgmiss_30_39")}  # split evenly

# Defense. Sleeper and ESPN points-allowed buckets differ only at 21 points: ESPN is 14-17,
# 18-21, 22-27 and Sleeper is 14-20, 21-27. ESPN id 121 (18-21) is split 3/4 and 1/4,
# uniform over the four scores.
DEF = {99: "sack", 95: "int", 96: "fum_rec", 97: "blk_kick", 98: "safe", 94: "def_td", 106: "ff"}
DEF_ST_TD = (101, 102)  # kick and punt return TDs, mapped to st_td (rare, unverified)
PA_ESPN = {89: "espn_pa_0", 90: "espn_pa_1_6", 91: "espn_pa_7_13", 92: "espn_pa_14_17", 121: "espn_pa_18_21",
           122: "espn_pa_22_27", 123: "espn_pa_28_34", 124: "espn_pa_35_45", 125: "espn_pa_46p"}
PA_SLEEPER_FROM_ESPN = {  # sleeper key: [(espn id, share)]
    "pts_allow_0": [(89, 1.0)], "pts_allow_1_6": [(90, 1.0)], "pts_allow_7_13": [(91, 1.0)],
    "pts_allow_14_20": [(92, 1.0), (121, 0.75)], "pts_allow_21_27": [(121, 0.25), (122, 1.0)],
    "pts_allow_28_34": [(123, 1.0)], "pts_allow_35p": [(124, 1.0), (125, 1.0)],
}
YDS = {128: "yds_allow_0_99", 129: "yds_allow_100_199", 130: "yds_allow_200_299", 131: "yds_allow_300_349",
       132: "yds_allow_350_399", 133: "yds_allow_400_449", 134: "yds_allow_450_499", 135: "yds_allow_500_549",
       136: "yds_allow_550p"}

# Inverse direction: ESPN league scoring ids that map to a canonical key.
# One ESPN id can drive several canonical keys.
SCORING_ID_TO_KEYS: dict[int, tuple[str, ...]] = {
    **{i: (k,) for i, k in OFF.items()},
    77: ("fgm_40_49",), 198: ("fgm_50_59",), 85: ("fgmiss",), 86: ("xpm",), 88: ("xpmiss",),
    80: ("fgm_0_19", "fgm_20_29", "fgm_30_39"),
    95: ("int",), 96: ("fum_rec",), 97: ("blk_kick",), 98: ("safe",), 99: ("sack",), 106: ("ff",),
    103: ("def_td",), 104: ("def_td",),   # fumble and INT return TDs. ESPN id 94 is their sum, scored once per TD
    101: ("st_td",), 102: ("st_td",),
    **{i: (k,) for i, k in PA_ESPN.items()},
    **{i: (k,) for i, k in YDS.items()},
}
# Ids whose canonical stat is already a sum of other ids, so never double count
IGNORED_SCORING_IDS = {93}  # blocked kick TD. No Rotowire equivalent


def espn_to_canon(stats: dict, pos: str) -> dict[str, float]:
    """Convert an ESPN raw stat map (keys are stat id strings) to canonical stat keys."""
    s = {int(k): v for k, v in stats.items()}
    out: dict[str, float] = {}
    if pos in ("QB", "RB", "WR", "TE"):
        for i, k in OFF.items():
            if i in s:
                out[k] = s[i]
        rec = out.get("rec", 0.0)
        out["bonus_rec_te"] = rec if pos == "TE" else 0.0   # Sleeper projects these equal to rec for the position
        out["bonus_rec_rb"] = rec if pos == "RB" else 0.0
        out["bonus_rec_wr"] = rec if pos == "WR" else 0.0
    elif pos == "K":
        for i, k in K.items():
            if i in s:
                out[k] = s[i]
        for i, keys in K_SPLIT_0_39.items():
            if i in s:
                for k in keys:
                    out[k] = s[i] / 2
    elif pos == "DEF":
        for i, k in DEF.items():
            if i in s:
                out[k] = s[i]
        if any(i in s for i in DEF_ST_TD):
            out["st_td"] = sum(s.get(i, 0.0) for i in DEF_ST_TD)
        for i, k in {**PA_ESPN, **YDS}.items():
            if i in s:
                out[k] = s[i]
        for k, parts in PA_SLEEPER_FROM_ESPN.items():
            if any(i in s for i, _ in parts):
                out[k] = sum(s.get(i, 0.0) * share for i, share in parts)
    return out
