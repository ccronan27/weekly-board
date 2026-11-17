import pytest

from pipeline.adapters import nflverse_lines as nv
from pipeline.common import ContractError


def test_normalize_week(load):
    rows = nv.parse(load("nflverse_games.csv"))
    games = nv.normalize(rows, 2026, 11)
    assert games and all(g["week"] == 11 for g in games)
    g = next(g for g in games if g["homeSpread"] is not None)
    assert g["impliedHome"] + g["impliedAway"] == pytest.approx(g["total"])
    assert g["impliedHome"] - g["impliedAway"] == pytest.approx(g["homeSpread"])
    assert "LA" not in {t for g in games for t in (g["home"], g["away"])}, "LA must be mapped to LAR"


def test_implied_totals_formula():
    text = "game_id,season,game_type,week,gameday,gametime,away_team,home_team,spread_line,total_line\n" \
           "2026_11_LA_SEA,2026,REG,11,2026-11-22,16:25,LA,SEA,3,45\n" \
           "2026_11_X_Y,2026,REG,11,2026-11-22,13:00,AAA,BBB,,\n"
    g = nv.normalize(nv.parse(text), 2026, 11)
    assert (g[0]["impliedHome"], g[0]["impliedAway"]) == (24.0, 21.0)
    assert g[0]["away"] == "LAR"
    assert g[1]["impliedHome"] is None and g[1]["homeSpread"] is None


def test_missing_column_fails(load):
    text = load("nflverse_games.csv").replace("spread_line", "spread")
    with pytest.raises(ContractError, match="spread_line"):
        nv.validate(nv.parse(text))


def test_no_rows_for_season_fails(load):
    with pytest.raises(ContractError, match="season 2031"):
        nv.validate(nv.parse(load("nflverse_games.csv")), season=2031)


def test_empty_file_fails():
    with pytest.raises(ContractError):
        nv.validate([])
