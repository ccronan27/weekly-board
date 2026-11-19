"""Build tests. Invariants on a fresh build from the committed raw cache, plus helper unit tests."""
import json
import shutil
from datetime import datetime, timezone

import pytest

from pipeline import build as bd
from pipeline.common import DATA, RAW, read_json

SEASON, WEEK = 2026, 11
HAVE_RAW = (RAW / str(SEASON) / str(WEEK) / "status.json").exists()
needs_raw = pytest.mark.skipif(not HAVE_RAW, reason="no cached raw data")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("build")
    res = bd.build(SEASON, WEEK, out_dir=out, save_idmap=False, recommended_root=out / "rec")
    return out, res


@needs_raw
def test_three_leagues_with_stamps(built):
    out, res = built
    assert set(res["leagues"]) == {"fantasizing", "hwh", "chicago-dynasty"}
    for k, o in res["leagues"].items():
        assert o["generatedAt"] and o["sources"], k
        assert all("lastUpdated" in s for s in o["sources"].values())
        assert (out / f"{k}.json").exists() and (out / f"pool-{k}.json").exists()
    assert json.loads((out / "meta.json").read_text())["espnRosters"]["syncedAt"]


@needs_raw
def test_recommendation_never_worse_and_never_starts_ineligible(built):
    for k, o in built[1]["leagues"].items():
        lu = o["lineup"]
        assert lu["gain"] >= 0 and lu["recommendedPoints"] > 0, k
        for s in lu["slots"]:
            r = s["recommended"]
            assert r is None or (r["eligible"] and "BYE" not in r["flags"] and "OUT" not in r["flags"]), (k, r)
        ids = [s["recommended"]["id"] for s in lu["slots"] if s["recommended"]]
        assert len(ids) == len(set(ids)), "a player was recommended twice"


@needs_raw
def test_slot_layouts_match_the_leagues(built):
    slots = {k: [s["slot"] for s in o["lineup"]["slots"]] for k, o in built[1]["leagues"].items()}
    assert slots["fantasizing"] == ["QB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
    assert slots["hwh"] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
    assert slots["chicago-dynasty"] == ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "FLEX", "K"]


@needs_raw
def test_alerts_flag_every_out_or_bye_starter(built):
    for k, o in built[1]["leagues"].items():
        bad = [s["current"]["name"] for s in o["lineup"]["slots"]
               if s["current"] and any(f in ("BYE", "OUT", "IR", "SUSPENDED", "INACTIVE") for f in s["current"]["flags"])]
        assert sorted(a["player"] for a in o["lineup"]["alerts"]) == sorted(bad), k


@needs_raw
def test_no_owner_identity_in_any_output(built):
    out = built[0]
    blob = "".join(p.read_text() for p in out.glob("*.json")).lower()
    for banned in ("owner_id", "display_name", "ownername", "865460014343634944", "avatar"):
        assert banned not in blob, banned


@needs_raw
def test_pool_is_sorted_and_scored(built):
    pool = json.loads((built[0] / "pool-hwh.json").read_text())["players"]
    pts = [p["points"] for p in pool]
    assert pts == sorted(pts, reverse=True) and len(pool) > 200
    assert any(p["rostered"] for p in pool) and any(not p["rostered"] for p in pool)


@needs_raw
def test_refuses_to_publish_an_empty_board(tmp_path):
    src = RAW / str(SEASON)
    dst = tmp_path / "raw" / str(SEASON)
    shutil.copytree(src, dst)
    for name in ("sleeper_projections", "espn_defaults"):
        f = dst / str(WEEK) / f"{name}.json"
        d = read_json(f)
        d["data"] = []
        f.write_text(json.dumps(d))
    with pytest.raises(bd.BuildError, match="empty"):
        bd.build(SEASON, WEEK, raw_root=tmp_path / "raw", out_dir=tmp_path / "out", save_idmap=False)


def test_build_needs_ingest_status(tmp_path):
    with pytest.raises(bd.BuildError, match="ingest"):
        bd.build(2031, 1, raw_root=tmp_path, out_dir=tmp_path, save_idmap=False)


# ---- helpers ----

def test_normalize_status():
    n = bd.normalize_status
    assert n("OUT", "espn") == "OUT" and n("Out", "sleeper") == "OUT" and n("IR", "sleeper") == "IR"
    assert n("INJURY_RESERVE", "espn") == "IR" and n("PUP", "sleeper") == "OUT" and n("Sus", "sleeper") == "SUSPENDED"
    assert n("Questionable", "sleeper") == "QUESTIONABLE" and n("ACTIVE", "espn") is None and n(None, "sleeper") is None
    assert n(None, "sleeper", "Inactive") == "INACTIVE" and n(None, "sleeper", "Injured Reserve") == "IR"


GAME = {"gameId": "g", "week": 11, "gameday": "2026-11-22", "gametime": "13:00", "away": "MIA", "home": "BUF",
        "homeSpread": 6.0, "total": 46.0, "impliedHome": 26.0, "impliedAway": 20.0}


def test_game_context_spread_totals_and_utc_kickoff():
    ctx = bd.game_context([GAME])
    assert ctx["BUF"]["spread"] == -6.0 and ctx["MIA"]["spread"] == 6.0, "negative means favored"
    assert ctx["BUF"]["implied"] == 26.0 and ctx["BUF"]["oppImplied"] == 20.0 and ctx["MIA"]["implied"] == 20.0
    assert ctx["BUF"]["kickoff"] == "2026-11-22T18:00Z", "13:00 Eastern in November is 18:00 UTC"
    assert "SEA" not in ctx, "a team with no game is on a bye"


def test_game_context_without_lines_or_time():
    g = dict(GAME, homeSpread=None, total=None, impliedHome=None, impliedAway=None, gametime=None)
    c = bd.game_context([g])["BUF"]
    assert c["spread"] is None and c["implied"] is None and c["kickoff"] is None


def test_sleeper_current_handles_empty_slots():
    assert bd._sleeper_current(["QB", "RB", "K"], ["1", "0", "3"]) == ["1", None, "3"]
    assert bd._sleeper_current(["QB", "RB", "K"], ["1"]) == ["1", None, None]


def test_espn_current_fills_matching_slots_in_order():
    recs = [{"id": "a", "slot": "FLEX"}, {"id": "b", "slot": "FLEX"}, {"id": "c", "slot": "QB"}, {"id": "d", "slot": "BN"}, {"id": "e", "slot": "IR"}]
    assert bd._espn_current(["QB", "FLEX", "FLEX", "K"], recs) == ["c", "a", "b", None]


# ---- locks, taxi, watch, week mismatch. Fixtures that need changed raw data copy the cache first ----

LOCK_NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)   # after the Thu IND/HOU game, before Sunday


def _raw_copy(tmp_path):
    shutil.copytree(RAW / str(SEASON), tmp_path / "raw" / str(SEASON))
    return tmp_path / "raw"


def _edit(raw_root, name, fn):
    f = raw_root / str(SEASON) / str(WEEK) / f"{name}.json"
    d = read_json(f)
    fn(d["data"])
    f.write_text(json.dumps(d))


@pytest.fixture(scope="module")
def locked(tmp_path_factory):
    out = tmp_path_factory.mktemp("locked")
    return bd.build(SEASON, WEEK, out_dir=out, save_idmap=False, recommended_root=out / "rec", now=LOCK_NOW)


@needs_raw
def test_kicked_off_players_are_locked_and_fields_present(locked):
    hwh = locked["leagues"]["hwh"]["lineup"]
    for s in hwh["slots"]:
        for side in ("current", "recommended"):
            p = s[side]
            if p:
                assert "locked" in p and "injuryNotes" in p and "espn" in p and "rotowire" in p, side
    roster = locked["leagues"]["hwh"]["roster"]
    for p in roster:
        assert p["locked"] == (p["team"] in ("IND", "HOU")), p["name"]
    assert any(p["locked"] for p in roster) and any(not p["locked"] for p in roster)


@needs_raw
def test_no_move_or_slot_change_involves_a_locked_player(locked):
    for k, o in locked["leagues"].items():
        for m in o["lineup"]["moves"]:
            assert not (m["in"] and m["in"]["locked"]), (k, m["in"]["name"])
            assert not (m["out"] and m["out"]["locked"]), (k, m["out"]["name"])
        for s in o["lineup"]["slots"]:
            cur = s["current"]
            if cur and cur["locked"]:
                assert s["recommended"]["id"] == cur["id"], (k, cur["name"])
        assert o["lineup"]["gain"] >= 0, k


@needs_raw
def test_locked_starter_out_scores_zero_and_keeps_slot(tmp_path):
    raw = _raw_copy(tmp_path)
    base = bd.build(SEASON, WEEK, raw_root=raw, out_dir=tmp_path / "a", save_idmap=False, now=LOCK_NOW)["leagues"]["hwh"]
    taylor = next(s["current"] for s in base["lineup"]["slots"] if s["current"] and s["current"]["name"] == "Jonathan Taylor")
    _edit(raw, "sleeper_players", lambda d: d[taylor["id"]].update(injuryStatus="Out"))
    o = bd.build(SEASON, WEEK, raw_root=raw, out_dir=tmp_path / "b", save_idmap=False, now=LOCK_NOW)["leagues"]["hwh"]
    rb_slot = next(s for s in o["lineup"]["slots"] if s["current"] and s["current"]["id"] == taylor["id"])
    assert rb_slot["current"]["locked"] and not rb_slot["current"]["eligible"] and rb_slot["recommended"]["id"] == taylor["id"]
    counted = sum(s["current"]["points"] for s in o["lineup"]["slots"] if s["current"] and s["current"]["eligible"])
    assert o["lineup"]["currentPoints"] == round(counted, 1)
    assert not any(m["out"] and m["out"]["id"] == taylor["id"] for m in o["lineup"]["moves"])


@needs_raw
def test_taxi_players_get_taxi_slot_and_reserve_gets_ir(tmp_path):
    raw = _raw_copy(tmp_path)

    moved = []

    def move(d):
        mine = next(t for t in d["hwh"]["teams"] if t["isMine"])
        bench = [p for p in mine["players"] if p not in mine["starters"] and p not in mine["reserve"] and p not in mine["taxi"]]
        mine["taxi"] = mine["taxi"] + [bench[0]]
        mine["reserve"] = mine["reserve"] + [bench[1]]
        moved.extend(bench[:2])
    _edit(raw, "sleeper_leagues", move)
    res = bd.build(SEASON, WEEK, raw_root=raw, out_dir=tmp_path / "out", save_idmap=False, now=LOCK_NOW)
    by = {p["id"]: p for p in res["leagues"]["hwh"]["roster"]}
    taxi, ir = by[moved[0]], by[moved[1]]
    assert taxi["slot"] == "TAXI" and not taxi["eligible"] and "IR" not in taxi["flags"]
    assert ir["slot"] == "IR" and not ir["eligible"] and "IR" in ir["flags"]


@needs_raw
def test_watch_lists_questionable_starter(tmp_path):
    base = bd.build(SEASON, WEEK, out_dir=tmp_path / "a", save_idmap=False, recommended_root=tmp_path / "rec", now=LOCK_NOW)["leagues"]["hwh"]
    starter = next(s["current"] for s in base["lineup"]["slots"] if s["current"] and not s["current"]["locked"]
                   and not s["current"]["flags"])
    raw = _raw_copy(tmp_path)
    _edit(raw, "sleeper_players", lambda d: d[starter["id"]].update(injuryStatus="Questionable", injuryNotes="Knee"))
    o = bd.build(SEASON, WEEK, raw_root=raw, out_dir=tmp_path / "b", save_idmap=False, now=LOCK_NOW)["leagues"]["hwh"]
    w = next(x for x in o["lineup"]["watch"] if x["player"] == starter["name"])
    assert w["flags"] == ["QUESTIONABLE"] and w["injuryNotes"] == "Knee"
    assert set(w) == {"player", "slot", "flags", "kickoff", "injuryNotes"}


@needs_raw
def test_week_mismatch_flag(tmp_path):
    ok = bd.build(SEASON, WEEK, out_dir=tmp_path / "ok", save_idmap=False, recommended_root=tmp_path / "rec", now=LOCK_NOW)
    assert ok["meta"]["espnRosters"]["weekMismatch"] is False
    rosters = read_json(DATA / "espn" / "rosters.json")
    rosters["week"] = WEEK - 1
    f = tmp_path / "rosters.json"
    f.write_text(json.dumps(rosters))
    bad = bd.build(SEASON, WEEK, out_dir=tmp_path / "bad", save_idmap=False, recommended_root=tmp_path / "rec", now=LOCK_NOW, rosters_path=f)
    assert bad["meta"]["espnRosters"]["weekMismatch"] is True


@needs_raw
def test_waivers_targets_are_free_agents_with_real_gains(built):
    out, res = built
    for k, o in res["leagues"].items():
        w = o["waivers"]
        pool = {p["id"]: p for p in read_json(out / f"pool-{k}.json")["players"]}
        mine = {p["id"] for p in o["roster"]}
        gains = [t["gain"] for t in w["targets"]]
        assert gains == sorted(gains, reverse=True) and all(g > 0 for g in gains), k
        for t in w["targets"]:
            p = t["player"]
            assert not pool[p["id"]]["rostered"] and p["id"] not in mine, (k, p["name"])
            assert p["eligible"] and not p["locked"], (k, p["name"])
            assert t["replaces"] is None or t["replaces"]["id"] in mine
        positions = [t["player"]["pos"] for t in w["targets"]]
        assert all(positions.count(x) <= 2 for x in positions) and len(positions) <= 8
        for pos, lst in w["byPosition"].items():
            assert all(p["pos"] == pos and not pool[p["id"]]["rostered"] for p in lst)
        assert w["freeAgents"] > 0


@needs_raw
def test_dynasty_gets_no_drop_idea_and_redraft_drop_is_a_bench_player(built):
    lg = built[1]["leagues"]
    assert lg["chicago-dynasty"]["waivers"]["dynasty"] is True and lg["chicago-dynasty"]["waivers"]["drop"] is None
    assert "DEF" not in lg["chicago-dynasty"]["waivers"]["byPosition"]     # league starts no DEF
    for k in ("hwh", "fantasizing"):
        o = lg[k]
        drop = o["waivers"]["drop"]
        starters = {s["recommended"]["id"] for s in o["lineup"]["slots"] if s["recommended"]}
        slot = next(p["slot"] for p in o["roster"] if p["id"] == drop["id"])
        assert drop["id"] not in starters and slot not in ("IR", "TAXI"), k


@needs_raw
def test_locked_free_agents_never_targeted(tmp_path):
    o = bd.build(SEASON, WEEK, out_dir=tmp_path, save_idmap=False, recommended_root=tmp_path / "rec", now=LOCK_NOW)["leagues"]
    for k, lg in o.items():
        for t in lg["waivers"]["targets"]:
            assert t["player"]["team"] not in ("IND", "HOU"), (k, t["player"]["name"])   # played Thursday


def _rec(**kw):
    base = {"slot": "BN", "status": None, "points": 10.0, "flags": [], "ppg": 7.0, "games": 8, "pos": "WR"}
    return {**base, **kw}


def test_long_term_rate_rule():
    assert bd.long_term_rate(_rec()) == (10.0, "projection")                       # healthy: current role
    assert bd.long_term_rate(_rec(flags=["BYE"], points=None)) == (7.0, "season")  # bye now: season average
    assert bd.long_term_rate(_rec(status="OUT", flags=["OUT"])) == (7.0, "season")
    assert bd.long_term_rate(_rec(pos="DEF")) == (7.0, "season")                   # DEF and K: matchup neutral
    assert bd.long_term_rate(_rec(pos="K", games=2)) == (0.0, None)
    assert bd.long_term_rate(_rec(status="IR", flags=["IR"])) == (0.0, None)
    assert bd.long_term_rate(_rec(slot="TAXI")) == (0.0, None)
    assert bd.long_term_rate(_rec(flags=["BYE"], points=None, games=2)) == (0.0, None)


@needs_raw
def test_long_term_targets_cover_playoff_weeks(built):
    for k, o in built[1]["leagues"].items():
        lt = o["waivers"]["longTerm"]
        assert lt is not None and lt["playoffWeeks"] == [15, 16, 17] and lt["weeks"] == [15, 16, 17], k
        mine = {p["id"] for p in o["roster"]}
        gains = [t["gain"] for t in lt["targets"]]
        assert gains == sorted(gains, reverse=True) and all(g > 0 for g in gains)
        for t in lt["targets"]:
            assert t["player"]["id"] not in mine and [x["week"] for x in t["weeks"]] == [15, 16, 17]
            assert abs(sum(x["gain"] for x in t["weeks"]) - t["gain"]) < 0.15
            assert all(x["rank"] is None or 1 <= x["rank"] <= 32 for x in t["weeks"])
            assert t["rateFrom"] == "season" if t["player"]["pos"] in ("DEF", "K") else t["rateFrom"] in ("projection", "season")


def test_defense_ranks_rank_most_allowed_first():
    from pipeline.scoring import League
    lg = League(key="x", name="x", platform="sleeper", scoring={"rec": 1.0}, starters=["WR"])
    stats = {1: [{"opponent": "AAA", "pos": "WR", "stats": {"rec": 10}}, {"opponent": "BBB", "pos": "WR", "stats": {"rec": 4}}],
             2: [{"opponent": "AAA", "pos": "WR", "stats": {"rec": 6}}, {"opponent": "BBB", "pos": "WR", "stats": {"rec": 2, "gp": 0}}]}
    assert bd.defense_ranks(stats, lg) == {("AAA", "WR"): 1, ("BBB", "WR"): 2}


@needs_raw
def test_trade_files_cover_every_team(built):
    out, res = built
    for k, o in res["leagues"].items():
        assert o["trade"]["file"] == f"trade-{k}.json"
        td = read_json(out / o["trade"]["file"])
        assert sum(r["isMine"] for r in td["rosters"]) == 1 and len(td["rosters"]) >= 10
        names = {r["name"] for r in td["rosters"]}
        mine = next(r for r in td["rosters"] if r["isMine"])
        assert {p["id"] for p in mine["players"]} == {p["id"] for p in o["roster"]}
        for i in td["ideas"]:
            assert i["team"] in names and i["team"] != mine["name"]
            assert i["myGain"] >= 0.5 and i["theirGain"] >= 0.5
            assert i["youthFlag"] in (True, False) and (td["dynasty"] or not i["youthFlag"])
        blob = json.dumps(td)
        assert "owner" not in blob and "display_name" not in blob     # team names only


@needs_raw
def test_stretch_run_covers_weeks_before_the_playoffs(built):
    for k, o in built[1]["leagues"].items():
        st = o["waivers"]["stretch"]
        assert st["weeks"] == [12, 13, 14], k
        for t in st["targets"]:
            assert [x["week"] for x in t["weeks"]] == [12, 13, 14] and t["gain"] > 0
        td = read_json(built[0] / o["trade"]["file"])
        assert td["weeks"] == [12, 13, 14, 15, 16, 17] and td["stretchWeeks"] == [12, 13, 14] and td["playoffWeeks"] == [15, 16, 17]
        for i in td["ideas"]:
            assert abs(i["stretchGain"] + i["playoffGain"] - i["myGain"]) < 0.15


@needs_raw
def test_standings_for_sleeper_leagues(built):
    lg = built[1]["leagues"]
    assert lg["fantasizing"]["standings"] is None          # the ESPN sync file has no standings yet
    for k in ("hwh", "chicago-dynasty"):
        st = lg[k]["standings"]
        assert st["weeksLeft"] == [11, 12, 13, 14] and st["playoffTeams"] == 6 and st["byes"] == 2
        assert len(st["teams"]) == 12 and sum(t["isMine"] for t in st["teams"]) == 1
        assert sum(t["playoffPct"] for t in st["teams"]) == pytest.approx(600.0, abs=1.0)
        assert sum(t["byePct"] for t in st["teams"]) == pytest.approx(200.0, abs=1.0)
        assert [t["seed"] for t in st["teams"]] == list(range(1, 13))
        assert [g["week"] for g in st["myGames"]] == [11, 12, 13, 14]
        assert all(0 <= g["winPct"] <= 100 for g in st["myGames"])
        assert 10 < st["sd"] < 60


@needs_raw
def test_recap_field_and_recommended_files(built):
    """Every league carries recap (or null), and each build stores its recommended lineup for the next week."""
    out, res = built
    for k, o in res["leagues"].items():
        assert "recap" in o, k
        stored = read_json(out / "rec" / str(SEASON) / str(WEEK) / f"recommended-{k}.json")
        assert [s["slot"] for s in stored["slots"]] == [s["slot"] for s in o["lineup"]["slots"]], k
        assert [s["playerId"] for s in stored["slots"]] == [(s["recommended"] or {}).get("id") for s in o["lineup"]["slots"]], k
        r = o["recap"]
        if r is None:
            continue
        assert set(r) == {"week", "actual", "optimal", "recommended", "left"}, k
        assert r["week"] == WEEK - 1, k
        assert r["recommended"] is None, "no recommended file exists for the week before the cache"
        if k == "fantasizing":   # ESPN has no platform score
            assert r["actual"] is None, k
        if r["optimal"] is not None and r["actual"] is not None:
            assert r["left"] == pytest.approx(r["optimal"] - r["actual"], abs=0.11), k


@needs_raw
def test_faab_rosgain_and_bids_for_sleeper_leagues(built):
    lg = built[1]["leagues"]
    assert lg["fantasizing"]["waivers"]["faab"] is None and lg["fantasizing"]["waivers"]["targets"] is not None
    for k in ("hwh", "chicago-dynasty"):
        w = lg[k]["waivers"]
        faab = w["faab"]
        if faab is None:       # older raw cache without waiver keys: null, never a crash
            assert all(t["bid"] is None for t in w["targets"])
            continue
        assert faab["budget"] == 100 and 0 <= faab["left"] <= 100
        assert faab["teams"] == sorted(faab["teams"], key=lambda t: -t["left"])
        lists = [w["targets"]] + [x["targets"] for x in (w["stretch"], w["longTerm"]) if x]
        for targets in lists:
            for t in targets:
                assert t["rosGain"] is not None and t["rosGain"] >= 0
                assert 0 <= t["bid"] <= faab["left"]
                if t["rosGain"] > 0:
                    assert t["bid"] >= 1
    for k in ("hwh", "chicago-dynasty"):
        st = lg[k]["standings"]
        games = st["myGames"]
        cur = [g for g in games if g["week"] == 11]
        assert cur and cur[0]["ifWin"] is not None and cur[0]["ifWin"] >= cur[0]["ifLose"]
        assert all("ifWin" not in g for g in games if g["week"] != 11)
        assert all("ifWin" not in t for t in st["teams"])
