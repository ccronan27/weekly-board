"""The state machines in docs/STATES.md: source freshness, the ESPN roster fallback, season phase,
and the site's routing, trade loading and clock-based staleness."""
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import build as bd, ingest
from pipeline.common import DATA, RAW, ROOT, read_json, source_state, source_status

ROSTERS = DATA / "espn" / "rosters.json"
SEASON, WEEK = 2026, 11
HAVE_RAW = (RAW / str(SEASON) / str(WEEK) / "status.json").exists()
NODE = shutil.which("node")


# ---------------------------------------------------------------- source freshness

def test_source_status_states():
    assert source_status(True, "2026-11-18T00:00:00Z")["state"] == "fresh"
    assert source_status(False, "2026-11-18T00:00:00Z", "boom")["state"] == "stale"
    assert source_status(True, "2026-11-18T00:00:00Z", stale=True)["state"] == "stale"
    assert source_status(False, None, "boom")["state"] == "missing"


def test_source_state_reads_entries_written_before_state_existed():
    assert source_state({"ok": True, "stale": False, "lastUpdated": "x"}) == "fresh"
    assert source_state({"ok": True, "stale": True, "lastUpdated": "x"}) == "stale"   # old ESPN sync
    assert source_state({"ok": False, "stale": True, "lastUpdated": "x"}) == "stale"
    assert source_state({"ok": False, "stale": True, "lastUpdated": None}) == "missing"


def test_run_source_writes_state(tmp_path):
    status = {}
    ingest._run_source(status, tmp_path, SEASON, WEEK, "src", lambda: 1 / 0)
    assert status["src"]["state"] == "missing"
    ingest._run_source(status, tmp_path, SEASON, WEEK, "src", lambda: {"v": 1})
    assert status["src"]["state"] == "fresh"
    ingest._run_source(status, tmp_path, SEASON, WEEK, "src", lambda: 1 / 0)
    assert status["src"]["state"] == "stale"


# ---------------------------------------------------------------- ESPN roster fallback

def _bad_rosters(tmp_path):
    d = read_json(ROSTERS)
    d["ok"] = False    # what the sync skill writes when it fails
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(d))
    return f


def _cache(root, week=WEEK - 1):
    d = read_json(ROSTERS)
    p = root / str(SEASON) / str(week) / "espn_rosters.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"source": "espn_rosters", "fetchedAt": d["syncedAt"], "data": d}))
    return d


def test_load_rosters_good_file(tmp_path):
    r, err = ingest.load_rosters(tmp_path, SEASON, WEEK)
    assert r["ok"] is True and err is None
    st = ingest.rosters_status(r, err, r["week"], now=ingest.espn_rosters.parse_synced_at(r["syncedAt"]))
    assert st["state"] == "fresh"


def test_load_rosters_falls_back_to_newest_cached_copy(tmp_path):
    good = _cache(tmp_path)
    r, err = ingest.load_rosters(tmp_path, SEASON, WEEK, _bad_rosters(tmp_path))
    assert r == good and "ok is not true" in err
    st = ingest.rosters_status(r, err, WEEK)
    assert st["state"] == "stale" and st["lastUpdated"] == good["syncedAt"] and "last good sync" in st["error"]


def test_load_rosters_skips_a_broken_cache(tmp_path):
    good = _cache(tmp_path, WEEK - 2)
    broken = tmp_path / str(SEASON) / str(WEEK) / "espn_rosters.json"
    broken.parent.mkdir(parents=True)
    broken.write_text('{"data": {"ok": false}}')
    assert ingest.load_rosters(tmp_path, SEASON, WEEK, _bad_rosters(tmp_path))[0] == good


def test_load_rosters_with_nothing_usable_is_missing(tmp_path):
    r, err = ingest.load_rosters(tmp_path, SEASON, WEEK, tmp_path / "nope.json")
    assert r is None and err
    assert ingest.rosters_status(r, err, WEEK)["state"] == "missing"


def test_old_sync_is_stale_and_week_mismatch_is_reported():
    r = read_json(ROSTERS)
    later = ingest.espn_rosters.parse_synced_at(r["syncedAt"]) + timedelta(days=5)
    st = ingest.rosters_status(r, None, r["week"] + 1, now=later)
    assert st["state"] == "stale" and st["ok"] and "for week" in st["error"]


def test_ingest_caches_a_good_roster_file(tmp_path, monkeypatch):
    from pipeline.adapters import espn_defaults, nflverse_lines, sleeper

    def fail(*a, **k):
        raise ConnectionError("offline")
    for mod, names in ((sleeper, ["fetch_league", "fetch_rosters", "fetch_users", "fetch_matchups", "fetch_players", "fetch_projections", "fetch_stats"]),
                       (espn_defaults, ["fetch"]), (nflverse_lines, ["fetch"])):
        for n in names:
            monkeypatch.setattr(mod, n, fail)
    out = ingest.run(SEASON, WEEK, root=tmp_path)
    cached = read_json(tmp_path / str(SEASON) / str(WEEK) / "espn_rosters.json")
    assert cached["data"] == read_json(ROSTERS)
    assert {s["state"] for s in out["sources"].values()} <= {"fresh", "stale", "missing"}
    assert out["sources"]["sleeper_projections"]["state"] == "missing"


LOCK_NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


@pytest.mark.skipif(not HAVE_RAW, reason="no cached raw data")
def test_build_publishes_with_last_good_rosters_when_the_sync_fails(tmp_path):
    raw = tmp_path / "raw"
    shutil.copytree(RAW / str(SEASON), raw / str(SEASON))
    good = _cache(raw)
    res = bd.build(SEASON, WEEK, raw_root=raw, out_dir=tmp_path / "out", save_idmap=False, now=LOCK_NOW,
                   rosters_path=_bad_rosters(tmp_path))
    assert set(res["leagues"]) == {"fantasizing", "hwh", "chicago-dynasty"}
    er = res["meta"]["espnRosters"]
    assert er["fromCache"] is True and er["state"] == "stale" and er["syncedAt"] == good["syncedAt"]
    assert res["leagues"]["fantasizing"]["sources"]["espn_rosters"]["state"] == "stale"


@pytest.mark.skipif(not HAVE_RAW, reason="no cached raw data")
def test_build_publishes_sleeper_leagues_with_no_usable_rosters(tmp_path):
    raw = tmp_path / "raw"
    shutil.copytree(RAW / str(SEASON), raw / str(SEASON))
    for p in raw.rglob("espn_rosters.json"):
        p.unlink()
    out = tmp_path / "out"
    res = bd.build(SEASON, WEEK, raw_root=raw, out_dir=out, save_idmap=False, now=LOCK_NOW,
                   rosters_path=_bad_rosters(tmp_path))
    assert set(res["leagues"]) == {"hwh", "chicago-dynasty"}
    assert res["meta"]["skippedLeagues"][0]["key"] == "fantasizing"
    assert res["meta"]["espnRosters"]["state"] == "missing"
    assert not (out / "fantasizing.json").exists()


@pytest.mark.skipif(not HAVE_RAW, reason="no cached raw data")
def test_build_sources_all_carry_state(tmp_path):
    res = bd.build(SEASON, WEEK, out_dir=tmp_path, save_idmap=False, recommended_root=tmp_path / "rec", now=LOCK_NOW)
    assert all(s["state"] in ("fresh", "stale", "missing") for s in res["meta"]["sources"].values())
    assert res["meta"]["espnRosters"]["fromCache"] is False and res["meta"]["espnRosters"]["staleAfterDays"] == 4
    assert res["meta"]["skippedLeagues"] == []
    assert {o["seasonPhase"] for o in res["leagues"].values()} == {"regular"}


# ---------------------------------------------------------------- season phase

def test_season_phase():
    pw = [15, 16, 17]
    assert [bd.season_phase(w, pw) for w in (1, 14, 15, 17, 18)] == ["regular", "regular", "playoffs", "playoffs", "over"]


# ---------------------------------------------------------------- site (node runs the pure functions in app.js)

def _node(js: str):
    app = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
    assert app.endswith("\nmain();\n")
    src = app[: -len("main();\n")] + js
    out = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


needs_node = pytest.mark.skipif(not NODE, reason="needs node")

LEAGUES_JS = """
const L = [
  {league: {key: "a"}, waivers: {}, trade: {file: "t.json"}, standings: null},
  {league: {key: "b"}, waivers: null},
];
"""


@needs_node
def test_site_routes():
    got = _node(LEAGUES_JS + """
console.log(JSON.stringify({
  viewsA: viewsFor(L[0]).map(v => v[0]), viewsB: viewsFor(L[1]).map(v => v[0]),
  r1: routeFromHash("#a/trade", L), r2: routeFromHash("#b/trade", L), r3: routeFromHash("#zzz/waivers", L),
  r4: routeFromHash("", L), r5: routeFromHash("#a/nonsense", L),
  h1: hashFor(L[0], "lineup"), h2: hashFor(L[0], "standings"),
}));""")
    assert got["viewsA"] == ["lineup", "waivers", "trade", "standings"]
    assert got["viewsB"] == ["lineup"], "a view the build does not carry is not offered"
    assert got["r1"] == {"league": 0, "view": "trade"}
    assert got["r2"] == {"league": 1, "view": "lineup"}
    assert got["r3"] == {"league": 0, "view": "waivers"}
    assert got["r4"] == got["r5"] == {"league": 0, "view": "lineup"}
    assert (got["h1"], got["h2"]) == ("#a", "#a/standings")


@needs_node
def test_site_trade_load_states():
    got = _node("""
let calls = 0, mode = "fail";
global.fetch = async () => { calls++; if (mode === "fail") return {ok: false, status: 404}; return {ok: true, json: async () => ({ideas: []})}; };
const store = {}, seen = [], lg = {league: {key: "a"}, trade: {file: "t.json"}};
(async () => {
  let t = loadTrade(store, lg, () => seen.push(store.a.status));
  seen.push(t.status);
  await new Promise(r => setTimeout(r, 10));
  mode = "ok";
  loadTrade(store, lg, () => seen.push(store.a.status));   // what Try again does
  await new Promise(r => setTimeout(r, 10));
  console.log(JSON.stringify({seen, calls, ready: !!store.a.data}));
})();""")
    assert got == {"seen": ["loading", "error", "ready"], "calls": 2, "ready": True}


@needs_node
def test_site_freshness_follows_the_clock():
    got = _node("""
const iso = t => new Date(t).toISOString();
const built = Date.parse("2026-11-18T13:00:00Z");
const meta = {generatedAt: iso(built), espnRosters: {syncedAt: iso(built), stale: false, staleAfterDays: 4, week: 11, weekMismatch: false}};
const espn = {league: {platform: "espn"}, sources: {
  espn_rosters: {ok: true, stale: false, lastUpdated: iso(built), state: "fresh"},
  nflverse_lines: {ok: false, stale: true, lastUpdated: iso(built)},
  espn_defaults: {ok: false, stale: true, lastUpdated: null}}};
const day = 86400000;
const cached = JSON.parse(JSON.stringify(meta)); cached.espnRosters.fromCache = true;
const skipped = JSON.parse(JSON.stringify(meta)); skipped.skippedLeagues = [{key: "fantasizing", name: "Fantasizing 2026", reason: "x"}];
const sleeper = {league: {platform: "sleeper"}, sources: {}};
console.log(JSON.stringify({
  now: freshnessMessages(espn, meta, built + day),
  later: freshnessMessages(espn, meta, built + 5 * day),
  cached: freshnessMessages(espn, cached, built + day),
  skipped: freshnessMessages(sleeper, skipped, built + day),
  rowNow: rowState("espn_rosters", espn.sources.espn_rosters, meta, built + day),
  rowLater: rowState("espn_rosters", espn.sources.espn_rosters, meta, built + 5 * day),
  legacy: [sourceState(espn.sources.nflverse_lines), sourceState(espn.sources.espn_defaults)],
  phases: [noFutureWeeks("playoffs"), noFutureWeeks("over"), noFutureWeeks("regular"), noFutureWeeks(undefined)],
}));""")
    assert got["now"] == ["Missing data: ESPN projections. Nothing has loaded from it yet.",
                          "Stale data: Vegas lines. Using the last good pull."]
    assert got["later"][0].startswith("This board was built 5 days ago")
    assert any("more than 4 days old" in m for m in got["later"]), "ESPN sync ages in the browser too"
    assert any("did not save a usable roster file" in m for m in got["cached"])
    assert got["skipped"][0].startswith("Fantasizing 2026 is not shown")
    assert (got["rowNow"], got["rowLater"]) == ("fresh", "stale")
    assert got["legacy"] == ["stale", "missing"]
    assert got["phases"] == ["Final week", "Over", "n/a", "Over"]
