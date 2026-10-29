"""bin/bookmarklet-favicon: name matching, spec parsing, and the Favicons database writes."""

import importlib.machinery
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
_loader = importlib.machinery.SourceFileLoader("bookmarklet_favicon", str(REPO / "bin" / "bookmarklet-favicon"))
spec = importlib.util.spec_from_loader("bookmarklet_favicon", _loader)
assert spec is not None and spec.loader is not None
bf = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bf  # dataclasses resolve string annotations through sys.modules
spec.loader.exec_module(bf)

# Chrome's Favicons schema, version 9 (components/favicon/core/favicon_database.cc).
SCHEMA = """
CREATE TABLE meta(key LONGVARCHAR NOT NULL UNIQUE PRIMARY KEY, value LONGVARCHAR);
CREATE TABLE icon_mapping(id INTEGER PRIMARY KEY,page_url LONGVARCHAR NOT NULL,icon_id INTEGER,page_url_type INTEGER DEFAULT 0);
CREATE TABLE favicons(id INTEGER PRIMARY KEY,url LONGVARCHAR NOT NULL,icon_type INTEGER DEFAULT 1);
CREATE TABLE favicon_bitmaps(id INTEGER PRIMARY KEY,icon_id INTEGER NOT NULL,last_updated INTEGER DEFAULT 0,image_data BLOB,width INTEGER DEFAULT 0,height INTEGER DEFAULT 0,last_requested INTEGER DEFAULT 0);
CREATE INDEX icon_mapping_page_url_idx ON icon_mapping(page_url);
CREATE INDEX icon_mapping_icon_id_idx ON icon_mapping(icon_id);
CREATE INDEX favicons_url ON favicons(url);
CREATE INDEX favicon_bitmaps_icon_id ON favicon_bitmaps(icon_id);
INSERT INTO meta VALUES ('version', '9'), ('last_compatible_version', '9');
"""

WAYBACK = "javascript:(function(){window.open('https://web.archive.org/web/2/'+location.href,'_blank');})()"
SAVE = "javascript:(function(){window.open('https://web.archive.org/save/'+location.href,'_blank');})()"

SCRIPT = REPO / "bin" / "bookmarklet-favicon"
HAVE_FONTS = Path(bf.EMOJI_FONT).exists() and any(p and Path(p).exists() for p in bf.TEXT_FONTS)
HAVE_PIL = bf.PIL_ERROR is None


def _script_python_has_pil() -> bool:
    # The script runs under `python3` from PATH, which may differ from the test interpreter.
    probe = subprocess.run(["/usr/bin/env", "python3", "-c", "import PIL"], capture_output=True, check=False)
    return probe.returncode == 0


def test_normalize_strips_emoji_and_case():
    assert bf.normalize_name("🕰️ Wayback") == "wayback"
    assert bf.normalize_name("Wayback") == "wayback"
    assert bf.normalize_name("📋Unlock [Select/Copy/Paste]") == "unlock [select/copy/paste]"
    assert bf.normalize_name("⬇️ Page → MP3") == bf.normalize_name("Page → MP3")


def test_leading_emoji_keeps_selectors_and_stops_at_text():
    assert bf.leading_emoji("🕰️ Wayback") == "🕰️"
    assert bf.leading_emoji("⬇️ Page → MP3") == "⬇️"
    assert bf.leading_emoji("📋Unlock") == "📋"
    assert bf.leading_emoji("👍🏽 ok") == "👍🏽"
    assert bf.leading_emoji("Allow Text Selection") is None
    assert bf.leading_emoji("→ arrows are not emoji") is None


def test_parse_spec_forms():
    s = bf.parse_spec("symbol:history,bg=#123456,fg=#fff")
    assert (s.kind, s.value, s.options["bg"], s.options["fg"]) == ("symbol", "history", "#123456", "#fff")
    assert str(s) == "symbol:history,bg=#123456,fg=#fff"
    assert bf.parse_spec("like:https://a.example/x,y").value == "https://a.example/x,y"
    d = bf.parse_spec({"emoji": "🔓", "bg": "#000"}, {"fg": "#eee"})
    assert (d.kind, d.value, d.options["bg"], d.options["fg"]) == ("emoji", "🔓", "#000", "#eee")
    with pytest.raises(ValueError):
        bf.parse_spec("nope:x")
    with pytest.raises(ValueError):
        bf.parse_spec("text:A,badoption")


def test_choose_spec_order(tmp_path):
    manifest_file = tmp_path / "icons.json"
    manifest_file.write_text(json.dumps({"icons": {"Wayback": "text:W"}}))
    manifest = bf.load_manifest(manifest_file)
    by_manifest = bf.choose_spec(bf.Bookmarklet("🕰️ Wayback", WAYBACK, ""), manifest)
    assert by_manifest[0] == "manifest" and by_manifest[1].kind == "text"
    by_emoji = bf.choose_spec(bf.Bookmarklet("💾 Archive This", SAVE, ""), manifest)
    assert by_emoji[0] == "emoji in name" and by_emoji[1].value == "💾"
    by_letter = bf.choose_spec(bf.Bookmarklet("plain name", SAVE, ""), manifest)
    assert by_letter[0] == "first letter" and (by_letter[1].kind, by_letter[1].value) == ("text", "P")


def _profile(tmp_path, bookmarks):
    root = tmp_path / "User Data"
    prof = root / "Default"
    prof.mkdir(parents=True)
    (prof / "Bookmarks").write_text(json.dumps({"roots": {"bookmark_bar": {
        "type": "folder", "name": "Bookmarks Bar",
        "children": [{"type": "url", "name": n, "url": u} for n, u in bookmarks]}}}))
    con = sqlite3.connect(prof / "Favicons")
    con.executescript(SCHEMA)
    con.close()
    return bf.Profile(bf.BROWSERS["chrome"], root, "Default", "Default")


def _icon(png: bytes):
    return bf.Icon({16: png, 32: png + b"32"}, bf.ICON_URL_PREFIX + png.hex())


def test_bookmarklets_keep_url_verbatim(tmp_path):
    profile = _profile(tmp_path, [("🕰️ Wayback", WAYBACK), ("GitHub", "https://github.com/")])
    found = bf.bookmarklets(profile)
    assert [(b.name, b.url, b.folder) for b in found] == [("🕰️ Wayback", WAYBACK, "Bookmarks Bar")]


def test_apply_writes_rows_and_is_idempotent(tmp_path):
    profile = _profile(tmp_path, [("🕰️ Wayback", WAYBACK), ("💾 Archive This", SAVE)])
    bms = bf.bookmarklets(profile)
    plans = [bf.Plan(profile, bms[0], "test", bf.Spec("text", "W"), _icon(b"png-w")),
             bf.Plan(profile, bms[1], "test", bf.Spec("text", "A"), _icon(b"png-a"))]
    with bf.exclusive_connection(profile.favicons_db) as con:
        results = bf.apply_plans(con, plans, commit=True)
    assert [r[1] for r in results] == ["set", "set"]
    con = sqlite3.connect(profile.favicons_db)
    rows = con.execute("SELECT page_url, icon_id, page_url_type FROM icon_mapping ORDER BY id").fetchall()
    assert [r[0] for r in rows] == [WAYBACK, SAVE]
    assert {r[2] for r in rows} == {0}
    bitmaps = con.execute("SELECT width, height, last_requested FROM favicon_bitmaps ORDER BY icon_id, width").fetchall()
    assert bitmaps == [(16, 16, 0), (32, 32, 0), (16, 16, 0), (32, 32, 0)]
    stamp = con.execute("SELECT MIN(last_updated) FROM favicon_bitmaps").fetchone()[0]
    assert stamp > 13_300_000_000_000_000  # Chrome epoch microseconds, i.e. after 2022
    con.close()

    with bf.exclusive_connection(profile.favicons_db) as con:
        again = bf.apply_plans(con, plans, commit=True)
    assert [r[1] for r in again] == ["unchanged", "unchanged"]
    con = sqlite3.connect(profile.favicons_db)
    assert con.execute("SELECT COUNT(*) FROM icon_mapping").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM favicons").fetchone()[0] == 2
    con.close()


def test_replacing_an_icon_prunes_only_our_orphan(tmp_path):
    profile = _profile(tmp_path, [("🕰️ Wayback", WAYBACK)])
    con = sqlite3.connect(profile.favicons_db)
    con.execute("INSERT INTO favicons (url, icon_type) VALUES ('https://site.example/favicon.ico', 1)")
    con.execute("INSERT INTO favicon_bitmaps (icon_id, image_data, width, height) VALUES (1, X'00', 16, 16)")
    con.commit()
    con.close()
    bm = bf.bookmarklets(profile)[0]
    with bf.exclusive_connection(profile.favicons_db) as c:
        bf.apply_plans(c, [bf.Plan(profile, bm, "t", bf.Spec("text", "W"), _icon(b"one"))], commit=True)
    with bf.exclusive_connection(profile.favicons_db) as c:
        out = bf.apply_plans(c, [bf.Plan(profile, bm, "t", bf.Spec("text", "W"), _icon(b"two"))], commit=True)
    assert out[0][1] == "replaced"
    con = sqlite3.connect(profile.favicons_db)
    urls = sorted(r[0] for r in con.execute("SELECT url FROM favicons"))
    assert urls == sorted(["https://site.example/favicon.ico", bf.ICON_URL_PREFIX + b"two".hex()])
    assert con.execute("SELECT COUNT(*) FROM icon_mapping").fetchone()[0] == 1
    con.close()


def test_dry_run_rolls_back(tmp_path):
    profile = _profile(tmp_path, [("🕰️ Wayback", WAYBACK)])
    bm = bf.bookmarklets(profile)[0]
    with bf.exclusive_connection(profile.favicons_db) as c:
        bf.apply_plans(c, [bf.Plan(profile, bm, "t", bf.Spec("text", "W"), _icon(b"x"))], commit=False)
    con = sqlite3.connect(profile.favicons_db)
    assert con.execute("SELECT COUNT(*) FROM icon_mapping").fetchone()[0] == 0
    con.close()


def test_locked_database_is_refused(tmp_path):
    profile = _profile(tmp_path, [("🕰️ Wayback", WAYBACK)])
    holder = sqlite3.connect(profile.favicons_db, isolation_level=None)
    holder.execute("PRAGMA locking_mode = EXCLUSIVE")
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO favicons (url) VALUES ('x')")
    with pytest.raises(SystemExit):
        with bf.exclusive_connection(profile.favicons_db):
            pass
    holder.execute("ROLLBACK")
    holder.close()


def test_unknown_schema_version_is_refused(tmp_path):
    profile = _profile(tmp_path, [("🕰️ Wayback", WAYBACK)])
    con = sqlite3.connect(profile.favicons_db)
    con.execute("UPDATE meta SET value = '12' WHERE key = 'version'")
    con.commit()
    con.close()
    bm = bf.bookmarklets(profile)[0]
    with pytest.raises(SystemExit), bf.exclusive_connection(profile.favicons_db) as c:
        bf.apply_plans(c, [bf.Plan(profile, bm, "t", bf.Spec("text", "W"), _icon(b"x"))], commit=True)


def test_icon_like_reuses_profile_icon(tmp_path):
    profile = _profile(tmp_path, [("🕰️ Wayback", WAYBACK)])
    con = sqlite3.connect(profile.favicons_db)
    con.execute("INSERT INTO favicons (url, icon_type) VALUES ('https://web.archive.org/favicon.ico', 1)")
    con.execute("INSERT INTO favicon_bitmaps (icon_id, image_data, width, height) VALUES (1, X'AA', 16, 16)")
    con.execute("INSERT INTO favicon_bitmaps (icon_id, image_data, width, height) VALUES (1, X'BB', 32, 32)")
    con.execute("INSERT INTO icon_mapping (page_url, icon_id) VALUES ('https://web.archive.org/web/', 1)")
    con.commit()
    con.close()
    icon = bf.icon_like(profile.favicons_db, "https://web.archive.org/")
    assert icon.icon_id == 1 and icon.bitmaps == {16: b"\xaa", 32: b"\xbb"}
    with pytest.raises(ValueError):
        bf.icon_like(profile.favicons_db, "https://nowhere.example/")


def test_export_html_carries_icon_and_escaped_url():
    bm = bf.Bookmarklet("A & B", "javascript:alert(\"<x>\")", "")
    plan = bf.Plan(None, bm, "t", bf.Spec("text", "A"), _icon(b"\x89PNG"))
    out = bf.export_html([plan])
    assert 'HREF="javascript:alert(&quot;&lt;x&gt;&quot;)"' in out
    assert 'ICON="data:image/png;base64,' in out and ">A &amp; B</A>" in out


@pytest.mark.skipif(not (HAVE_PIL and HAVE_FONTS), reason="needs Pillow, Apple Color Emoji and Roboto or Helvetica")
def test_rendering_produces_both_sizes():
    for spec in ("emoji:🕰️", "text:W", "text:MP,bg=#000000"):
        icon = bf.render(bf.parse_spec(spec))
        assert set(icon.bitmaps) == {16, 32}
        assert all(png.startswith(b"\x89PNG") for png in icon.bitmaps.values())
        assert icon.icon_url is not None and icon.icon_url.startswith(bf.ICON_URL_PREFIX)
    assert bf.render(bf.parse_spec("text:W")).icon_url == bf.render(bf.parse_spec("text:W")).icon_url


@pytest.mark.skipif(not (_script_python_has_pil() and HAVE_FONTS), reason="the script's python3 needs Pillow and fonts")
def test_render_cli_writes_png(tmp_path):
    out = tmp_path / "w.png"
    subprocess.run([str(SCRIPT), "render", "text:W,bg=#000000", "-o", str(out), "--size", "32"],
                   check=True, capture_output=True)
    png = out.read_bytes()
    assert png.startswith(b"\x89PNG")
    assert b"IHDR" in png and png[16:24] == (32).to_bytes(4, "big") * 2
