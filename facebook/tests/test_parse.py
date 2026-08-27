"""Regression tests for the Comet-feed parser, via the public parse_target.

The fixture mirrors the real Facebook (Comet) GraphQL shape mapped from live
data, with NO real names: a group_feed edge node whose engagement lives deep
under comet_ufi_summary_and_actions_renderer, plus a preview comment carrying
its own reactions (the trap the post total must not pick up).

Runs against a tempdir (monkeypatched paths), so it never touches real data,
reports, cookies, or the targets file.

Run: `python3 tests/test_parse.py`  (or `pytest facebook/tests/`)
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fbtools import config, parse  # noqa: E402


def _ts(date: str) -> int:
    return int(time.mktime(time.strptime(date, "%Y-%m-%d")))


def _node(pid: str, total_reactions: int, comments: int, caption: str, date: str) -> dict[str, Any]:
    ufi = {
        "comet_ufi_summary_and_actions_renderer": {
            "feedback": {
                "id": "ZmVlZGJhY2s=",
                "subscription_target_id": pid,
                # Per-reaction-type breakdown as localized strings: must lose to
                # the numeric total below.
                "top_reactions": {"edges": [{"i18n_reaction_count": "999", "node": {"key": "LIKE"}}]},
                "adaptive_ufi_action_renderers": [
                    {"feedback": {"reaction_count": {"count": total_reactions}}},
                    {"feedback": {"comment_rendering_instance": {"comments": {"total_count": comments}}}},
                ],
            }
        }
    }
    return {
        "__typename": "Story",
        "post_id": pid,
        "id": f"base64_{pid}",
        "creation_time": _ts(date),
        "permalink_url": f"https://www.facebook.com/groups/OMfCT/permalink/{pid}/",
        "actors": [{"name": "Fixture Person", "id": f"a{pid}"}],
        "attachments": [
            {"styles": {"attachment": {"media": {"image": {"uri": f"https://scontent.fbcdn.net/v/t39/{pid}.jpg"}}}}}
        ],
        # Stub feedback like the real node has (must NOT be used for counts).
        "feedback": {"associated_group": {"id": "g"}, "id": "stub", "owning_profile": {"id": "p"}},
        "comet_sections": {
            "content": {"story": {"message": {"text": caption}}},
            "feedback": {
                "story": {
                    "story_ufi_container": {
                        "story": {
                            "feedback_context": {
                                # Preview comment with its OWN reactions -- the trap.
                                "interesting_top_level_comments": [
                                    {"comment": {"feedback": {"reaction_count": {"count": 888}}}}
                                ],
                                "feedback_target_with_context": ufi,
                            }
                        }
                    }
                }
            },
        },
    }


def _raw_line(nodes: list[dict[str, Any]]) -> str:
    body = json.dumps({"data": {"node": {"group_feed": {"edges": [{"node": n} for n in nodes]}}}})
    return json.dumps({"url": "https://www.facebook.com/api/graphql/", "body": body})


def _raw_line_direct(node: dict[str, Any]) -> str:
    """A standalone single-story response: the post sits at data.node directly,
    not inside a feed edge. This shape once dropped every post it delivered."""
    body = json.dumps({"data": {"node": node}})
    return json.dumps({"url": "https://www.facebook.com/api/graphql/", "body": body})


def _parse_fixture(tmp: Path, raw_lines: list[str]) -> dict[str, dict[str, Any]]:
    """Point config at a tempdir, write a raw dump, run parse_target, load it."""
    config.ROOT = tmp
    config.DATA = tmp / "data"
    config.REPORT = tmp / "report"
    config.TARGETS_FILE = tmp / "targets.json"
    target, _ = config.resolve_target("selftest", "https://www.facebook.com/groups/OMfCT")
    target.raw.mkdir(parents=True, exist_ok=True)
    (target.raw / "raw-selftest.jsonl").write_text("\n".join(raw_lines), encoding="utf-8")
    parse.parse_target("selftest")
    return {
        json.loads(line)["id"]: json.loads(line)
        for line in target.posts_file.read_text().splitlines()
        if line.strip()
    }


def test_extraction_from_comet_shape() -> None:
    with tempfile.TemporaryDirectory() as d:
        posts = _parse_fixture(
            Path(d), [_raw_line([_node("111", 150, 12, "caption twenty twenty-one", "2021-05-01")])]
        )
    assert set(posts) == {"111"}
    rec = posts["111"]
    assert rec["reactions"] == 150, f"post total, not 888 comment or 999 i18n: {rec['reactions']}"
    assert rec["comments"] == 12, rec["comments"]
    assert rec["year"] == 2021, rec["year"]
    assert rec["permalink"].endswith("/permalink/111/")
    assert len(rec["images"]) == 1 and rec["images"][0].endswith("111.jpg")
    assert rec["author"]["name"] == "Fixture Person"
    assert rec["text"] == "caption twenty twenty-one"


def test_direct_single_story_node() -> None:
    """A post delivered as data.node (no feed edge) must still be extracted."""
    with tempfile.TemporaryDirectory() as d:
        posts = _parse_fixture(
            Path(d), [_raw_line_direct(_node("999", 133, 20, "top meme of the year", "2026-02-14"))]
        )
    assert set(posts) == {"999"}, "the direct single-story post must be captured"
    assert posts["999"]["reactions"] == 133


def test_comment_reactions_not_counted_as_post() -> None:
    with tempfile.TemporaryDirectory() as d:
        posts = _parse_fixture(Path(d), [_raw_line([_node("222", 5, 0, "low", "2020-01-01")])])
    assert set(posts) == {"222"}, "the 888-reaction preview comment must not become a post"
    assert posts["222"]["reactions"] == 5


def test_max_merge_and_years() -> None:
    with tempfile.TemporaryDirectory() as d:
        posts = _parse_fixture(
            Path(d),
            [
                _raw_line([_node("111", 150, 12, "cap", "2021-05-01"), _node("333", 40, 3, "c20", "2020-07-07")]),
                _raw_line([_node("111", 175, 15, "cap", "2021-05-01")]),  # aged: higher count
            ],
        )
    assert posts["111"]["reactions"] == 175, "max-merge should keep the higher count"
    assert posts["111"]["comments"] == 15
    assert posts["333"]["year"] == 2020
    assert {p["year"] for p in posts.values()} == {2020, 2021}


def _run() -> int:
    for t in (
        test_extraction_from_comet_shape,
        test_direct_single_story_node,
        test_comment_reactions_not_counted_as_post,
        test_max_merge_and_years,
    ):
        t()
        print(f"PASS {t.__name__}")
    print("\nAll parser tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
