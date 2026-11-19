"""v3 trade analyzer. Pure functions, no I/O.

A trade is judged the same way as a long term waiver add: how much it changes each team's
best lineup, summed over the fantasy playoff weeks still ahead. A player's weekly rate is
pipeline.build.long_term_rate (this week's projection for healthy skill players, season average
for DEF, K and anyone hurt or on bye). Teams off a week count 0 that week.

Suggestions are 1 for 1 trades where both teams get better. A trade the other side loses on
is not a real offer, so it is never suggested. The site's analyzer handles any other shape.
"""
from __future__ import annotations

import statistics

from pipeline import waivers

MIN_IDEA_GAIN = 2.0   # an idea must add at least this much to your playoff lineup, and must help them too
TRADE_POSITIONS = {"QB", "RB", "WR", "TE"}   # K and DEF are streamed, not traded
NEED_POSITIONS = ("QB", "RB", "WR", "TE")
NEED_MAX = 2
YOUTH_GAP = 4         # dynasty: flag a trade that sends away a player this many years younger


def playoff_total(slots: list[str], weeks: list[int], players: list[dict], plays) -> tuple[float, list[float]]:
    """(total, per week) of a roster's best lineup over the playoff weeks.

    players: dicts with id, pos, team, rate. plays(week, team) says whether that team plays.
    """
    per = []
    for w in weeks:
        ps = [{"id": p["id"], "pos": p["pos"], "points": p["rate"], "eligible": bool(p["rate"]) and plays(w, p["team"])}
              for p in players]
        per.append(waivers.best_lineup(slots, ps)[0])
    return round(sum(per), 1), per


def evaluate(slots, weeks, mine, theirs, give: list, get: list, plays) -> dict:
    """Both sides of one trade. give and get are player ids. Gains are over the playoff weeks."""
    give_s, get_s = set(give), set(get)
    moved_out = [p for p in mine if p["id"] in give_s]
    moved_in = [p for p in theirs if p["id"] in get_s]
    my_before, my_wk_before = playoff_total(slots, weeks, mine, plays)
    my_after, my_wk_after = playoff_total(slots, weeks, [p for p in mine if p["id"] not in give_s] + moved_in, plays)
    th_before, _ = playoff_total(slots, weeks, theirs, plays)
    th_after, _ = playoff_total(slots, weeks, [p for p in theirs if p["id"] not in get_s] + moved_out, plays)
    return {
        "give": list(give), "get": list(get),
        "myGain": round(my_after - my_before, 1), "theirGain": round(th_after - th_before, 1),
        "weeks": [{"week": w, "gain": round(a - b, 1)} for w, a, b in zip(weeks, my_wk_after, my_wk_before)],
    }


def youth_flag(give: list[dict], get: list[dict], gap: int = YOUTH_GAP) -> bool:
    """True when the youngest player you give is at least gap years younger than the youngest you get."""
    ga = [p["age"] for p in give if p.get("age")]
    ra = [p["age"] for p in get if p.get("age")]
    return bool(ga and ra) and min(ra) - min(ga) >= gap


def starter_strength(slots: list[str], players: list[dict]) -> dict[str, float]:
    """Playoff rate summed over one team's best lineup, per trade position. Same rates trades use."""
    ps = [{"id": p["id"], "pos": p["pos"], "points": p["rate"], "eligible": bool(p["rate"])} for p in players]
    _, ids = waivers.best_lineup(slots, ps)
    by_id = {p["id"]: p for p in players}
    out = {pos: 0.0 for pos in NEED_POSITIONS}
    for i in ids:
        if i is not None and by_id[i]["pos"] in out:
            out[by_id[i]["pos"]] += by_id[i]["rate"]
    return {pos: round(v, 1) for pos, v in out.items()}


def needs(slots: list[str], rosters: list[list[dict]]) -> list[list[str]]:
    """Per roster (same order as input): up to NEED_MAX positions where its starters sit furthest
    below the league median. Empty when nothing is below median."""
    if not rosters:
        return []
    strengths = [starter_strength(slots, players) for players in rosters]
    median = {pos: statistics.median(s[pos] for s in strengths) for pos in NEED_POSITIONS}
    out = []
    for s in strengths:
        short = [(round(median[pos] - s[pos], 1), pos) for pos in NEED_POSITIONS if round(median[pos] - s[pos], 1) > 0]
        short.sort(key=lambda x: (-x[0], NEED_POSITIONS.index(x[1])))
        out.append([pos for _, pos in short[:NEED_MAX]])
    return out


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def owned_picks(team_names: dict[int, str], traded: list[dict], seasons: list[str], rounds: int) -> dict[int, list[dict]]:
    """Draft picks each roster owns after trades: its own picks for rounds 1..rounds in each season.

    team_names: roster id -> team name. traded: rows {season, round, rosterId, ownerId}, where rosterId
    is the original owner and ownerId the current one. Returns roster id -> picks sorted by season, round.
    Each pick: {season, round, label, from}, from is the original team name, or None when it is their own.
    """
    owner = {(s, r, rid): rid for s in seasons for r in range(1, rounds + 1) for rid in team_names}
    for t in traded:
        key = (t["season"], t["round"], t["rosterId"])
        if key in owner:
            owner[key] = t["ownerId"]
    out = {rid: [] for rid in team_names}
    for (s, r, orig), who in owner.items():
        if who in out:
            out[who].append({"season": s, "round": r, "label": f"{s} {_ordinal(r)}",
                             "from": None if who == orig else team_names[orig]})
    for picks in out.values():
        picks.sort(key=lambda p: (p["season"], p["round"]))
    return out


def suggest(slots, weeks, mine: list[dict], teams: list[dict], plays, limit: int = 8) -> list[dict]:
    """1 for 1 trades with every other team that raise both teams' playoff lineups.

    teams: [{"name", "players"}] for every other team. Ranked by the smaller of the two gains
    first (a fair trade gets accepted), then by your gain. At most two ideas per partner.
    """
    if not weeks:
        return []
    my_base = playoff_total(slots, weeks, mine, plays)[0]
    tradeable = [p for p in mine if p["rate"] and p["pos"] in TRADE_POSITIONS]
    out = []
    for t in teams:
        theirs = t["players"]
        th_base = playoff_total(slots, weeks, theirs, plays)[0]
        ideas = []
        for g in tradeable:
            for r in theirs:
                if not r["rate"] or r["pos"] not in TRADE_POSITIONS:
                    continue
                my_after = playoff_total(slots, weeks, [p for p in mine if p["id"] != g["id"]] + [r], plays)[0]
                mg = round(my_after - my_base, 1)
                if mg < MIN_IDEA_GAIN:
                    continue
                th_after = playoff_total(slots, weeks, [p for p in theirs if p["id"] != r["id"]] + [g], plays)[0]
                tg = round(th_after - th_base, 1)
                if tg <= 0:
                    continue
                ideas.append({"team": t["name"], "give": [g["id"]], "get": [r["id"]], "myGain": mg, "theirGain": tg})
        ideas.sort(key=lambda i: (-min(i["myGain"], i["theirGain"]), -i["myGain"], i["give"][0], i["get"][0]))
        out += ideas[:2]
    out.sort(key=lambda i: (-min(i["myGain"], i["theirGain"]), -i["myGain"], i["team"]))
    return out[:limit]
