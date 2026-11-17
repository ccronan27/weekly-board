from pipeline import players as pl

P = {
    "1": {"name": "Aaron Jones", "pos": "RB", "team": "MIN", "active": True},
    "2": {"name": "Aaron Jones", "pos": "RB", "team": "GB", "active": False},
    "3": {"name": "Marvin Harrison", "pos": "WR", "team": "ARI", "active": True},
    "4": {"name": "Marvin Harrison", "pos": "WR", "team": None, "active": False},
    "5": {"name": "Jaxon Smith-Njigba", "pos": "WR", "team": "SEA", "active": True},
    "6": {"name": "Hunter Smith", "pos": "RB", "team": "DAL", "active": True},
    "SEA": {"name": "Seattle Seahawks", "pos": "DEF", "team": "SEA", "active": True},
}


def m(name, pos, team):
    return pl.match_one(name, pos, team, P, pl.index_sleeper(P))


def test_suffix_punctuation_and_team_tiebreak():
    assert m("Aaron Jones Sr.", "RB", "MIN") == "1"
    assert m("Aaron Jones", "RB", "GB") == "2"
    assert m("Jaxon Smith-Njigba", "WR", "SEA") == "5"
    assert m("Marvin Harrison Jr.", "WR", "ARI") == "3"


def test_ambiguous_without_team_prefers_active_and_never_guesses_when_tied():
    assert m("Aaron Jones", "RB", "NYJ") == "1", "one active candidate wins when team does not match"
    P2 = dict(P, **{"7": {"name": "Aaron Jones", "pos": "RB", "team": "DAL", "active": True}})
    assert pl.match_one("Aaron Jones", "RB", "NYJ", P2, pl.index_sleeper(P2)) is None


def test_defense_matches_by_team_code():
    assert m("Seahawks D/ST", "D/ST", "SEA") == "SEA" and m("X D/ST", "DEF", "XXX") is None


def test_position_mismatch_falls_back_to_same_team_name():
    assert m("Hunter Smith", "WR", "DAL") == "6"
    assert m("Hunter Smith", "WR", "KC") is None


def test_resolve_keeps_existing_ids_and_reports_unmatched():
    entries = [{"espnId": 10, "name": "Aaron Jones", "pos": "RB", "team": "MIN"},
               {"espnId": 11, "name": "Nobody Here", "pos": "WR", "team": "MIN"},
               {"espnId": 12, "name": "Aaron Jones", "pos": "RB", "team": "MIN"}]
    out, unmatched = pl.resolve_espn(entries, P, {12: "2", 99: "5"})
    assert out[10] == "1" and out[12] == "2" and out[99] == "5"
    assert [e["espnId"] for e in unmatched] == [11]
