"""Contract for data/espn/rosters.json, the file written by the espn-roster-sync skill."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from pipeline.adapters import espn_rosters as er
from pipeline.common import ContractError


@pytest.fixture
def real():
    return json.loads(er.PATH.read_text(encoding="utf-8"))


def test_committed_file_passes_contract():
    d = er.load()
    assert d["platform"] == "espn" and len(d["teams"]) == d["settings"]["teams"]


def test_no_network_imports():
    import inspect
    src = inspect.getsource(er)
    assert "requests" not in src and "http" not in src.replace("https", "").split("import")[0]


@pytest.mark.parametrize("key", ["syncedAt", "settings", "teams", "week", "season"])
def test_missing_top_key_fails(real, key):
    del real[key]
    with pytest.raises(ContractError, match=key):
        er.validate(real)


def test_failed_sync_fails(real):
    real["ok"] = False
    with pytest.raises(ContractError, match="sync failed"):
        er.validate(real)


def test_owner_fields_are_rejected(real):
    real["teams"][0]["ownerName"] = "Some Person"
    with pytest.raises(ContractError, match="owner"):
        er.validate(real)


def test_unknown_slot_fails(real):
    real["teams"][0]["roster"][0]["slot"] = "SUPERFLEX"
    with pytest.raises(ContractError, match="slot"):
        er.validate(real)


def test_player_field_rename_fails(real):
    p = real["teams"][0]["roster"][0]
    p["status"] = p.pop("injuryStatus")
    with pytest.raises(ContractError, match="injuryStatus"):
        er.validate(real)


def test_team_count_mismatch_fails(real):
    real["teams"].pop()
    with pytest.raises(ContractError, match="teams"):
        er.validate(real)


def test_staleness_after_four_days(real):
    now = er.parse_synced_at(real["syncedAt"])
    assert not er.is_stale(real, now + timedelta(days=3, hours=23))
    assert er.is_stale(real, now + timedelta(days=4, hours=1))


def test_bad_timestamp_fails(real):
    real["syncedAt"] = "yesterday"
    with pytest.raises(ContractError, match="syncedAt"):
        er.validate(real)
