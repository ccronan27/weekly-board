"""Record trimmed, scrubbed fixtures of real source responses into tests/fixtures/.

Run this when a contract test fails because a source changed shape: re-record, look at the
diff, then update the adapter. Only public endpoints are called. ESPN league endpoints are
never used. Owner identities are scrubbed (team_name is kept, handles and ids are replaced).

    python scripts/record_fixtures.py
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.adapters import espn_defaults, nflverse_lines, sleeper  # noqa: E402
from pipeline.ingest import load_config  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
FAKE_ME = "u1"


def dump(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", name)


def top_by_pos(rows, per_pos=3, key=lambda r: r["stats"].get("pts_ppr", 0)):
    keep = []
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        group = sorted((r for r in rows if r["player"]["position"] == pos and "pts_ppr" in r["stats"]), key=key, reverse=True)
        keep += group[:per_pos]
    keep += [r for r in rows if "pts_ppr" not in r["stats"]][:4]   # ADP-only placeholders exist in real data
    return keep


def main() -> None:
    cfg = load_config()
    state = sleeper.fetch_state()
    season, week = int(state["season"]), state["week"]
    dump("sleeper_state.json", state)

    lid = str(next(l["id"] for l in cfg["leagues"] if l["key"] == "hwh"))
    league, rosters, users = sleeper.fetch_league(lid), sleeper.fetch_rosters(lid), sleeper.fetch_users(lid)
    dump("sleeper_league.json", league)
    # Scrub owners. Keep the real shape, replace identities and drop free-text metadata.
    ids = {}
    for r in rosters[:3]:  # users who own the kept rosters, so team names resolve
        ids[r["owner_id"]] = FAKE_ME if len(ids) == 0 else f"u{len(ids) + 1}"
    users = [{"user_id": ids[u["user_id"]], "display_name": f"user{ids[u['user_id']][1:]}", "avatar": None,
              "is_bot": False, "is_owner": False, "league_id": lid, "settings": None,
              "metadata": {"team_name": (u.get("metadata") or {}).get("team_name")}} for u in users if u["user_id"] in ids]
    rosters = [dict(r, owner_id=ids[r["owner_id"]], co_owners=None, metadata=None) for r in rosters if r["owner_id"] in ids]
    dump("sleeper_rosters.json", rosters)
    dump("sleeper_users.json", users)
    dyn = str(next(l["id"] for l in cfg["leagues"] if l.get("dynasty")))
    dump("sleeper_traded_picks.json", sleeper.fetch_traded_picks(dyn))   # roster ids only, no owners

    players = sleeper.fetch_players()
    keep, seen = {}, {}
    for pid, p in players.items():
        pos = p.get("position")
        if p.get("active") and seen.get(pos, 0) < 3 and pos in ("QB", "RB", "WR", "TE", "K", "DEF", "LB"):
            keep[pid] = {k: p.get(k) for k in ("first_name", "last_name", "position", "team", "status", "injury_status",
                                              "injury_notes", "active", "news_updated", "age", "years_exp", "fantasy_positions")}
            seen[pos] = seen.get(pos, 0) + 1
    dump("sleeper_players.json", keep)

    def slim(rows):
        out = top_by_pos(rows)
        for r in out:  # drop the heavy nested player metadata we never read
            r["player"] = {k: r["player"].get(k) for k in ("first_name", "last_name", "position", "team", "injury_status")}
        return out

    dump("sleeper_projections.json", slim(sleeper.fetch_projections(season, week)))
    dump("sleeper_stats.json", slim(sleeper.fetch_stats(season, week - 1)))

    d = espn_defaults.fetch(season, week)
    chosen, per = [], {}
    def proj_total(p):
        return max((s.get("appliedTotal", 0) for s in p["player"]["stats"] if s["scoringPeriodId"] == week and s["statSourceId"] == 1), default=0)
    for p in sorted(d["players"], key=proj_total, reverse=True):
        pos = p["player"]["defaultPositionId"]
        if per.get(pos, 0) < 3:
            chosen.append(p); per[pos] = per.get(pos, 0) + 1
    extras = [p for p in d["players"] if any("stats" not in s for s in p["player"]["stats"])][:1]
    extras += [p for p in d["players"] if "injuryStatus" not in p["player"] and p["player"]["defaultPositionId"] != 16][:1]
    for p in chosen + extras:
        pl = p["player"]
        pl["stats"] = [s for s in pl["stats"] if s["seasonId"] == season and s["scoringPeriodId"] in (0, week - 1, week)]
        for k in ("outlooks", "draftRanksByRankType", "rankings", "ownership", "seasonOutlook"):
            pl.pop(k, None)
        p.pop("ratings", None)
    dump("espn_defaults.json", {"players": chosen + [e for e in extras if e not in chosen]})

    text = nflverse_lines.fetch()
    rows = [r for r in csv.DictReader(io.StringIO(text)) if r["season"] == str(season) and r["week"] in (str(week), str(week - 1))]
    cols = nflverse_lines.REQUIRED_COLUMNS
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader(); w.writerows(rows)
    (OUT / "nflverse_games.csv").write_text(buf.getvalue(), encoding="utf-8")
    print("wrote nflverse_games.csv", f"(season {season}, week {week})")


if __name__ == "__main__":
    main()
