"""Lineup view helpers in site/app.js (docs/UX_PLAN.md S2). Node runs the pure functions, the same way tests/test_states.py does."""
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


def test_css_is_one_block_per_section_with_layout_last():
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    sections = ["Band: title", "Scoreboard: this week", "Player rows", "Trades", "Standings and Shotguns", "Waivers:", "All view", "Layout\n", "Sticky bar"]
    for s in sections:
        assert css.count("-- " + s) == 1, s
    assert css.index("-- Layout\n") > css.index("-- All view")   # layout overrides come after the pieces they arrange


@needs_node
def test_upside_options_follow_the_slot_rules_and_skip_locked_and_out_players():
    got = _node("""
const slots = [
  {slot: "QB", recommended: {name: "QB1", pos: "QB", ceiling: 20}},
  {slot: "FLEX", recommended: {name: "WR1", pos: "WR", ceiling: 17.6}},
  {slot: "FLEX", recommended: {name: "RB1", pos: "RB", ceiling: 15, locked: true}},
  {slot: "K", recommended: {name: "K1", pos: "K", ceiling: 9}},
];
const bench = [
  {name: "WR bench", pos: "WR", ceiling: 24.1, eligible: true},
  {name: "TE bench", pos: "TE", ceiling: 19, eligible: true},
  {name: "QB bench", pos: "QB", ceiling: 30, eligible: true},
  {name: "RB out", pos: "RB", ceiling: 40, eligible: false},
  {name: "RB locked", pos: "RB", ceiling: 40, eligible: true, locked: true},
  {name: "K bench", pos: "K", ceiling: 9, eligible: true},
  {name: "No range", pos: "WR", eligible: true},
];
console.log(JSON.stringify({
  canFlex: [canFill("FLEX", "RB"), canFill("FLEX", "TE"), canFill("FLEX", "QB"), canFill("FLEX", "K")],
  canSuper: [canFill("SUPER_FLEX", "QB"), canFill("SUPER_FLEX", "DEF")],
  own: [canFill("K", "K"), canFill("QB", "RB")],
  out: upsideOptions(slots, bench).map(o => [o.player.name, o.starter.name, o.slot]),
}));""")
    assert got["canFlex"] == [True, True, False, False]
    assert got["canSuper"] == [True, False]
    assert got["own"] == [True, False]
    # Biggest gap first: QB bench (30 vs 20 at QB), WR bench (24.1 vs 17.6 at FLEX), TE bench (19 vs 17.6 at FLEX).
    # The K bench player ties the K starter, so it is not an upside. The locked RB starter is never replaced.
    # The RB out and RB locked players are not eligible, and "No range" has no ceiling.
    assert got["out"] == [["QB bench", "QB1", "QB"], ["WR bench", "WR1", "FLEX"], ["TE bench", "WR1", "FLEX"]]


@needs_node
def test_upside_options_list_at_most_three_biggest_gaps_first():
    got = _node("""
const slots = [{slot: "FLEX", recommended: {name: "Low", pos: "WR", ceiling: 5}}];
const bench = [1, 2, 3, 4].map(i => ({name: "P" + i, pos: "RB", ceiling: 5 + i, eligible: true}));
console.log(JSON.stringify(upsideOptions(slots, bench).map(o => o.player.name)));""")
    assert got == ["P4", "P3", "P2"]


@needs_node
def test_bench_split_puts_playable_first():
    got = _node("""
const list = [
  {name: "a", eligible: true, flags: []},
  {name: "b", eligible: true, flags: ["QUESTIONABLE"]},
  {name: "c", eligible: false, flags: ["BYE"]},
  {name: "d", eligible: true, flags: ["OUT"]},
  {name: "e", eligible: true, flags: ["IR"], slot: "BN"},
  {name: "f", eligible: true, flags: [], slot: "IR"},
  {name: "g", eligible: false, flags: [], slot: "TAXI"},
];
const s = benchSplit(list);
console.log(JSON.stringify({p: s.playable.map(p => p.name), o: s.out.map(p => p.name)}));""")
    assert got == {"p": ["a", "b"], "o": ["c", "d", "e", "f", "g"]}


@needs_node
def test_close_call_within_two_points_only():
    got = _node("""
const nb = {name: "Tre Tucker", points: 8.3};
const st = (points, extra) => ({recommended: Object.assign({name: "Starter", points, eligible: true}, extra || {}), nextBest: nb});
console.log(JSON.stringify({
  close: closeCallText(st(9.9)),
  edge: closeCallText(st(10.3)),
  far: closeCallText(st(12)),
  under: closeCallText(st(8.0)),
  locked: closeCallText(st(9.9, {locked: true})),
  none: closeCallText({recommended: {name: "x", points: 9, eligible: true}, nextBest: null}),
  out: closeCallText({recommended: {name: "x", points: 9, eligible: false}, nextBest: nb}),
}));""")
    assert got["close"] == "Close call. Next best Tre Tucker, 1.6 behind."
    assert got["edge"] == "Close call. Next best Tre Tucker, 2.0 behind."
    assert got["far"] == "" and got["under"] == "" and got["locked"] == "" and got["none"] == "" and got["out"] == ""


@needs_node
def test_relative_time_for_the_injury_note():
    got = _node("""
const now = Date.parse("2026-11-19T20:00:00Z");
console.log(JSON.stringify([
  relativeAgo("2026-11-19T17:00:00Z", now), relativeAgo("2026-11-17T20:00:00Z", now),
  relativeAgo("2026-11-19T19:30:00Z", now), relativeAgo("2026-11-19T19:59:50Z", now),
  relativeAgo("2026-11-19T21:00:00Z", now), relativeAgo(null, now), relativeAgo("nonsense", now),
]));""")
    assert got == ["updated 3h ago", "updated 2d ago", "updated 30m ago", "updated just now", "updated just now", "", ""]


@needs_node
def test_backup_lines_say_what_to_do_and_when_it_is_late():
    got = _node("""
const kick = "2026-11-22T21:25Z";
console.log(JSON.stringify({
  backup: backupLines({backup: {name: "Tre Tucker", points: 8.3, kickoff: kick}, lateRisk: false}),
  none: backupLines({backup: null, lateRisk: false}),
  late: backupLines({backup: {name: "Josh Cameron", points: 3.1, kickoff: "2026-11-22T18:00Z"}, lateRisk: true}),
  lateNoTime: backupLines({backup: {name: "X", points: null, kickoff: null}, lateRisk: true}),
  old: backupLines({player: "x"}),
}));""")
    # The time comes from the backup kickoff through shortWhen, so check its shape, not the exact characters
    assert len(got["backup"]) == 1 and got["backup"][0]["late"] is False
    assert got["backup"][0]["text"].startswith("If he sits, start Tre Tucker (8.3, ") and got["backup"][0]["text"].endswith(").")
    assert got["none"] == [{"text": "No eligible backup on your bench.", "late": False}]
    assert got["late"][0]["text"].startswith("If he sits, start Josh Cameron (3.1, ")
    assert len(got["late"]) == 2 and got["late"][1]["late"] is True
    assert got["late"][1]["text"].startswith("He plays after every backup, so there is no swap left if he is ruled out late.")
    assert got["late"][1]["text"].count("Decide before ") == 1 and got["late"][1]["text"].endswith(".")
    assert got["lateNoTime"][0]["text"] == "If he sits, start X."
    assert got["lateNoTime"][1]["text"] == "He plays after every backup, so there is no swap left if he is ruled out late."
    assert got["old"] == []


@needs_node
def test_this_week_game_odds_and_colors():
    got = _node("""
const league = {week: 11, standings: {myGames: [
  {week: 10, opp: "Old", winPct: 50, myMean: 1, oppMean: 1},
  {week: 11, opp: "Olav é Trois ", myMean: 124.6, oppMean: 145.8, winPct: 27.7, ifWin: 80.5, ifLose: 47.6},
]}};
const g = thisGame(league);
console.log(JSON.stringify({
  opp: g.opp, none: thisGame({week: 12, standings: league.standings}), noStd: thisGame({week: 11, standings: null}),
  cls: [winClass(60), winClass(59.9), winClass(40), winClass(40.1), winClass(undefined)],
  pct: [pctText(27.7), pctText(80.5), pctText(undefined)],
  odds: oddsText(g), oneSide: oddsText({ifWin: 12.4}), noOdds: oddsText({}),
}));""")
    assert got["opp"] == "Olav é Trois "
    assert got["none"] is None and got["noStd"] is None
    assert got["cls"] == ["good", "", "bad", "", ""]
    assert got["pct"] == ["28%", "81%", ""]
    assert got["odds"] == "Playoff odds 81% with a win, 48% with a loss"
    assert got["oneSide"] == "Playoff odds 12% with a win" and got["noOdds"] == ""


@needs_node
def test_recap_parts_hide_when_null():
    got = _node("""
console.log(JSON.stringify({
  full: recapLines({week: 10, actual: 164.5, optimal: 195.9, recommended: 179.8}),
  hindsight: recapLines({week: 10, actual: null, optimal: 157.8, recommended: null}),
  none: recapLines({week: 10, actual: null, optimal: null, recommended: null}),
  nul: recapLines(null),
}));""")
    assert got["full"] == ["You scored 164.5", "Best possible with hindsight 195.9", "Board's lineup 179.8"]
    assert got["hindsight"] == ["Best possible with hindsight 157.8"]
    assert got["none"] == [] and got["nul"] == []


@needs_node
def test_scoring_notes_are_reworded_in_plain_words():
    got = _node("""
console.log(JSON.stringify([
  scoringNoteText("ESPN scoring ids with points but no Rotowire equivalent, ignored for Rotowire: [63, 201, 206, 209]"),
  scoringNoteText("D/ST scored with ESPN's default values from config. The sync file does not carry this league's D/ST scoring yet"),
  scoringNoteText("Something else entirely."),
]));""")
    assert got[0] == "ESPN gives points for stats (ids 63, 201, 206, 209) that Rotowire does not have, so Rotowire projections leave them out."
    assert got[1].startswith("Defense scoring uses ESPN's default values.")
    assert got[2] == "Something else entirely."


@needs_node
def test_detail_lines_show_only_what_the_build_has():
    got = _node("""
const now = Date.parse("2026-11-19T20:00:00Z");
const full = {espn: 15.4, rotowire: 16.9, game: {implied: 25.8, spread: -6, oppImplied: 19.8},
  recent: [{week: 6, pts: 30.7}, {week: 7, pts: 22}, {week: 8, pts: null}], injuryNotes: "Spasms", newsUpdated: "2026-11-19T17:00:00Z"};
console.log(JSON.stringify({
  full: detailLines(full, now),
  bare: detailLines({}, now),
  noRecent: detailLines({recent: []}, now),
  noNote: detailLines({injuryNotes: "x"}, now),
}));""")
    assert got["full"] == [
        ["Projections", "ESPN 15.4 · Rotowire 16.9"],
        ["Game", "team total 25.8 · spread -6.0 · opponent total 19.8"],
        ["Recent", "W6 30.7 · W7 22.0"],
        ["Injury note", "Spasms (updated 3h ago)"],
    ]
    assert got["bare"] == []
    assert got["noRecent"] == [["Recent", "No games played yet"]]
    assert got["noNote"] == [["Injury note", "x"]]


@needs_node
def test_axis_is_fixed_zero_to_forty():
    got = _node("""console.log(JSON.stringify([axisPct(0), axisPct(20), axisPct(40), axisPct(55), axisPct(-3), axisPct(undefined)]));""")
    assert got == [0, 50, 100, 100, 0, 0]
