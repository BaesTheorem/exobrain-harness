"""Property-based tests (Hypothesis) for the repo's pure parsing helpers.

Why property tests specifically: agent-written code is plausible-looking by
construction, and example tests can be satisfied by the same plausibility.
Hypothesis picks the inputs itself, so an overfit implementation still fails.
Keep each test fast; this file runs inside the edit loop, not a nightly job.
"""

from datetime import date, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import load_script
from test_imessage_reader import make_blob

reader = load_script("imessage/imessage-reader.py")
sync = load_script("things3-sync/things3-obsidian-sync.py")
mood = load_script("mood-tracker/render-mood-journal.py")

# Keep example counts modest: this suite should stay under a few seconds total.
FAST = settings(max_examples=60, deadline=None)


class TestTypedstreamRoundtrip:
    @FAST
    @given(st.text(max_size=300))
    def test_roundtrip_any_text(self, text):
        assert reader.extract_body_text(make_blob(text)) == text

    @FAST
    @given(st.integers(min_value=0, max_value=200))
    def test_roundtrip_multibyte_lengths(self, n):
        # Multi-byte chars push the byte length across the 0x80/0x81 encoding
        # boundary at a different point than the character count.
        text = "é世\U0001f389" * n
        assert reader.extract_body_text(make_blob(text)) == text

    @FAST
    @given(st.binary(max_size=200))
    def test_never_raises_on_garbage(self, blob):
        reader.extract_body_text(blob)  # any return is fine; raising is not


class TestPhoneNormalization:
    @FAST
    @given(st.text(alphabet="0123456789()+- .", max_size=20))
    def test_idempotent(self, raw):
        once = reader._normalize_phone(raw)
        assert reader._normalize_phone(once) == once

    @FAST
    @given(st.text(alphabet="0123456789", min_size=10, max_size=10))
    def test_ten_digits_always_get_us_prefix(self, digits):
        assert reader._normalize_phone(digits) == "+1" + digits


class TestFrontmatterUpdate:
    keys = st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=12)
    values = st.text(
        alphabet=st.characters(blacklist_characters="\n\r", blacklist_categories=("Cs",)),
        max_size=30,
    )

    @FAST
    @given(key=keys, value=values)
    def test_update_lands_in_frontmatter_exactly_once(self, key, value):
        text = "---\nstatus: active\n---\n# Body\n"
        out = sync.update_frontmatter_field(text, key, value)
        fm_block = out.split("---\n")[1]
        hits = [ln for ln in fm_block.splitlines() if ln.startswith(f"{key}:")]
        assert len(hits) == 1
        assert out.endswith("# Body\n")

    @FAST
    @given(key=keys, value=values)
    def test_second_update_is_idempotent(self, key, value):
        text = "---\nstatus: active\n---\n# Body\n"
        once = sync.update_frontmatter_field(text, key, value)
        twice = sync.update_frontmatter_field(once, key, value)
        assert once == twice


class TestDateHelpers:
    @FAST
    @given(st.integers(min_value=1, max_value=3000))
    def test_ordinal_suffix_total_and_teens(self, day):
        suffix = mood.ordinal_suffix(day)
        assert suffix in ("st", "nd", "rd", "th")
        if 10 <= day % 100 <= 20:
            assert suffix == "th"

    @FAST
    @given(st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)))
    def test_week_bounds_invariants(self, d):
        monday, sunday = mood.week_bounds(d)
        assert monday.weekday() == 0
        assert sunday - monday == timedelta(days=6)
        assert monday <= d <= sunday

    @FAST
    @given(st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)))
    def test_daily_note_link_parses_back(self, d):
        # The link must always be the vault daily-note name for that date.
        link = mood.daily_note_link(d.isoformat())
        assert link.startswith(d.strftime("%A, %B "))
        assert link.endswith(f", {d.year}")
        assert f" {d.day}{mood.ordinal_suffix(d.day)}," in link


class TestScoreFormatting:
    @FAST
    @given(st.one_of(st.none(), st.floats(min_value=0, max_value=5), st.integers(0, 5)))
    def test_fmt_score_never_raises_and_is_compact(self, v):
        out = mood.fmt_score(v)
        assert isinstance(out, str) and out
        if v is not None and float(v).is_integer():
            assert "." not in out
