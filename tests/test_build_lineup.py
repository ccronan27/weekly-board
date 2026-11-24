"""P1 fields on a fresh build from the cached raw pull: league links, player news and recent weeks,
lineup context (next best, backups, late risk) and the next refresh time. Backups and late risk for
flagged starters are also checked on a fixed roster, independent of the live week's injuries."""
import re

import pytest

from pipeline import build as bd
from pipeline.common import RAW

SEASON, WEEK = 2026, 11
HAVE_RAW = (RAW / str(SEASON) / str(WEEK) / "status.json").exists()
needs_raw = pytest.mark.skipif(not HAVE_RAW, reason="no cached raw data")
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("build-lineup")
    res = bd.build(SEASON, WEEK, out_dir=out, save_idmap=False, recommended_root=out / "rec")
    return out, res


@needs_raw
def test_league_app_links_for_each_platform(built):
    leagues = built[1]["leagues"]
    assert leagues["hwh"]["league"]["appName"] == "Sleeper"
    assert leagues["hwh"]["league"]["appUrl"] == "https://sleeper.com/leagues/1389389185361653760/team"
    assert leagues["fantasizing"]["league"]["appName"] == "ESPN"
    assert leagues["fantasizing"]["league"]["appUrl"] == \
        "https://fantasy.espn.com/football/team?leagueId=125685129&teamId=14"


@needs_raw
def test_player_news_and_recent_weeks_are_well_formed(built):
    for k, o in built[1]["leagues"].items():
        for p in o["roster"]:
            assert p["newsUpdated"] is None or ISO_Z.match(p["newsUpdated"]), (k, p["name"])
            assert len(p["recent"]) <= 4
            weeks = [r["week"] for r in p["recent"]]
            assert weeks == sorted(weeks) and all(r["week"] < WEEK for r in p["recent"]), (k, p["name"])
            assert all(isinstance(r["pts"], float) for r in p["recent"]), (k, p["name"])


@needs_raw
def test_lineup_slots_carry_next_best_and_flagged_players_carry_backups(built):
    for k, o in built[1]["leagues"].items():
        rec_ids = {s["recommended"]["id"] for s in o["lineup"]["slots"] if s["recommended"]}
        for s in o["lineup"]["slots"]:
            nb = s["nextBest"]
            assert nb is None or nb["id"] not in rec_ids, k
        for w in o["lineup"]["watch"]:
            assert set(w) >= {"backup", "lateRisk"}, k
            assert isinstance(w["lateRisk"], bool), k
            if w["backup"]:
                assert set(w["backup"]) == {"id", "name", "points", "kickoff", "gain"}, k
        for a in o["lineup"]["alerts"]:
            assert "backup" in a, k


# ---- flagged starters from a fixed roster, so the test does not depend on the live week's injuries

HWH_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
NOON, LATE, SNF = "2026-11-22T18:00Z", "2026-11-22T21:05Z", "2026-11-23T01:20Z"


def P(pid, pos, pts, kick, status=None, flags=(), eligible=True, locked=False, notes=None):
    return {"id": pid, "name": pid.title(), "pos": pos, "points": pts, "eligible": eligible, "locked": locked,
            "status": status, "flags": list(flags), "injuryNotes": notes, "game": {"kickoff": kick}}


def hwh_roster(flex_kick=LATE, flex_status="QUESTIONABLE"):
    """Ten starters with a questionable WR in the first FLEX, plus a bench. The best FLEX backup is
    bench-rb (9.0, noon). A locked WR and an ineligible RB outscore it but cannot be swapped in."""
    starters = [P("qb", "QB", 20.0, NOON), P("rb1", "RB", 15.0, NOON), P("rb2", "RB", 13.0, LATE),
                P("wr1", "WR", 16.0, NOON), P("wr2", "WR", 14.0, LATE), P("te", "TE", 10.0, NOON),
                P("flex-wr", "WR", 12.0, flex_kick, status=flex_status, flags=["Q"], notes="Ankle"),
                P("flex-rb", "RB", 11.0, NOON), P("k", "K", 8.0, NOON), P("def", "DEF", 7.0, NOON)]
    bench = [P("bench-rb", "RB", 9.0, NOON), P("bench-wr", "WR", 6.5, LATE),
             P("locked-wr", "WR", 10.5, NOON, locked=True), P("out-rb", "RB", 9.5, LATE, eligible=False),
             P("bench-qb", "QB", 18.0, NOON)]
    return starters, starters + bench


def test_questionable_flex_starter_gets_a_watch_entry_with_the_best_backup():
    starters, roster = hwh_roster()
    alerts, watch = bd.flagged_starters(HWH_SLOTS, [p["id"] for p in starters], roster)
    assert alerts == []
    assert len(watch) == 1
    w = watch[0]
    assert (w["player"], w["slot"], w["kickoff"], w["injuryNotes"]) == ("Flex-Wr", "FLEX", LATE, "Ankle")
    assert w["backup"] == {"id": "bench-rb", "name": "Bench-Rb", "points": 9.0, "kickoff": NOON, "gain": -3.0}, \
        "locked and ineligible players are skipped, QB does not fit FLEX, gain is backup minus flagged points"
    assert w["lateRisk"] is False, "bench-wr kicks off at the same time, so a late swap is still possible"


def test_questionable_flex_is_late_risk_when_it_kicks_off_after_every_backup():
    starters, roster = hwh_roster(flex_kick=SNF)
    _, watch = bd.flagged_starters(HWH_SLOTS, [p["id"] for p in starters], roster)
    assert watch[0]["backup"]["id"] == "bench-rb"
    assert watch[0]["lateRisk"] is True


def test_questionable_flex_with_no_eligible_backup_has_null_backup_and_no_late_risk():
    starters, roster = hwh_roster(flex_kick=SNF)
    roster = [p for p in roster if p["id"] not in ("bench-rb", "bench-wr")]
    _, watch = bd.flagged_starters(HWH_SLOTS, [p["id"] for p in starters], roster)
    assert watch[0]["backup"] is None and watch[0]["lateRisk"] is False


def test_out_starter_is_an_alert_with_backup_gain_from_zero():
    starters, roster = hwh_roster(flex_status="OUT")
    starters[6]["flags"] = ["OUT"]
    alerts, watch = bd.flagged_starters(HWH_SLOTS, [p["id"] for p in starters], roster)
    assert watch == []
    assert alerts == [{"player": "Flex-Wr", "slot": "FLEX", "flags": ["OUT"],
                       "backup": {"id": "bench-rb", "name": "Bench-Rb", "points": 9.0, "kickoff": NOON, "gain": 9.0}}]


@needs_raw
def test_meta_has_next_refresh_after_generated_at(built):
    meta = built[1]["meta"]
    assert ISO_Z.match(meta["nextRefresh"]) and meta["nextRefresh"] > meta["generatedAt"]
