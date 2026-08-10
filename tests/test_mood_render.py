"""Characterization tests for mood-tracker/render-mood-journal.py helpers.

daily_note_link must keep producing the vault's daily-note filename format
(`dddd, MMMM Do, YYYY`); a drift there silently breaks every wikilink the
mood journal writes.
"""

from datetime import date

from conftest import load_script

mood = load_script("mood-tracker/render-mood-journal.py")


class TestFormatting:
    def test_fmt_score(self):
        assert mood.fmt_score(None) == "—"
        assert mood.fmt_score(3.0) == "3"
        assert mood.fmt_score(3.5) == "3.5"
        assert mood.fmt_score(4) == "4"

    def test_ordinal_suffix(self):
        assert mood.ordinal_suffix(1) == "st"
        assert mood.ordinal_suffix(2) == "nd"
        assert mood.ordinal_suffix(3) == "rd"
        assert mood.ordinal_suffix(4) == "th"
        assert mood.ordinal_suffix(11) == "th"
        assert mood.ordinal_suffix(12) == "th"
        assert mood.ordinal_suffix(13) == "th"
        assert mood.ordinal_suffix(21) == "st"
        assert mood.ordinal_suffix(22) == "nd"

    def test_daily_note_link_matches_vault_format(self):
        assert mood.daily_note_link("2026-08-10") == "Monday, August 10th, 2026"
        assert mood.daily_note_link("2026-03-01") == "Sunday, March 1st, 2026"

    def test_none_scores_never_crash(self):
        assert mood.get_emoji(None) == ""
        assert mood.get_color(None) == "#2c2c2c"


class TestWeekBounds:
    def test_monday_anchors_week(self):
        monday, sunday = mood.week_bounds(date(2026, 8, 10))
        assert monday == date(2026, 8, 10)
        assert sunday == date(2026, 8, 16)

    def test_midweek_maps_back(self):
        monday, sunday = mood.week_bounds(date(2026, 8, 13))
        assert monday == date(2026, 8, 10)
        assert sunday == date(2026, 8, 16)


class TestWeeklySummary:
    def test_two_entry_week(self):
        entries = [
            {"date": "2026-08-10", "overall": 3.0, "emotional": 3, "energy": 2,
             "self_care": 3, "social": 4, "purpose": 3},
            {"date": "2026-08-12", "overall": 4.0, "emotional": 4, "energy": 4,
             "self_care": 4, "social": 4, "purpose": 4},
        ]
        out = "\n".join(mood.render_weekly_summaries(entries))
        assert "### Week of" in out
        assert "**Overall: 3.5/5**" in out


class TestParseFrontmatter:
    def test_typed_values(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("---\nmood_score: 3.5\nmood_energy: 4\ndate: 2026-08-10\n---\nbody\n")
        fm = mood.parse_frontmatter(note)
        assert fm == {"mood_score": 3.5, "mood_energy": 4, "date": "2026-08-10"}

    def test_no_frontmatter(self, tmp_path):
        note = tmp_path / "note.md"
        note.write_text("just a body\n")
        assert mood.parse_frontmatter(note) is None
