"""v3 trades: engine tests, plus a check that the site's JavaScript optimizer agrees with Python."""
import json
import shutil
import subprocess

import pytest

from pipeline import trades as tr
from pipeline.common import BUILD, read_json

SLOTS = ["QB", "RB", "WR", "TE", "FLEX"]
ALL = lambda w, t: True


def R(pid, pos, rate, team="AAA", age=None):
    return {"id": pid, "pos": pos, "team": team, "rate": rate, "age": age}


def mine():      # deep at RB, weak at WR. Best lineup 15+14+4+7+13 = 53
    return [R("qb", "QB", 15), R("rb1", "RB", 14), R("rb2", "RB", 13), R("rb3", "RB", 12), R("wr", "WR", 4), R("te", "TE", 7)]


def theirs():    # deep at WR, weak at RB. Best lineup 16+3+15+8+14 = 56
    return [R("tqb", "QB", 16), R("twr1", "WR", 15), R("twr2", "WR", 14), R("twr3", "WR", 13), R("trb", "RB", 3), R("tte", "TE", 8)]


def test_playoff_total_skips_bye_weeks():
    plays = lambda w, t: not (w == 16 and t == "BBB")
    ps = [R("qb", "QB", 10, "BBB"), R("rb", "RB", 5), R("wr", "WR", 5), R("te", "TE", 5), R("fx", "RB", 4)]
    total, per = tr.playoff_total(SLOTS, [15, 16], ps, plays)
    assert per == [29.0, 19.0] and total == 48.0


def test_evaluate_both_sides():
    r = tr.evaluate(SLOTS, [15], mine(), theirs(), ["rb2"], ["twr1"], ALL)
    # me: 15 + 14 + WR 15 + 7 + FLEX rb3 12 = 63, up 10 from 53
    assert r["myGain"] == 10.0 and r["weeks"] == [{"week": 15, "gain": 10.0}]
    # them: 16 + RB 13 + 14 + 8 + FLEX 13 = 64, up 8 from 56
    assert r["theirGain"] == 8.0


def test_evaluate_lopsided_trade_hurts_them():
    r = tr.evaluate(SLOTS, [15], mine(), theirs(), ["wr"], ["twr1"], ALL)
    assert r["myGain"] == 11.0 and r["theirGain"] < 0


def test_suggest_only_trades_that_help_both():
    ideas = tr.suggest(SLOTS, [15, 16], mine(), [{"name": "T", "players": theirs()}], ALL)
    assert ideas, "rb for wr swap should help both"
    for i in ideas:
        assert i["myGain"] >= tr.MIN_GAIN and i["theirGain"] >= tr.MIN_GAIN
        assert tr.evaluate(SLOTS, [15, 16], mine(), theirs(), i["give"], i["get"], ALL)["myGain"] == i["myGain"]


def test_suggest_skips_k_def_and_no_weeks():
    assert tr.suggest(SLOTS, [], mine(), [{"name": "T", "players": theirs()}], ALL) == []
    k = [R("k", "K", 20)]
    assert all(i["give"] != ["k"] for i in tr.suggest(SLOTS + ["K"], [15], mine() + k, [{"name": "T", "players": theirs()}], ALL))


def test_youth_flag():
    assert tr.youth_flag([{"age": 22}], [{"age": 27}])
    assert not tr.youth_flag([{"age": 25}], [{"age": 27}])
    assert not tr.youth_flag([{"age": None}], [{"age": 30}])


NODE = shutil.which("node")
HAVE_BUILD = all((BUILD / f"trade-{k}.json").exists() for k in ("fantasizing", "hwh", "chicago-dynasty"))


@pytest.mark.skipif(not NODE or not HAVE_BUILD, reason="needs node and a built data/build")
@pytest.mark.parametrize("key", ["fantasizing", "hwh", "chicago-dynasty"])
def test_site_optimizer_matches_python(key, tmp_path):
    td = read_json(BUILD / f"trade-{key}.json")
    plays = lambda w, t: t in set(td["plays"][str(w)])
    app = (BUILD.parent.parent / "site" / "app.js").read_text(encoding="utf-8").replace("\nmain();\n", "\n")
    script = tmp_path / "parity.js"
    script.write_text(app + """
const td = JSON.parse(require("fs").readFileSync(process.argv[2], "utf8"));
const mine = td.rosters.filter(r => r.isMine)[0].players;
const out = {totals: {}, ideas: []};
td.rosters.forEach(r => { out.totals[r.name] = sum(playoffWeeks(td, r.players)); });
td.ideas.forEach(i => {
  const th = td.rosters.filter(r => r.name === i.team)[0].players;
  const res = tradeResult(td, mine, th, new Set(i.give), new Set(i.get));
  out.ideas.push([res.myGain, res.theirGain, res.thisWeek]);
});
console.log(JSON.stringify(out));
""", encoding="utf-8")
    got = json.loads(subprocess.run([NODE, str(script), str(BUILD / f"trade-{key}.json")], capture_output=True,
                                    text=True, check=True).stdout)
    for r in td["rosters"]:
        assert got["totals"][r["name"]] == pytest.approx(tr.playoff_total(td["slots"], td["weeks"], r["players"], plays)[0], abs=0.05), r["name"]
    for i, (mg, tg, now) in zip(td["ideas"], got["ideas"]):
        assert (mg, tg, now) == pytest.approx((i["myGain"], i["theirGain"], i["thisWeek"]), abs=0.05)
