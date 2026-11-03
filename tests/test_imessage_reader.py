"""Characterization tests for imessage/imessage-reader.py.

extract_body_text parses Apple's typedstream blobs (attributedBody column).
The blob builder here mirrors the length-encoding rules documented in the
function's own docstring; if the parser and these tests ever disagree, read
a real chat.db blob before deciding which one is wrong.
"""

from datetime import datetime

from conftest import load_script

reader = load_script("imessage/imessage-reader.py")


def make_blob(text: str, junk: bytes = b"\x01\x95\x84\x01") -> bytes:
    """Build a minimal typedstream blob the way iMessage lays one out."""
    data = text.encode("utf-8")
    n = len(data)
    if n < 0x81:
        enc = bytes([n])
    elif n <= 0xFFFF:
        enc = b"\x81" + n.to_bytes(2, "little")
    else:
        enc = b"\x82" + n.to_bytes(4, "little")
    return b"\x04\x0bstreamtyped\x81\xe8\x03NSString" + junk + b"+" + enc + data


class TestExtractBodyText:
    def test_short_message(self):
        assert reader.extract_body_text(make_blob("hey, running late")) == "hey, running late"

    def test_empty_message(self):
        assert reader.extract_body_text(make_blob("")) == ""

    def test_boundary_128_bytes_direct_length(self):
        # 0x80 is the largest direct-encoded length.
        text = "a" * 0x80
        assert reader.extract_body_text(make_blob(text)) == text

    def test_boundary_129_bytes_u16_length(self):
        text = "b" * 0x81
        assert reader.extract_body_text(make_blob(text)) == text

    def test_long_message_u32_length(self):
        text = "c" * 70_000
        assert reader.extract_body_text(make_blob(text)) == text

    def test_emoji_multibyte(self):
        text = "see you at 7 \U0001f389\U0001f60a"
        assert reader.extract_body_text(make_blob(text)) == text

    def test_none_and_garbage(self):
        assert reader.extract_body_text(None) is None
        assert reader.extract_body_text(b"") is None
        assert reader.extract_body_text(b"no marker here") is None

    def test_plus_too_far_from_marker(self):
        # The '+' must appear within 20 bytes of 'NSString'.
        blob = make_blob("hi", junk=b"\x00" * 25)
        assert reader.extract_body_text(blob) is None


class TestNormalizePhone:
    def test_ten_digit_us(self):
        assert reader._normalize_phone("8165551234") == "+18165551234"

    def test_eleven_digit_with_country(self):
        assert reader._normalize_phone("18165551234") == "+18165551234"

    def test_already_normalized(self):
        assert reader._normalize_phone("+18165551234") == "+18165551234"

    def test_formatting_stripped(self):
        assert reader._normalize_phone("(816) 555-1234") == "+18165551234"

    def test_empty_passthrough(self):
        assert reader._normalize_phone("") == ""
        assert reader._normalize_phone(None) is None


class TestTimestamps:
    def test_cutoff_roundtrip(self):
        # An Apple-epoch cutoff for "now" should convert back to roughly now.
        ts = reader.utc_cutoff_ts()
        dt = reader.apple_ts_to_datetime(ts)
        assert abs((dt - datetime.now()).total_seconds()) < 5

    def test_cutoff_hours_back(self):
        delta_ns = reader.utc_cutoff_ts() - reader.utc_cutoff_ts(hours=2)
        assert abs(delta_ns - 2 * 3600 * 1_000_000_000) < 5 * 1_000_000_000

    def test_zero_and_none(self):
        assert reader.apple_ts_to_datetime(None) is None
        assert reader.apple_ts_to_datetime(0) is None


class TestChatGrouping:
    """1:1 chats store display_name as '' in chat.db. The reader once let ''
    through COALESCE, labelled every 1:1 thread "Unknown", and printed
    adjacent threads under one header, so a text to one person read as a
    text to the next person in the block."""

    def _rows(self):
        def row(rowid, ident, sender, me, text, ts):
            return {"chat_rowid": rowid, "chat_name": ident, "chat_named": 0,
                    "sender_id": sender, "is_from_me": me, "text": text,
                    "attributedBody": None, "msg_date": ts}
        return [
            row(31, "+18165550001", "+18165550001", 1, "bring kernels", 1),
            row(194, "+18165550002", "+18165550002", 0, "how are you", 2),
        ]

    def test_each_chat_gets_its_own_header(self, monkeypatch, capsys):
        monkeypatch.setattr(reader, "get_contacts", lambda: {
            "+18165550001": "Friend A", "+18165550002": "Friend B"})
        reader._print_messages(self._rows())
        out = capsys.readouterr().out
        assert "Unknown" not in out
        assert out.index("Friend A") < out.index("bring kernels") < out.index("Friend B")

    def test_same_name_different_chat_still_splits(self, monkeypatch, capsys):
        monkeypatch.setattr(reader, "get_contacts", lambda: {})
        rows = self._rows()
        rows[1]["chat_name"] = rows[0]["chat_name"]
        reader._print_messages(rows)
        assert capsys.readouterr().out.count("=" * 60) == 4

    def test_query_treats_empty_display_name_as_missing(self):
        assert "NULLIF(c.display_name, '')" in reader.MSG_QUERY_COLS
