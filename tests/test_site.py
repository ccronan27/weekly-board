"""Hard rules for the static site from CLAUDE.md."""
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"
SVG_NAMESPACE = 'xmlns="http://www.w3.org/2000/svg"'
# The Refresh button is a plain link to the workflow page. It loads nothing and holds no token.
# GitHub only shows Run workflow to signed-in users with write access.
REFRESH_URL = "https://github.com/ccronan27/weekly-board/actions/workflows/refresh.yml"


def test_noindex_and_robots():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<meta name="robots" content="[^"]*noindex', html)
    assert (SITE / "robots.txt").read_text().split() == ["User-agent:", "*", "Disallow:", "/"]


def test_no_em_dashes_anywhere_in_site():
    for p in SITE.iterdir():
        assert "—" not in p.read_text(encoding="utf-8"), p.name


def test_ui_copy_has_no_semicolons():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    for lit in re.findall(r'"(?:[^"\\\n]|\\.)*"', js):
        assert ";" not in lit, f"semicolon in UI string {lit}"
    html = re.sub(r"<(script|style)\b.*?</\1>|<[^>]+>", " ", (SITE / "index.html").read_text(encoding="utf-8"), flags=re.S)
    assert ";" not in html


def test_site_reads_only_data_build_and_loads_nothing_external():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    assert all(p.startswith("data/build/") for p in re.findall(r'"(data/[^"]*)"', js))
    for p in SITE.iterdir():
        # The SVG namespace is an identifier, not a request. icon.svg needs it to render as an image.
        text = p.read_text(encoding="utf-8").replace(SVG_NAMESPACE, "")
        if p.name == "index.html":
            text = text.replace(f'href="{REFRESH_URL}"', "", 1)
        assert not re.search(r"https?://", text), f"external URL in {p.name}"


def test_data_is_never_inserted_as_html():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js


def test_central_time_zone():
    assert 'timeZone: TZ' in (SITE / "app.js").read_text() and 'TZ = "America/Chicago"' in (SITE / "app.js").read_text()


def test_make_site_refuses_empty_build(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("make_site", REPO / "scripts" / "make_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    (tmp_path / "site").mkdir()
    (tmp_path / "data" / "build").mkdir(parents=True)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.main() == 1 and not (tmp_path / "_site").exists()


def test_app_reads_optional_fields():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    for name in ["watch", "locked", "injuryNotes", "weekMismatch"]:
        assert name in js, name


def test_position_colors_for_every_slot_in_light_and_dark():
    css = (SITE / "style.css").read_text(encoding="utf-8")
    light, dark = css.split("prefers-color-scheme", 1)
    for pos in ["qb", "rb", "wr", "te", "flex", "k", "def"]:
        assert f"--pos-{pos}-bg:" in light, pos
        assert f"--pos-{pos}-bg:" in dark, pos
        assert f".chip.pos-{pos}{{" in css, pos


def test_tabs_point_at_the_panel():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    assert 'setAttribute("aria-controls", "panel")' in js
    assert 'id="panel"' in (SITE / "index.html").read_text(encoding="utf-8")


def test_waivers_view_is_wired():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    for needle in ("renderWaivers", "league.waivers", "byPosition", "w.targets", "w.drop", '"/" + view',
                   "longTerm", "horizonSection", "rateFrom", "w.stretch", "stretchGain"):
        assert needle in js, needle


def test_trade_view_is_wired():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    for needle in ("renderTrade", "league.trade", "bestTotal", "tradeResult", "td.ideas", "youthFlag", '"trade", "Trade"'):
        assert needle in js, needle


def test_standings_view_is_wired():
    js = (SITE / "app.js").read_text(encoding="utf-8")
    for needle in ("renderStandings", "league.standings", "playoffPct", "byePct", "myGames", '"standings", "Standings"'):
        assert needle in js, needle


def test_add_to_home_screen_files():
    import json
    m = json.loads((SITE / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert (m["name"], m["short_name"], m["display"], m["start_url"]) == ("Weekly Board", "Board", "standalone", ".")
    assert m["icons"] == [{"src": "icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}]
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert "--bg:#f6f7f9" in css and "--bg:#0f1318" in css   # manifest and theme colors come from these tokens
    assert m["theme_color"] == m["background_color"] == "#f6f7f9"
    assert (SITE / "icon.svg").read_text(encoding="utf-8").startswith("<svg ")
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for needle in ('rel="manifest" href="manifest.webmanifest"', 'rel="icon" type="image/svg+xml" href="icon.svg"',
                   'rel="apple-touch-icon" href="icon.svg"',
                   'name="theme-color" content="#f6f7f9" media="(prefers-color-scheme: light)"',
                   'name="theme-color" content="#0f1318" media="(prefers-color-scheme: dark)"'):
        assert needle in html, needle


def test_next_refresh_line_starts_hidden_and_the_bar_sticks_on_phones():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert '<p id="next" class="muted" hidden></p>' in html
    assert 'id="viewbar"' in html and 'class="bar"' in html
    css = (SITE / "style.css").read_text(encoding="utf-8")
    assert "@media (max-width:999px){\n  .bar{position:sticky;top:0" in css
    assert "nextRefresh" in (SITE / "app.js").read_text(encoding="utf-8")


def test_refresh_button_is_a_plain_link_to_the_workflow():
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert html.count(REFRESH_URL) == 1
    assert re.search(r'<a class="refresh" href="' + re.escape(REFRESH_URL) + r'"[^>]*rel="noopener noreferrer"[^>]*>Refresh</a>', html)
    assert "github.com" not in (SITE / "app.js").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in (REPO / ".github/workflows/refresh.yml").read_text(encoding="utf-8")
