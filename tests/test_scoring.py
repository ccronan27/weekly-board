import pytest

from pipeline import scoring, statmap
from pipeline.adapters import espn_defaults as ed
from pipeline.adapters import espn_rosters, sleeper
from pipeline.scoring import League, Support, project_player


def L(scoring_, platform="sleeper", **kw):
    return League(key="t", name="t", platform=platform, scoring=scoring_, starters=[], **kw)


# ---- ESPN native scoring is exact ----

def test_espn_native_equals_applied_total_on_fixture(load):
    lg = scoring.league_from_espn("fantasizing", espn_rosters.load())
    players = [p for p in ed.normalize(load("espn_defaults.json"), 2026, 11) if p["projection"]]
    assert {p["pos"] for p in players} >= {"QB", "RB", "WR", "TE", "K", "DEF"}
    for p in players:
        pts = lg.espn_dst_points if p["pos"] == "DEF" else lg.espn_points
        got = scoring.score_espn_native(p["projection"]["stats"], pts)
        assert got == pytest.approx(p["projection"]["appliedTotal"], abs=1e-5), p["name"]


def test_dst_overrides_apply_to_dst_only():
    lg = scoring.league_from_espn("fantasizing", espn_rosters.load())
    raw = {"95": 1.0}   # one interception
    assert scoring.score_espn_native(raw, lg.espn_points) == 0.0, "a WR's interception is not scored"
    assert scoring.score_espn_native(raw, lg.espn_dst_points) == 2.0


def test_espn_league_canonical_scoring():
    lg = scoring.league_from_espn("fantasizing", espn_rosters.load())
    s = lg.scoring
    assert s["rec"] == 1.0 and s["pass_yd"] == 0.04 and s["rush_yd"] == 0.1 and s["rec_td"] == 6
    assert s["fgm_0_19"] == s["fgm_20_29"] == s["fgm_30_39"] == 3 and s["fgm_40_49"] == 4 and s["fgm_50_59"] == 5
    assert s["def_td"] == 6, "ids 103 and 104 both feed def_td and must not be summed"
    assert s["sack"] == 1 and s["espn_pa_0"] == 5
    assert lg.starters == ["QB", "RB", "WR", "WR", "TE", "FLEX", "FLEX", "K", "DEF"]
    assert any("no Rotowire equivalent" in n for n in lg.notes)


def test_sleeper_league_from_fixture(load):
    norm = sleeper.normalize_league(load("sleeper_league.json"), load("sleeper_rosters.json"), load("sleeper_users.json"), None)
    lg = scoring.league_from_sleeper("hwh", norm, overrides={})
    assert lg.scoring["rec"] == 1.0 and lg.scoring["pass_td"] == 4.0
    assert "BN" not in lg.starters and lg.slot_counts["FLEX"] == 2 and lg.slot_counts["K"] == 1
    lg2 = scoring.league_from_sleeper("hwh", norm, overrides={"scoring": {"rec": 0.5}})
    assert lg2.scoring["rec"] == 0.5


# ---- canonical stat conversion ----

def test_te_premium_applies_to_te_only_in_both_sources():
    chi = L({"rec": 0.5, "rec_yd": 0.1, "bonus_rec_te": 0.5})
    rw_te = {"rec": 5, "rec_yd": 50, "bonus_rec_te": 5}                 # Rotowire gives bonus_rec_te itself
    es_te = {"53": 5, "42": 50}                                          # ESPN does not, we derive it
    assert scoring.score(scoring.rotowire_to_canon(rw_te, "TE"), chi.scoring) == pytest.approx(10.0)
    assert scoring.score(statmap.espn_to_canon(es_te, "TE"), chi.scoring) == pytest.approx(10.0)
    assert scoring.score(statmap.espn_to_canon(es_te, "WR"), chi.scoring) == pytest.approx(7.5)


def test_espn_offense_mapping_matches_default_ppr():
    raw = {"3": 250, "4": 2, "20": 1, "24": 30, "25": 1, "72": 1, "53": 0}
    ppr = L({"pass_yd": 0.04, "pass_td": 4, "pass_int": -1, "rush_yd": 0.1, "rush_td": 6, "fum_lost": -2})
    assert scoring.score(statmap.espn_to_canon(raw, "QB"), ppr.scoring) == pytest.approx(10 + 8 - 1 + 3 + 6 - 2)


def test_k_rotowire_derivations():
    s = scoring.rotowire_to_canon({"fga": 3.0, "fgm": 2.0, "fgm_20_29": 1.0, "fgm_40_49": 0.5, "fgm_50p": 0.5,
                                   "fgmiss_40_49": 0.5, "fgmiss_50p": 0.25, "xpm": 2, "xpmiss": 0}, "K")
    assert s["fgm_50_59"] == 0.5 and s["fgmiss"] == pytest.approx(1.0)
    assert s["fgmiss_20_29"] == pytest.approx(0.25), "misses not accounted for at 30+ are short misses"
    chi = L({"fgm_20_29": 3, "fgm_40_49": 4, "fgm_50_59": 6, "fgmiss_20_29": -3, "fgmiss_40_49": -1, "xpm": 1, "xpmiss": -3})
    assert scoring.score(s, chi.scoring) == pytest.approx(3 + 2 + 3 - 0.75 - 0.5 + 2)
    hwh = L({"fgmiss": -1, "fgm_20_29": 3})
    assert scoring.score(s, hwh.scoring) == pytest.approx(3 - 1.0)


def test_k_espn_zero_to_39_bucket_is_split_evenly():
    s = statmap.espn_to_canon({"80": 2.0, "82": 1.0, "77": 1.0}, "K")
    assert s["fgm_20_29"] == s["fgm_30_39"] == 1.0 and s["fgmiss_20_29"] == s["fgmiss_30_39"] == 0.5
    assert s["fgm_40_49"] == 1.0


def test_def_points_allowed_bucket_conversion():
    s = statmap.espn_to_canon({"121": 1.0}, "DEF")           # ESPN 18-21
    assert s["pts_allow_14_20"] == 0.75 and s["pts_allow_21_27"] == 0.25 and s["espn_pa_18_21"] == 1.0
    s = statmap.espn_to_canon({"124": 0.5, "125": 0.25}, "DEF")
    assert s["pts_allow_35p"] == 0.75


def test_rotowire_def_buckets_from_numbers():
    s = scoring.rotowire_to_canon({"pts_allow": 21.0, "yds_allow": 342.0}, "DEF")
    assert s["pts_allow_21_27"] == 1.0 and s["espn_pa_18_21"] == 1.0 and s["yds_allow_300_349"] == 1.0
    s = scoring.rotowire_to_canon({"pts_allow": 16.0, "pts_allow_14_20": 1.0}, "DEF")
    assert s["espn_pa_14_17"] == 1.0 and s["pts_allow_14_20"] == 1.0


# ---- blending: equal average, gap filling ----

SUP = Support(rotowire={"RB": {"rush_yd", "rush_td"}}, espn={"RB": {"rush_yd", "rush_td", "rush_td_50p"}})


def test_equal_average_of_two_sources():
    lg = L({"rush_yd": 0.1, "rush_td": 6})
    out = project_player(lg, "RB", {"rush_yd": 100, "rush_td": 1}, {"24": 60, "25": 0.5}, SUP)
    assert out["rotowire"] == pytest.approx(16.0) and out["espn"] == pytest.approx(9.0)
    assert out["points"] == pytest.approx(12.5) and out["sources"] == ["espn", "rotowire"]


def test_single_source_is_used_as_is():
    lg = L({"rush_yd": 0.1})
    assert project_player(lg, "RB", {"rush_yd": 100}, None, SUP)["points"] == pytest.approx(10.0)
    out = project_player(lg, "RB", None, {"24": 50}, SUP)
    assert out["points"] == pytest.approx(5.0) and out["sources"] == ["espn"]
    assert project_player(lg, "RB", None, None, SUP)["points"] is None


def test_gap_fill_only_for_stats_a_source_never_projects():
    chi = L({"rush_yd": 0.1, "rush_td_50p": 1.0})
    out = project_player(chi, "RB", {"rush_yd": 100}, {"24": 100, "36": 0.1}, SUP)
    assert out["rotowire"] == pytest.approx(10.1), "Rotowire never projects rush_td_50p, so it takes ESPN's value"
    assert out["espn"] == pytest.approx(10.1) and out["filled"] == ["rotowire:rush_td_50p"]
    both = Support(rotowire={"RB": {"rush_yd", "rush_td_50p"}}, espn={"RB": {"rush_yd", "rush_td_50p"}})
    out = project_player(chi, "RB", {"rush_yd": 100}, {"24": 100, "36": 0.1}, both)
    assert out["rotowire"] == pytest.approx(10.0) and out["filled"] == [], "a source that supports the stat keeps its own (zero)"


def test_espn_league_uses_native_scoring_for_espn_source():
    lg = scoring.league_from_espn("fantasizing", espn_rosters.load())
    sup = Support(rotowire={"WR": {"rec", "rec_yd"}}, espn={"WR": {"rec", "rec_yd"}})
    out = project_player(lg, "WR", {"rec": 6, "rec_yd": 80}, {"53": 6, "42": 80, "101": 0.1}, sup)
    assert out["espn"] == pytest.approx(6 + 8 + 0.6), "native scoring includes return TDs (id 101)"
    assert out["rotowire"] == pytest.approx(14.0)


# ---- volatility ----

def test_floor_ceiling_from_weekly_sd():
    import statistics
    weekly = [10.0, 20.0, 15.0, 5.0]
    sd = statistics.stdev(weekly)
    fc = scoring.floor_ceiling(14.0, weekly)
    assert fc["sd"] == round(sd, 2) and fc["floor"] == round(14 - sd, 1) and fc["ceiling"] == round(14 + sd, 1) and fc["games"] == 4


def test_floor_clamped_at_zero_and_needs_three_games():
    assert scoring.floor_ceiling(3.0, [0.0, 20.0, 1.0])["floor"] == 0.0
    assert scoring.floor_ceiling(14.0, [10.0, 20.0]) == {"sd": None, "floor": None, "ceiling": None, "games": 2}
    assert scoring.floor_ceiling(None, [1, 2, 3])["sd"] is None


def test_weekly_points_skips_games_not_played():
    lg = L({"rec": 1.0})
    pts = scoring.weekly_points(lg, "WR", {"1": {"rec": 5, "gp": 1}, "2": {"rec": 9, "gp": 0}, "3": {"rec": 3, "gp": 1}})
    assert pts == [5.0, 3.0]
