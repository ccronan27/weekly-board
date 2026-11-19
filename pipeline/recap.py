"""Week recap: last week's platform score against the best lineup and the lineup the board recommended.

For a build in week W the recap covers week W-1:
  actual       your team's platform score that week (Sleeper matchup points). None for ESPN
  optimal      best lineup from your roster's actual points that week, rescored with this league's scoring.
               The raw pulls do not keep past rosters, so your roster is approximated by the roster this
               build sees (current roster). IR and taxi players cannot start, as on the board.
  recommended  actual points (this league's scoring) of the players in the lineup the board recommended
               in its last run for week W-1, read from data/raw/{season}/{week}/recommended-{league}.json
  left         optimal minus actual
Every part is null when its input is missing. The whole recap is null when no part can be computed.
"""
from __future__ import annotations

from pathlib import Path

from pipeline import lineup, scoring
from pipeline.common import read_json, write_json


def recommended_path(raw_root, season: int, week: int, league_key: str) -> Path:
    return Path(raw_root) / str(season) / str(week) / f"recommended-{league_key}.json"


def write_recommended(raw_root, season: int, week: int, league_key: str, slots: list[str],
                      rec_slots: list, generated: str) -> None:
    """Store this run's recommended lineup. Overwrites an earlier run in the same week, so the last run wins."""
    write_json(recommended_path(raw_root, season, week, league_key), {
        "generatedAt": generated, "week": week,
        "slots": [{"slot": s, "playerId": p} for s, p in zip(slots, rec_slots)],
    })


def read_recommended(raw_root, season: int, week: int, league_key: str) -> list | None:
    """Player ids per slot from the stored recommendation, None when there is no usable file."""
    p = recommended_path(raw_root, season, week, league_key)
    if not p.exists():
        return None
    try:
        return [s["playerId"] for s in read_json(p)["slots"]]
    except (KeyError, TypeError, ValueError):
        return None


def week_points(lg: scoring.League, rows: list[dict]) -> dict:
    """player id -> points for one week's stat rows, scored with this league's scoring."""
    return {r["playerId"]: scoring.score(scoring.actual_to_canon(r["stats"], r["pos"]), lg.scoring) for r in rows}


def optimal_points(lg: scoring.League, roster: list[dict], pts: dict) -> float:
    """Best lineup the roster could field with these points. roster: dicts with id, pos and slot.
    Players who did not play score 0 but still fill a slot, which is the best case for the roster."""
    players = [{"id": p["id"], "pos": p["pos"], "points": pts.get(p["id"], 0.0),
                "eligible": p.get("slot") not in ("IR", "TAXI")} for p in roster]
    by_id = {p["id"]: p for p in players}
    ids = lineup.recommend(lg.starters, players)
    return round(sum(by_id[i]["points"] for i in ids if i is not None), 1)


def platform_points(matchups: dict | None, week: int, roster_id) -> float | None:
    """Your roster's score in a past week from Sleeper matchups. 0 means no game data yet, so None."""
    if matchups is None or roster_id is None:
        return None
    for r in matchups.get(str(week), []):
        if r["rosterId"] == roster_id and r["points"] > 0:
            return round(r["points"], 1)
    return None


def league_recap(*, season: int, week: int, lg: scoring.League, roster: list[dict], stats: dict,
                 matchups: dict | None, my_roster_id, raw_root) -> dict | None:
    """Recap for week - 1, or None. roster: your players in this build. stats: week -> stat rows from the
    raw pulls. matchups: Sleeper matchups by week (None for ESPN). my_roster_id: your Sleeper roster id."""
    w = week - 1
    if w < 1:
        return None
    rows = stats.get(w)
    pts = week_points(lg, rows) if rows is not None else None
    actual = platform_points(matchups, w, my_roster_id)
    optimal = optimal_points(lg, roster, pts) if pts is not None and roster else None
    rec_ids = read_recommended(raw_root, season, w, lg.key)
    recommended = round(sum(pts.get(pid, 0.0) for pid in rec_ids if pid), 1) \
        if pts is not None and rec_ids is not None else None
    # The board re-scores from Sleeper stats, which miss a few ESPN stat ids. A "best possible" below what the
    # platform actually scored is that gap, not a real number, so it is dropped rather than shown.
    if optimal is not None and actual is not None and optimal < actual:
        optimal = None
    if actual is None and optimal is None and recommended is None:
        return None
    left = round(optimal - actual, 1) if optimal is not None and actual is not None else None
    return {"week": w, "actual": actual, "optimal": optimal, "recommended": recommended, "left": left}
