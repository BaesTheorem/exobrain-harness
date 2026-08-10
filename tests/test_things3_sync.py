"""Characterization tests for the pure helpers in things3-sync.

These are the functions that decide where a project note lives and how its
frontmatter is rewritten; getting them silently wrong moves real vault files.
"""

from pathlib import Path

from conftest import load_script

sync = load_script("things3-sync/things3-obsidian-sync.py")

FM_NOTE = """---
status: active
things_id: ABC123
area: "[[Work]]"
---
# My Project

Body text stays untouched.
"""


class TestUpdateFrontmatterField:
    def test_replaces_existing_key(self):
        out = sync.update_frontmatter_field(FM_NOTE, "status", "someday")
        assert "status: someday" in out
        assert "status: active" not in out
        assert "Body text stays untouched." in out

    def test_adds_missing_key(self):
        out = sync.update_frontmatter_field(FM_NOTE, "synced", "2026-08-10")
        assert "synced: 2026-08-10" in out
        # New key lands inside the frontmatter block, not the body.
        assert out.index("synced:") < out.index("# My Project")

    def test_no_frontmatter_returns_unchanged(self):
        plain = "# Just a note\nno frontmatter here\n"
        assert sync.update_frontmatter_field(plain, "status", "active") == plain

    def test_other_keys_untouched(self):
        out = sync.update_frontmatter_field(FM_NOTE, "status", "archive")
        assert 'area: "[[Work]]"' in out
        assert "things_id: ABC123" in out


class TestCleanTitle:
    def test_strips_emoji_prefix(self):
        assert sync.clean_title("\U0001f525 Fix the deck") == "Fix the deck"

    def test_plain_title_unchanged(self):
        assert sync.clean_title("Fix the deck") == "Fix the deck"

    def test_interior_emoji_kept(self):
        assert sync.clean_title("Fix the \U0001f525 deck") == "Fix the \U0001f525 deck"


class TestStatusPaths:
    def test_target_dirs(self):
        assert sync.target_dir_for_status("someday") == sync.SOMEDAY_DIR
        assert sync.target_dir_for_status("archive") == sync.ARCHIVE_DIR
        assert sync.target_dir_for_status("active") == sync.PROJECTS_DIR
        assert sync.target_dir_for_status("anything-else") == sync.PROJECTS_DIR

    def test_status_roundtrips_through_path(self):
        base = Path.home() / "Exobrain" / "Projects"
        assert sync.current_status_from_path(base / "X" / "X.md") == "active"
        assert sync.current_status_from_path(base / "Someday" / "X" / "X.md") == "someday"
        assert sync.current_status_from_path(base / "Archive" / "X.md") == "archive"
        assert sync.current_status_from_path(Path("/tmp/elsewhere.md")) == "active"
