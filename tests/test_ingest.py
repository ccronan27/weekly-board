"""Ingest behavior: failures are isolated, caches survive, rosters never touch the network."""
import json
from pathlib import Path

import pytest

from pipeline import ingest
from pipeline.common import ContractError, read_json


def test_failed_source_keeps_old_cache_and_marks_stale(tmp_path):
    status = {}
    ingest._run_source(status, tmp_path, 2026, 11, "src", lambda: {"v": 1})
    first = status["src"]["lastUpdated"]
    assert status["src"]["ok"] and not status["src"]["stale"]

    def boom():
        raise ContractError("shape changed")
    ingest._run_source(status, tmp_path, 2026, 11, "src", boom)
    assert status["src"]["stale"] and not status["src"]["ok"]
    assert status["src"]["lastUpdated"] == first, "stale source keeps the time of the last good pull"
    assert "contract" in status["src"]["error"]
    assert read_json(tmp_path / "2026/11/src.json")["data"] == {"v": 1}


def test_failed_source_with_no_cache_is_missing(tmp_path):
    status = {}
    ingest._run_source(status, tmp_path, 2026, 11, "src", lambda: 1 / 0)
    assert status["src"]["lastUpdated"] is None and status["src"]["stale"]


def test_run_survives_every_network_source_failing(tmp_path, monkeypatch):
    from pipeline.adapters import espn_defaults, nflverse_lines, sleeper

    def fail(*a, **k):
        raise ConnectionError("offline")
    for mod, names in ((sleeper, ["fetch_league", "fetch_rosters", "fetch_users", "fetch_matchups", "fetch_players", "fetch_projections", "fetch_stats"]),
                       (espn_defaults, ["fetch"]), (nflverse_lines, ["fetch"])):
        for n in names:
            monkeypatch.setattr(mod, n, fail)
    out = ingest.run(2026, 11, root=tmp_path)
    assert out["sources"]["espn_rosters"]["ok"], "rosters come from the committed file"
    assert not out["sources"]["sleeper_projections"]["ok"]
    assert (tmp_path / "2026/11/status.json").exists()
    assert ingest.main.__name__ == "main"


def test_rosters_adapter_makes_no_network_calls(monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: pytest.fail("network call from espn_rosters"))
    from pipeline.adapters import espn_rosters
    espn_rosters.load()


# ---- hard rules from CLAUDE.md, enforced on the repo itself ----

REPO = Path(__file__).resolve().parent.parent


def _text_files():
    for base in ("pipeline", "scripts", ".github", "config"):
        for p in (REPO / base).rglob("*"):
            if p.is_file() and p.suffix in {".py", ".yml", ".yaml", ".js", ".html", ".json", ".md"}:
                yield p


def test_no_espn_league_endpoints_or_credentials():
    banned = ["swid", "espn_s2", "espn-s2", "cookie", "/leagues/125685129", "apis/v3/games/ffl/seasons/{season}/segments/0/leagues/"]
    for p in _text_files():
        t = p.read_text(encoding="utf-8").lower()
        for b in banned:
            assert b not in t, f"{p.relative_to(REPO)} contains banned term {b!r}"


def test_espn_calls_only_leaguedefaults():
    # Calls: only leaguedefaults. Links: the public team page a viewer opens (league.appUrl), never fetched
    import re
    for p in _text_files():
        for m in re.finditer(r"fantasy\.espn\.com[^\s\"']*", p.read_text(encoding="utf-8")):
            assert "leaguedefaults" in m.group(0) or m.group(0).startswith("fantasy.espn.com/football/team?"), \
                f"{p.relative_to(REPO)}: {m.group(0)}"
