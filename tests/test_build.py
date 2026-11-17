"""Build tests. Invariants on a fresh build from the committed raw cache, plus helper unit tests."""
import json
import shutil

import pytest

from pipeline import build as bd
from pipeline.common import RAW, read_json

SEASON, WEEK = 2026, 11
HAVE_RAW = (RAW / str(SEASON) / str(WEEK) / "status.json").exists()
needs_raw = pytest.mark.skipif(not HAVE_RAW, reason="no cached raw data")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("build")
    res = bd.build(SEASON, WEEK, out_dir=out, save_idmap=False)
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
