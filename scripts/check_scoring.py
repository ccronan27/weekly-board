"""Verify the scoring engine against ground truth in the cached raw data.

  1. ESPN native scoring vs ESPN appliedTotal (must be exact)
  2. ESPN stats through the canonical mapping vs native (checks statmap and the inverse)
  3. Rotowire re-scored under standard PPR vs Rotowire's own pts_ppr

    python scripts/check_scoring.py [season] [week]
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import scoring  # noqa: E402
from pipeline.adapters import espn_rosters  # noqa: E402
from pipeline.common import RAW, read_json  # noqa: E402

season = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
week = int(sys.argv[2]) if len(sys.argv) > 2 else 11
D = RAW / str(season) / str(week)


def native(p):
    pts = league.espn_dst_points if p["pos"] == "DEF" else league.espn_points
    return scoring.score_espn_native(p["projection"]["stats"], pts)


def report(title, rows):
    print(f"\n{title}")
    by = collections.defaultdict(list)
    for pos, err in rows:
        by[pos].append(err)
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        e = by.get(pos)
        if e:
            print(f"  {pos:4} n={len(e):4}  max abs diff {max(e):8.4f}   mean {sum(e)/len(e):7.4f}")


rosters = espn_rosters.load()
league = scoring.league_from_espn("fantasizing", rosters)
print("ESPN league notes:", *league.notes, sep="\n  - ")
espn = [p for p in read_json(D / "espn_defaults.json")["data"] if p["projection"]]

report("1. ESPN native vs appliedTotal (ESPN league scoring)",
       [(p["pos"], abs(native(p) - p["projection"]["appliedTotal"])) for p in espn])

report("2. ESPN via canonical mapping vs native (ESPN league scoring)",
       [(p["pos"], abs(scoring.score(scoring.espn_to_canon(p["projection"]["stats"], p["pos"]), league.scoring)
                       - native(p))) for p in espn])

lg = read_json(D / "sleeper_leagues.json")["data"]["hwh"]
hwh = scoring.league_from_sleeper("hwh", lg)
rw = read_json(D / "sleeper_projections.json")["data"]
report("3. Rotowire re-scored with HWH (full PPR) vs Rotowire pts_ppr",
       [(r["pos"], abs(scoring.score(scoring.rotowire_to_canon(r["stats"], r["pos"]), hwh.scoring) - r["stats"]["pts_ppr"])) for r in rw])
