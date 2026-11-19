"""P1 fields on a fresh build from the cached raw pull: league links, player news and recent weeks,
lineup context (next best, backups, late risk) and the next refresh time."""
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


@needs_raw
def test_hwh_questionable_flex_has_a_backup_and_meta_has_next_refresh(built):
    out, res = built
    hwh = res["leagues"]["hwh"]["lineup"]
    watch = [w for w in hwh["watch"] if w["player"] == "Ladd McConkey"]
    assert watch and watch[0]["backup"] is not None, "Ladd McConkey is questionable in HWH"
    meta = res["meta"]
    assert ISO_Z.match(meta["nextRefresh"]) and meta["nextRefresh"] > meta["generatedAt"]
