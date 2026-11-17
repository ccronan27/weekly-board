"""Hard rules for the static site from CLAUDE.md."""
import importlib.util
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE = REPO / "site"


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
        assert not re.search(r"https?://", p.read_text(encoding="utf-8")), f"external URL in {p.name}"


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
