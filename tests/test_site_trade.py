"""Pure helpers behind the Trade view (site/app.js, S4): idea merging, rival badge rule, builder grouping,
partner context, picks that stay out of the scoring, and the position filter. Run in node like test_states.py."""
import json
import shutil
import subprocess

import pytest

from pipeline.common import ROOT

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="needs node")


def _node(js: str):
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert app.endswith("\nmain();\n")
    src = app[: -len("main();\n")] + js
    out = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_merge_joins_same_partner_get_and_gains():
    got = _node("""
const ideas = [
  {team: "Olav", give: ["1"], get: ["9", "8"], myGain: 5, theirGain: 4, thisWeek: 1, youthFlag: false},
  {team: "Olav", give: ["2"], get: ["8", "9"], myGain: 5, theirGain: 4, thisWeek: 2, youthFlag: true},
  {team: "Olav", give: ["3"], get: ["9", "8"], myGain: 5, theirGain: 3.5, thisWeek: 1, youthFlag: false},
  {team: "Other", give: ["4"], get: ["9", "8"], myGain: 5, theirGain: 4, thisWeek: 1, youthFlag: false},
  {team: "Olav", give: ["5"], get: ["7"], myGain: 5, theirGain: 4, thisWeek: 1, youthFlag: false},
];
const groups = mergeIdeas(ideas);
console.log(JSON.stringify(groups.map(g => ({team: g.team, get: g.get, n: g.variants.map(v => v.give[0]), first: g.variants[0].give[0]}))));""")
    assert got == [
        {"team": "Olav", "get": ["9", "8"], "n": ["1", "2"], "first": "1"},
        {"team": "Olav", "get": ["9", "8"], "n": ["3"], "first": "3"},
        {"team": "Other", "get": ["9", "8"], "n": ["4"], "first": "4"},
        {"team": "Olav", "get": ["7"], "n": ["5"], "first": "5"},
    ], "same partner, same get set (any order), same gains merge. Anything else stays apart"


@needs_node
def test_rival_badge_rule():
    got = _node("""
console.log(JSON.stringify([
  helpsRival(3, 9, 4, 6),     // top 4 and gains more than you
  helpsRival(6, 9, 4, 6),     // above you in the standings and gains more
  helpsRival(6, 2, 4, 6),     // below you, not top 4: no badge
  helpsRival(3, 9, 6, 4),     // top 4 but gains less than you
  helpsRival(null, 2, 4, 6),  // no standings row for the partner
  helpsRival(2, null, 4, 6),  // top 4 with no standing for you
]));""")
    assert got == [True, True, False, False, False, True]


@needs_node
def test_partner_text_and_playoff_share():
    got = _node("""
const st = {teams: [{name: "Olav é Trois", seed: 3, playoffPct: 100}, {name: "Low", seed: 12, playoffPct: 0.2}, {name: "Mid", seed: 7, playoffPct: 38.4}]};
console.log(JSON.stringify([
  partnerText(st, "Olav é Trois"), partnerText(st, "Low"), partnerText(st, "Mid"),
  partnerText(st, "Nobody"), partnerText(null, "Olav é Trois"),
  playoffText(null), playoffText(99.99), playoffText(0),
]));""")
    assert got == [
        "Olav é Trois · seed 3 · 100% playoffs", "Low · seed 12 · under 1% playoffs", "Mid · seed 7 · 38% playoffs",
        "Nobody", "Olav é Trois", None, "100% playoffs", "0% playoffs",
    ]


@needs_node
def test_builder_groups_by_position_then_rate():
    got = _node("""
const ps = [
  {name: "Kick", pos: "K", rate: 9}, {name: "Wa", pos: "WR", rate: 10}, {name: "Qb2", pos: "QB", rate: 12},
  {name: "Wb", pos: "WR", rate: 15}, {name: "Ra", pos: "RB", rate: 7}, {name: "Dst", pos: "DEF", rate: 5},
  {name: "Odd", pos: "LB", rate: 1}, {name: "Te", pos: "TE", rate: 4}, {name: "Qb1", pos: "QB", rate: 20},
];
console.log(JSON.stringify(groupByPosition(ps).map(g => [g.pos, g.players.map(p => p.name)])));""")
    assert got == [
        ["QB", ["Qb1", "Qb2"]], ["RB", ["Ra"]], ["WR", ["Wb", "Wa"]], ["TE", ["Te"]], ["K", ["Kick"]], ["DEF", ["Dst"]], ["LB", ["Odd"]],
    ]


@needs_node
def test_ideas_filter_by_the_position_they_bring_back():
    got = _node("""
const byId = {"Them|a": {id: "a", pos: "QB"}, "Them|b": {id: "b", pos: "WR"}, "Them|c": {id: "c", pos: "RB"}};
const i = {team: "Them", get: ["a", "b"]}, j = {team: "Them", get: ["c"]};
console.log(JSON.stringify([ideaHasPos(i, "ALL", byId), ideaHasPos(i, "QB", byId), ideaHasPos(i, "RB", byId), ideaHasPos(j, "WR", byId), ideaHasPos(j, "RB", byId)]));""")
    assert got == [True, True, False, False, True]


@needs_node
def test_empty_ideas_copy_uses_the_threshold():
    got = _node("""console.log(JSON.stringify([noIdeasText(2), noIdeasText(undefined)]));""")
    assert got == [
        "No one for one trade adds at least 2.0 points for you and helps them too. Try the builder below.",
        "No one for one trade helps both teams right now. Try the builder below.",
    ]


@needs_node
def test_picks_have_their_own_ids_and_never_score():
    got = _node("""
const p1 = {season: "2027", round: 1, label: "2027 1st", from: null};
const p2 = {season: "2027", round: 1, label: "2027 1st", from: "Team X"};
const td = {slots: ["QB", "RB"], flexEligible: {}, weeks: [15], plays: {"15": ["AAA", "BBB"]}};
const mine = [{id: "1", pos: "QB", rate: 10, team: "AAA"}, {id: "2", pos: "RB", rate: 5, team: "AAA"}];
const theirs = [{id: "3", pos: "RB", rate: 9, team: "BBB"}];
const plain = tradeResult(td, mine, theirs, new Set(["2"]), new Set(["3"]));
const withPicks = tradeResult(td, mine, theirs, new Set(["2", pickId(p1)]), new Set(["3", pickId(p2)]));
console.log(JSON.stringify({
  ids: [pickId(p1), pickId(p2)], distinct: pickId(p1) !== pickId(p2), isPick: [isPickId(pickId(p1)), isPickId("3")],
  labels: [pickLabel(p1), pickLabel(p2)],
  same: plain.myGain === withPicks.myGain && plain.theirGain === withPicks.theirGain && plain.thisWeek === withPicks.thisWeek,
  counted: [countPlayers(new Set(["2", pickId(p1)])), signClass(2), signClass(-1), signClass(0)],
}));""")
    assert got["distinct"] is True
    assert got["isPick"] == [True, False]
    assert got["labels"] == ["2027 1st", "2027 1st (from Team X)"]
    assert got["same"] is True, "picks change no score"
    assert got["counted"] == [1, "pos", "neg", ""]
