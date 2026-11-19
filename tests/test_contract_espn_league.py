"""Contract for the public ESPN league endpoint (pipeline/adapters/espn_league.py). Fixtures are trimmed
real responses with owner data removed (scripts/record_fixtures.py)."""
import copy
import json
from pathlib import Path

import pytest

from pipeline.adapters import espn_league as el, espn_rosters as er
from pipeline.common import ContractError

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def league():
    return json.loads((FIX / "espn_league.json").read_text(encoding="utf-8"))


@pytest.fixture
def week():
    return json.loads((FIX / "espn_league_week.json").read_text(encoding="utf-8"))


def test_normalized_league_meets_the_roster_file_contract(league):
    d = el.normalize_league(league)
    er.validate(d)   # the same contract the sync skill's file meets
    assert d["platform"] == "espn" and d["source"] == "espn_public_api"
    assert d["settings"]["playoffWeekStart"] == league["settings"]["scheduleSettings"]["matchupPeriodCount"] + 1
    assert set(d["settings"]["dstScoringByStatId"]) == set(d["settings"]["scoringByStatId"])
    assert {r["teamId"] for r in d["standings"]} == {t["teamId"] for t in d["teams"]}
    assert all(p["slot"] in er.SLOTS for t in d["teams"] for p in t["roster"])


def test_owner_data_is_never_kept(league):
    league = copy.deepcopy(league)
    league["members"] = [{"id": "x", "firstName": "Real", "lastName": "Person", "displayName": "handle"}]
    for t in league["teams"]:
        t["owners"] = ["{X}"]
        t["primaryOwner"] = "{X}"
    text = json.dumps(el.normalize_league(league))
    for bad in ("Real", "Person", "handle", "{X}", "owners", "members"):
        assert bad not in text


def test_finished_games_carry_scores(league):
    d = el.normalize_league(league)
    done = [g for g in league["schedule"] if g["winner"] != "UNDECIDED" and g.get("away")]
    rows = [g for g in d["schedule"] if "homePoints" in g]
    assert len(rows) == len(done)
    assert all("homePoints" not in g for g in d["schedule"] if g["week"] >= league["scoringPeriodId"])


@pytest.mark.parametrize("key", ["settings", "teams", "schedule", "scoringPeriodId"])
def test_missing_top_key_fails(league, key):
    del league[key]
    with pytest.raises(ContractError, match=key):
        el.normalize_league(league)


def test_unknown_slot_fails(league):
    league["teams"][0]["roster"]["entries"][0]["lineupSlotId"] = 99
    with pytest.raises(ContractError, match="lineupSlotId"):
        el.normalize_league(league)


def test_week_lineups(week):
    w = week["scoringPeriodId"]
    rows = el.normalize_week(week, w)
    assert len(rows) == 2
    for t in rows:
        assert t["starters"] and all(s["slot"] not in ("BN", "IR") for s in t["starters"])
        assert all(isinstance(s["points"], float) for s in t["starters"])


def test_week_mismatch_fails(week):
    with pytest.raises(ContractError, match="asked for week"):
        el.normalize_week(week, week["scoringPeriodId"] + 1)


def test_week_without_lineups_fails(week):
    del week["schedule"][0]["home"]["rosterForCurrentScoringPeriod"]
    with pytest.raises(ContractError, match="no lineup"):
        el.normalize_week(week, week["scoringPeriodId"])
