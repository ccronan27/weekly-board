"""Waivers and standings (UX plan S3). Node runs the pure helpers in site/app.js, the way tests/test_states.py does."""
import json
import shutil
import subprocess

import pytest

from pipeline.common import ROOT

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(not NODE, reason="needs node")
APP = (ROOT / "site" / "app.js").read_text(encoding="utf-8")


def _node(js: str):
    assert APP.endswith("\nmain();\n")
    src = APP[: -len("main();\n")] + js
    out = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _t(pid, name, gain, ros=None, bid=None, pos="WR"):
    return {"gain": gain, "bid": bid, "rosGain": ros, "player": {"id": pid, "name": name, "pos": pos}}


WAIVERS_JS = """
const W = {
  targets: [%s],
  stretch: {weeks: [12, 13], targets: [%s]},
  longTerm: {weeks: [15, 16], targets: [%s]},
};
""" % (
    ", ".join(json.dumps(t) for t in [
        _t(1, "Cam Ward", 1.1, 6.6, 3, "QB"), _t(2, "Small Guy", 0.4, 0.4, 0, "RB"), _t("TB", "Buccaneers", 1.9, 3.0, 2, "DEF"),
    ]),
    ", ".join(json.dumps(t) for t in [_t(1, "Cam Ward", 3.4, 6.6, 3, "QB"), _t(3, "Kicker", 9.6, 8.4, 4, "K")]),
    ", ".join(json.dumps(t) for t in [_t("TB", "Buccaneers", 4.2, 3.0, 2, "DEF"), _t(4, "Late Add", 0.6, None, None, "TE")]),
)


@needs_node
def test_pickup_rows_merge_by_player_and_sort_by_rest_of_season():
    got = _node(WAIVERS_JS + """
const rows = pickupRows(W);
console.log(JSON.stringify(rows.map(r => [r.id, r.name, r.week, r.stretch, r.playoffs, r.ros, r.bid])));""")
    assert got == [
        ["3", "Kicker", None, 9.6, None, 8.4, 4],
        ["1", "Cam Ward", 1.1, 3.4, None, 6.6, 3],
        ["TB", "Buccaneers", 1.9, None, 4.2, 3.0, 2],
        ["2", "Small Guy", 0.4, None, None, 0.4, 0],
        ["4", "Late Add", None, None, 0.6, None, None],
    ], "one row per id, blanks where a list does not hold the player, rest of season first"


@needs_node
def test_pickup_rows_fall_back_to_this_week_and_skip_horizons_without_weeks():
    got = _node("""
const W = {
  targets: [{gain: 2.5, bid: null, rosGain: null, player: {id: 9, name: "Old Build", pos: "RB"}},
            {gain: 0.2, bid: null, rosGain: null, player: {id: 8, name: "Low", pos: "WR"}}],
  stretch: {weeks: [], targets: [{gain: 7, rosGain: 7, bid: 1, player: {id: 7, name: "Ignored", pos: "QB"}}]},
  longTerm: null,
};
console.log(JSON.stringify(pickupRows(W).map(r => [r.name, r.week, r.stretch, r.ros])));""")
    assert got == [["Old Build", 2.5, None, None], ["Low", 0.2, None, None]]


@needs_node
def test_pickup_rows_cap_at_eight():
    got = _node("""
const t = [];
for (let i = 0; i < 12; i++) t.push({gain: 1 + i, rosGain: i, bid: 1, player: {id: i, name: "P" + i, pos: "WR"}});
console.log(JSON.stringify({n: pickupRows({targets: t, stretch: null, longTerm: null}).length, top: pickupRows({targets: t}).map(r => r.name)[0]}));""")
    assert got == {"n": 8, "top": "P11"}


@needs_node
def test_small_gain_is_under_one_point():
    got = _node("""console.log(JSON.stringify([isSmallGain(0.99), isSmallGain(1), isSmallGain(1.1), isSmallGain(null), isSmallGain(undefined), isSmallGain(0)]));""")
    assert got == [True, False, False, False, False, True]


@needs_node
def test_horizon_counts_only_with_weeks():
    got = _node("""console.log(JSON.stringify([horizonOf(null), horizonOf({weeks: []}), horizonOf({weeks: [3]}) !== null]));""")
    assert got == [None, None, True]


@needs_node
def test_odds_swing_and_current_game():
    got = _node("""
const st = {myGames: [
  {week: 12, winPct: 73.1, opp: "A"},
  {week: 11, winPct: 27.7, opp: "B", ifWin: 80.5, ifLose: 47.6},
]};
const cur = currentGame(st);
console.log(JSON.stringify({
  opp: cur.opp,
  line: oddsLine(cur),
  swing: swingLine(cur),
  one: swingLine({ifWin: 50.4, ifLose: 49.6}),
  none: currentGame({myGames: [{week: 12, winPct: 1}]}),
}));""")
    assert got["opp"] == "B"
    assert got["line"] == "Playoff odds 81% with a win, 48% with a loss"
    assert got["swing"] == "This week swings your odds by 33 points."
    assert got["one"] == "This week swings your odds by 1 point."
    assert got["none"] is None


def test_s3_copy_and_no_semicolons_or_em_dashes_in_new_text():
    assert "ESPN standings show up here once the roster sync starts saving them." in APP
    assert "Bids are a rough guide, not tested against real bids. Bigger rest of season gain means a bigger share of what you have left, capped at 40 percent." in APP
    assert "small gain" in APP and "Best pickups" in APP
    assert "docs/SPEC.md" not in APP.split("function renderStandings", 1)[1].split("function ", 1)[0]


def test_standings_points_stay_and_bye_goes_under_400px():
    css = (ROOT / "site" / "style.css").read_text(encoding="utf-8")
    assert ".standings .pf{display:none}" not in css
    assert "@media (max-width:399px){.standings .bye{display:none}}" in css
    assert 'i === 5 ? " bye"' in APP
