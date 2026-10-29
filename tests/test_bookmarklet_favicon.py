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


def test_label_runs_split_emoji_from_text():
    assert bf._label_runs("🕰️ Wayback") == [("🕰️", True), (" Wayback", False)]
    assert bf._label_runs("📋Unlock") == [("📋", True), ("Unlock", False)]
    assert bf._label_runs("⬇️ Page → MP3") == [("⬇️", True), (" Page → MP3", False)]


def test_relative_file_paths_resolve_against_the_manifest(tmp_path):
    manifest = tmp_path / "icons.json"
    manifest.write_text(json.dumps({"icons": {
        "Passage": "file:icons/passage-{size}.svg",
        "Abs": "file:/opt/x.svg",
        "Home": "file:~/x.svg",
    }}))
    icons = bf.load_manifest(manifest).icons
    assert icons["passage"].value == str(tmp_path / "icons" / "passage-{size}.svg")
    assert icons["abs"].value == "/opt/x.svg"
    assert icons["home"].value == "~/x.svg"
    assert bf.sized_paths(icons["passage"].value) == {
        16: tmp_path / "icons" / "passage-16.svg", 32: tmp_path / "icons" / "passage-32.svg"}
    assert bf.sized_paths("/opt/x.svg") is None


@pytest.mark.skipif(not HAVE_PIL, reason="needs Pillow")
def test_per_size_art_is_used_as_drawn(tmp_path):
    Image = bf.Image
    for size, color in ((16, (200, 10, 10, 255)), (32, (10, 200, 10, 255))):
        art = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        art.putpixel((1, 1), color)  # a lone pixel at the edge: a crop or resample would move or blur it
        art.save(tmp_path / f"a-{size}.png")
    icon = bf.render(bf.parse_spec(f"file:{tmp_path}/a-{{size}}.png"))
    import io
    for size, color in ((16, (200, 10, 10, 255)), (32, (10, 200, 10, 255))):
        got = Image.open(io.BytesIO(icon.bitmaps[size])).convert("RGBA")
        assert got.size == (size, size)
        assert got.getpixel((1, 1)) == color and got.getpixel((2, 2)) == (0, 0, 0, 0)


@pytest.mark.skipif(not HAVE_PIL, reason="needs Pillow")
def test_content_address_covers_every_size():
    Image = bf.Image
    big = Image.new("RGBA", (32, 32), "#00ff00")
    one = bf.make_icon({16: Image.new("RGBA", (16, 16), "#ff0000"), 32: big})
    two = bf.make_icon({16: Image.new("RGBA", (16, 16), "#0000ff"), 32: big})
    assert one.bitmaps[32] == two.bitmaps[32]
    assert one.icon_url != two.icon_url


@pytest.mark.skipif(not (HAVE_PIL and any(p and Path(p).exists() for p in bf.SYMBOL_FONTS)),
                    reason="needs Pillow and the Material Symbols font")
def test_symbols_draw_once_per_size_with_matched_optical_size():
    options = dict(bf.DEFAULT_OPTIONS)
    small = bf.render_symbol("content_paste", options, 16)
    assert small.size == (16, 16)
    thin = bf.render_symbol("content_paste", {**options, "opsz": "48"}, 16)
    assert small.tobytes() != thin.tobytes()  # the opsz axis is wired: 20 at 16 px, not 48
    icon = bf.render(bf.parse_spec("symbol:content_paste"))
    assert set(icon.bitmaps) == {16, 32}


def test_code_match_wins_and_survives_a_removed_name(tmp_path):
    manifest_file = tmp_path / "icons.json"
    manifest_file.write_text(json.dumps({"icons": {
        "Wayback": {"icon": "text:W", "match": "web.archive.org/web/"},
        "Save": {"icon": "text:S", "match": ["web.archive.org/save/", "never-present"]},
        "Archive This": "text:A",
        "Plain": {"emoji": "💾"},
    }}))
    manifest = bf.load_manifest(manifest_file)
    source, spec = bf.choose_spec(bf.Bookmarklet("", WAYBACK, ""), manifest)
    assert (source, spec.value) == ("manifest, code match", "W")
    # the code match beats the name match
    assert bf.choose_spec(bf.Bookmarklet("💾 Archive This", SAVE, ""), manifest)[1].value == "S"
    # matching reads the code after percent-decoding, as the bookmark stores it encoded
    encoded = "javascript:void(window.open('https://web.archive.org%2Fweb%2F2%2F'%2Blocation.href))"
    assert bf.choose_spec(bf.Bookmarklet("x", encoded, ""), manifest)[1].value == "W"
    assert manifest.icons["plain"].kind == "emoji"  # a plain dict spec still parses


def test_fallback_never_replaces_an_existing_icon(tmp_path):
    profile = _profile(tmp_path, [("", WAYBACK)])
    bm = bf.bookmarklets(profile)[0]
    with bf.exclusive_connection(profile.favicons_db) as c:
        bf.apply_plans(c, [bf.Plan(profile, bm, "manifest", bf.Spec("text", "W"), _icon(b"designed"))], commit=True)
    with bf.exclusive_connection(profile.favicons_db) as c:
        out = bf.apply_plans(c, [bf.Plan(profile, bm, "first letter", bf.Spec("text", "?"), _icon(b"fallback"))],
                             commit=True)
    assert out[0][1] == "kept"
    con = sqlite3.connect(profile.favicons_db)
    assert [r[0] for r in con.execute("SELECT url FROM favicons")] == [bf.ICON_URL_PREFIX + b"designed".hex()]
    con.close()
    other = _profile(tmp_path / "other", [("", WAYBACK)])
    bm2 = bf.bookmarklets(other)[0]
    with bf.exclusive_connection(other.favicons_db) as c:  # with no icon yet, the fallback fills the gap
        out = bf.apply_plans(c, [bf.Plan(other, bm2, "first letter", bf.Spec("text", "?"), _icon(b"fallback"))],
                             commit=True)
    assert out[0][1] == "set"


def test_plan_label_names_an_icon_only_bookmark():
    nameless = bf.Plan(None, bf.Bookmarklet("", WAYBACK, ""), "manifest, code match", bf.Spec("text", "W"),
                       entry="Wayback")
    assert nameless.label == "[no name: Wayback]"
    unknown = bf.Plan(None, bf.Bookmarklet("", WAYBACK, ""), "first letter", bf.Spec("text", "?"))
    assert unknown.label.startswith("[no name: (function(){window.open(")
    named = bf.Plan(None, bf.Bookmarklet("🕰️ Wayback", WAYBACK, ""), "manifest", bf.Spec("text", "W"))
    assert named.label == "🕰️ Wayback"


def test_apply_quit_leaves_the_browser_running_when_nothing_changes(tmp_path, monkeypatch, capsys):
    profile = _profile(tmp_path, [("", WAYBACK)])
    con = sqlite3.connect(profile.favicons_db)
    con.execute("INSERT INTO favicons (url, icon_type) VALUES ('https://web.archive.org/favicon.ico', 1)")
    con.execute("INSERT INTO favicon_bitmaps (icon_id, image_data, width, height) VALUES (1, X'AA', 16, 16)")
    con.execute("INSERT INTO favicon_bitmaps (icon_id, image_data, width, height) VALUES (1, X'BB', 32, 32)")
    con.execute("INSERT INTO icon_mapping (page_url, icon_id) VALUES ('https://web.archive.org/web/', 1)")
    con.commit()
    con.close()
    manifest = tmp_path / "icons.json"
    manifest.write_text(json.dumps({"icons": {"Wayback": {"icon": "like:https://web.archive.org/",
                                                          "match": "web.archive.org/web/"}}}))
    monkeypatch.setitem(bf.BROWSERS, "chrome", bf.Browser("chrome", "Google Chrome", profile.root, tmp_path / "none.app"))
    monkeypatch.setattr(bf, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(bf, "relaunch", lambda browser: pytest.fail("relaunched"))
    monkeypatch.setattr(bf, "quit_browser", lambda browser, timeout=60: pytest.fail("quit"))
    monkeypatch.setattr(bf, "running", lambda browser: False)
    assert bf.main(["apply", "--manifest", str(manifest)]) == 0  # browser closed: the icon gets written
    assert "set" in capsys.readouterr().out
    monkeypatch.setattr(bf, "running", lambda browser: True)
    assert bf.main(["apply", "--quit", "--manifest", str(manifest)]) == 0  # nothing new: no quit, no relaunch
    assert "already in place" in capsys.readouterr().out
