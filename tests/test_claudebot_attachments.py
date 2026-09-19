"""claude-bot attachments: cache naming, transcript markers, recency budget,
and TTL pruning. The bug these guard is an image-only message rendering as an
empty transcript line and vanishing before MIST ever saw it."""

import time
import types

import pytest
from conftest import load_script, script_exists

pytestmark = pytest.mark.skipif(
    not script_exists("claude-bot/attachments.py"), reason="claude-bot not present"
)


def _at():
    return load_script("claude-bot/attachments.py")


def _att(att_id: int, filename: str = "shot.png", size: int = 1000):
    return types.SimpleNamespace(id=att_id, filename=filename, size=size,
                                 content_type="image/png")


def _msg(msg_id: int, *atts):
    return types.SimpleNamespace(id=msg_id, attachments=list(atts))


def test_safe_name_strips_path_traversal():
    at = _at()
    name = at.safe_name(7, 9, "../../etc/passwd")
    assert "/" not in name
    assert name.startswith("7-9-")


def test_safe_name_survives_an_empty_filename():
    at = _at()
    assert at.safe_name(1, 2, "") == "1-2-file"


def test_kind_of_reads_the_content_type_then_the_extension():
    at = _at()
    assert at.kind_of("image/png") == "image"
    assert at.kind_of("video/mp4") == "video"
    assert at.kind_of(None, "report.PDF") == "PDF"
    assert at.kind_of(None, "notes.txt") == "file"


def test_marker_without_a_path_names_the_file_only():
    at = _at()
    mark = at.marker("shot.png", "image/png")
    assert mark == "[image attached: shot.png]"
    assert "/" not in mark  # shared contexts must not leak a local path


def test_marker_with_a_path_points_at_read():
    at = _at()
    mark = at.marker("shot.png", "image/png", "/tmp/cache/1-2-shot.png")
    assert "/tmp/cache/1-2-shot.png" in mark
    assert "Read" in mark


def test_pick_prefers_the_newest_messages():
    at = _at()
    old, new = _msg(1, _att(10)), _msg(2, _att(20))
    picked = at.pick([old, new], limit=1)
    assert [a.id for _, a in picked] == [20]


def test_pick_honours_the_file_budget():
    at = _at()
    msgs = [_msg(i, _att(i * 10), _att(i * 10 + 1)) for i in range(1, 6)]
    assert len(at.pick(msgs, limit=3)) == 3


def test_pick_skips_oversized_files():
    at = _at()
    msgs = [_msg(1, _att(10, size=999), _att(11, size=10**9))]
    assert [a.id for _, a in at.pick(msgs, max_bytes=10**6)] == [10]


def test_pick_ignores_messages_with_no_attachments():
    at = _at()
    assert at.pick([_msg(1), _msg(2)]) == []


def test_prune_deletes_only_expired_files(tmp_path):
    at = _at()
    fresh, stale = tmp_path / "fresh.png", tmp_path / "stale.png"
    fresh.write_bytes(b"x")
    stale.write_bytes(b"x")
    now = time.time()
    import os
    os.utime(stale, (now - 30 * 86400, now - 30 * 86400))
    assert at.prune(tmp_path, ttl_days=7, now=now) == 1
    assert fresh.exists() and not stale.exists()


def test_prune_tolerates_a_missing_cache_dir(tmp_path):
    at = _at()
    assert at.prune(tmp_path / "nope") == 0
