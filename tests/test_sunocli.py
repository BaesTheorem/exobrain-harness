"""Characterization tests for the Suno CLI: request shapes, the two spend gates, the receipts
that stop a double charge, error mapping, timed lyrics, and the drift comparison.

The client is driven through a fake transport and a temp ledger, so nothing touches the
network, the browser, or the real receipts. Every id, name and lyric here is made up.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "suno"))

from sunocli import cli, drift, model, official, session as sess  # noqa: E402
from sunocli.api import (AuthRejected, NotAuthorized, NotFound, OutcomeUnknown, RateLimited,  # noqa: E402
                         Rejected, SchemaDrift, SunoClient, browser_token)
from sunocli.ledger import Blocked, Ledger, fingerprint  # noqa: E402
from sunocli.model import InputError  # noqa: E402

USER = "11111111-2222-3333-4444-555555555555"
PLAN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLIP_A = "0a0a0a0a-1111-2222-3333-444444444444"
CLIP_B = "0b0b0b0b-1111-2222-3333-444444444444"


def make_jwt(**claims) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"h.{body}.s"


JWT = make_jwt(**{"suno/user_id": "1234567", "suno.com/claims/user_id": USER, "suno/handle": "tester",
                  "suno.com/claims/email": "nobody@example.invalid"})


class FakeTransport:
    """Answers in order. A response may be an exception to raise."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, json.loads(body) if body else None, headers))
        answer = self.responses.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        status, payload = answer
        return status, (payload if isinstance(payload, bytes) else json.dumps(payload).encode())

    def paths(self, method=None):
        return [u.split("/a/api", 1)[-1] for m, u, _, _ in self.calls if method in (None, m)]


def make_session(**state) -> sess.Session:
    base = {"client": "cookie-value", "device_id": "dev-1", "session_id": "sess_1", "jwt": JWT, "jwt_at": 1000}
    base.update(state)
    return sess.Session(transport=FakeTransport(), state=base, reimport=None, clock=lambda: 1001, persist=False)


def make_client(*responses) -> tuple[SunoClient, FakeTransport]:
    transport = FakeTransport(*responses)
    client = SunoClient(make_session(), transport=transport, sleep=lambda s: None, clock=lambda: 1001.0)
    return client, transport


def raw_clip(clip_id=CLIP_A, **over) -> dict:
    clip = {"id": clip_id, "title": "Test Song", "status": "complete", "created_at": "2026-11-11T18:09:00.000Z",
            "model_name": "chirp-hawk", "major_model_version": "v6", "is_download_unlocked": False,
            "audio_url": "https://example.invalid/api/forbidden", "user_id": USER,
            "metadata": {"duration": 61.5, "tags": "piano", "prompt": "[Verse]\nA made-up line", "type": "gen"}}
    clip.update(over)
    return clip


def billing(credits=500, used=0, limit=20, extra=6) -> dict:
    return {"total_credits_left": credits, "monthly_limit": 2500, "monthly_usage": 2500 - credits,
            "period": "month", "plan": {"id": PLAN, "name": "Pro Plan"},
            "models": [{"name": "v6", "external_key": "chirp-hawk", "can_use": True, "is_default_model": True,
                        "max_lengths": {"title": 100, "prompt": 5000, "tags": 1000, "negative_tags": 1000,
                                        "gpt_description_prompt": 3000}},
                       {"name": "v6-wild", "external_key": "chirp-hawk-wild", "can_use": False}],
            "download_usage": {"current_period_downloads_used": used, "current_period_downloads_limit": limit,
                               "additional_download_remaining": extra}}


# -- session -----------------------------------------------------------------------------------


@pytest.mark.parametrize("pasted", ["abc123", "__client=abc123", "cookie: a=1; __client=abc123; b=2",
                                    "  a=1; __client=abc123  "])
def test_clean_pasted_finds_the_client_cookie(pasted):
    assert sess.clean_pasted(pasted) == "abc123"


def test_clean_pasted_rejects_a_header_without_it():
    with pytest.raises(ValueError):
        sess.clean_pasted("a=1; b=2")


def test_pick_login_prefers_the_auth_domain_and_needs_a_cookie():
    jar = [{"name": "__client", "value": "old", "domain": ".suno.com"},
           {"name": "__client", "value": "live", "domain": "auth.suno.com"},
           {"name": "suno_device_id", "value": '"dev-9"', "domain": "suno.com"}]
    assert sess.pick_login(jar) == ("live", "dev-9")
    with pytest.raises(sess.LoginNeeded):
        sess.pick_login([{"name": "other", "value": "x", "domain": "suno.com"}])


def test_decrypt_cookie_reads_v10_with_and_without_the_domain_hash():
    pytest.importorskip("cryptography")
    import hashlib

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key, host = b"k" * 16, "auth.suno.com"

    def seal(plain: bytes) -> bytes:
        pad = 16 - len(plain) % 16
        enc = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
        return b"v10" + enc.update(plain + bytes([pad]) * pad) + enc.finalize()

    assert sess.decrypt_cookie(seal(hashlib.sha256(host.encode()).digest() + b"value-1"), key, host) == "value-1"
    assert sess.decrypt_cookie(seal(b"value-2"), key, host) == "value-2"  # before Chrome 130: no prefix
    long_old = b"an-older-cookie-value-that-is-longer-than-thirty-two-bytes"
    assert sess.decrypt_cookie(seal(long_old), key, host) == long_old.decode()  # never cut blindly
    assert sess.decrypt_cookie(b"", key, host) is None
    with pytest.raises(RuntimeError):
        sess.decrypt_cookie(b"v20whatever", key, host)


def test_user_id_is_the_uuid_claim_not_the_short_number():
    # The short `suno/user_id` number matches no clip; a library filter built from it is empty.
    assert make_session().user_id() == USER


def test_token_is_cached_then_minted_again_when_old():
    transport = FakeTransport((200, {"jwt": make_jwt(n=2)}))
    now = [1000 + sess.JWT_MAX_AGE - 1]
    s = sess.Session(transport=transport, state={"client": "c", "session_id": "sess_1", "jwt": JWT, "jwt_at": 1000},
                     reimport=None, clock=lambda: now[0], persist=False)
    assert s.token() == JWT and not transport.calls
    now[0] += 5
    assert s.token() == make_jwt(n=2)
    method, url, _, headers = transport.calls[0]
    assert method == "POST" and "/v1/client/sessions/sess_1/tokens" in url
    assert headers["cookie"] == "__client=c"


def test_a_dead_cookie_is_imported_again_once():
    transport = FakeTransport((401, {}), (200, {"response": {"last_active_session_id": "sess_2"}}),
                              (200, {"jwt": make_jwt(n=3)}))
    s = sess.Session(transport=transport, state={"client": "dead", "session_id": "sess_1"},
                     reimport=lambda: {"client": "fresh"}, clock=lambda: 5000, persist=False)
    assert s.token() == make_jwt(n=3)
    assert s.state["client"] == "fresh" and s.state["session_id"] == "sess_2"


def test_no_login_and_no_browser_is_login_needed():
    s = sess.Session(transport=FakeTransport(), state={}, reimport=None, persist=False)
    with pytest.raises(sess.LoginNeeded):
        s.token()


# -- client plumbing ---------------------------------------------------------------------------


def test_headers_carry_the_bearer_device_and_browser_token():
    client, transport = make_client((200, {"ok": True}))
    client.call("GET", "/billing/info/")
    headers = transport.calls[0][3]
    assert headers["authorization"] == f"Bearer {JWT}"
    assert headers["device-id"] == "dev-1"
    inner = json.loads(base64.b64decode(json.loads(headers["browser-token"])["token"]))
    assert inner == {"timestamp": 1001000}
    assert json.loads(browser_token(5))["token"] == base64.b64encode(b'{"timestamp":5}').decode()


def test_reads_retry_on_429_and_5xx():
    client, transport = make_client((429, {"detail": "Too many requests.", "error_type": "rate_limited"}),
                                    (502, "bad gateway"), (200, {"n": 1}))
    assert client.call("GET", "/billing/info/") == {"n": 1}
    assert len(transport.calls) == 3


def test_reads_give_up_after_four_tries():
    client, transport = make_client(*[(429, {"detail": "Too many requests."})] * 4)
    with pytest.raises(RateLimited):
        client.call("GET", "/billing/info/")
    assert len(transport.calls) == 4


@pytest.mark.parametrize("answer,error", [((429, {"detail": "Too many requests."}), RateLimited),
                                          ((500, {"detail": "boom"}), OutcomeUnknown),
                                          (TimeoutError("timed out"), OutcomeUnknown)])
def test_a_paid_post_is_sent_once_whatever_comes_back(answer, error):
    client, transport = make_client(answer)
    with pytest.raises(error):
        client.call("POST", "/generate/v2-web/", {"x": 1}, spends=True)
    assert len(transport.calls) == 1


def test_a_rejected_token_is_refreshed_and_the_request_resent_once():
    client, transport = make_client((401, {"detail": "Token validation failed."}), (200, {"ok": True}))
    client.session.transport = FakeTransport((200, {"jwt": make_jwt(n=9)}))
    assert client.call("POST", "/generate/v2-web/", {"x": 1}, spends=True) == {"ok": True}
    assert transport.calls[1][3]["authorization"] == f"Bearer {make_jwt(n=9)}"


def test_a_token_rejected_twice_is_an_auth_error():
    client, _ = make_client((401, {}), (401, {}))
    client.session.transport = FakeTransport((200, {"jwt": make_jwt(n=9)}))
    with pytest.raises(AuthRejected):
        client.call("GET", "/billing/info/")


def test_422_field_errors_are_drift_and_other_refusals_are_not():
    client, _ = make_client((422, {"detail": [{"loc": ["body", "params", "title"], "msg": "none is not allowed"}]}))
    with pytest.raises(SchemaDrift):
        client.call("POST", "/generate/v2-web/", {}, spends=True)
    client, _ = make_client((422, {"detail": "Lyrics were flagged."}))
    with pytest.raises(Rejected):
        client.call("POST", "/generate/v2-web/", {}, spends=True)
    client, _ = make_client((404, {"detail": "Not found."}))
    with pytest.raises(NotFound):
        client.call("GET", "/clip/nope")


# -- library -----------------------------------------------------------------------------------


def test_feed_filters_match_the_website_and_carry_the_user_uuid():
    client, transport = make_client((200, {"clips": [], "has_more": False}))
    client.feed_page(search="rain")
    body = transport.calls[0][2]
    assert body["limit"] == 20 and body["cursor"] is None
    assert body["filters"]["user"] == {"presence": "True", "userId": USER}
    assert body["filters"]["trashed"] == "False" and body["filters"]["searchText"] == "rain"
    assert body["filters"]["stem"] == {"presence": "False"}


def test_library_follows_the_cursor_and_stops_at_the_limit():
    pages = [(200, {"clips": [raw_clip(f"{i:08d}-0000-0000-0000-000000000000") for i in range(a, a + 20)],
                    "has_more": True, "next_cursor": f"cur{a}"}) for a in (0, 20, 40)]
    client, transport = make_client(*pages)
    got = list(client.library(limit=45))
    assert len(got) == 45
    assert [c[2]["cursor"] for c in transport.calls] == [None, "cur0", "cur20"]


def test_clips_are_asked_for_two_at_a_time():
    client, transport = make_client((200, [raw_clip("a"), raw_clip("b")]), (200, [raw_clip("c")]))
    assert [c["id"] for c in client.clips(["a", "b", "c"])] == ["a", "b", "c"]
    assert transport.paths() == ["/feed/?ids=a,b", "/feed/?ids=c"]


def test_wait_needs_every_id_terminal():
    streaming, done = raw_clip(CLIP_B, status="streaming"), raw_clip(CLIP_B)
    client, _ = make_client((200, [raw_clip(CLIP_A)]), (200, [raw_clip(CLIP_A), streaming]),
                            (200, [raw_clip(CLIP_A), done]))
    ticks = []
    final = client.wait([CLIP_A, CLIP_B], on_tick=lambda state: ticks.append([c["status"] for c in state]))
    assert [c["status"] for c in final] == ["complete", "complete"]
    assert ticks == [["complete"], ["complete", "streaming"], ["complete", "complete"]]


# -- downloads ---------------------------------------------------------------------------------


def test_prepare_polls_until_ready():
    client, transport = make_client((200, {"ok": True, "status": "processing"}),
                                    (200, {"ok": True, "status": "ready", "download_url": "https://files.invalid/a.mp3?sig=1"}))
    assert client.prepare_download(CLIP_A, "mp3") == "https://files.invalid/a.mp3?sig=1"
    assert transport.paths() == [f"/download/clip/{CLIP_A}?format=mp3"] * 2


def test_prepare_on_a_locked_clip_raises_and_spends_nothing():
    client, transport = make_client((200, {"ok": False, "reason": "not_authorized", "message": "no"}))
    with pytest.raises(NotAuthorized):
        client.prepare_download(CLIP_A)
    assert transport.paths("POST") == []


def test_wav_asks_for_a_conversion_once():
    client, transport = make_client((200, {"wav_file_url": None}), (200, None), (200, {"wav_file_url": None}),
                                    (200, {"wav_file_url": "https://files.invalid/a.wav"}))
    assert client.prepare_download(CLIP_A, "wav") == "https://files.invalid/a.wav"
    assert transport.paths("POST") == [f"/gen/{CLIP_A}/convert_wav/"]


# -- request bodies ----------------------------------------------------------------------------


def custom(**over) -> dict:
    args = dict(mode="custom", model_key="chirp-hawk", title="T", tags="piano", text="[Verse]\nLine", plan_id=PLAN)
    args.update(over)
    return model.generate_payload(**args)


@pytest.mark.parametrize("mode,kwargs", [("custom", {}), ("simple", {})])
def test_payload_key_sets_are_the_captured_ones(mode, kwargs):
    payload = custom() if mode == "custom" else model.generate_payload(mode="simple", model_key="chirp-hawk",
                                                                      text="a quiet song", plan_id=PLAN)
    assert set(payload) == model.KEYS[mode]
    assert set(payload["metadata"]) == model.METADATA_KEYS[mode]
    assert payload["metadata"]["create_mode"] == mode and payload["metadata"]["user_tier"] == PLAN


def test_simple_mode_carries_the_description_apart_from_the_prompt():
    payload = model.generate_payload(mode="simple", model_key="chirp-hawk", text="a quiet song", plan_id=PLAN)
    assert payload["task"] == "agentic_thinking" and payload["prompt"] == ""
    assert payload["gpt_description_prompt"] == "a quiet song"
    assert "title" not in payload and "tags" not in payload
    with pytest.raises(InputError):
        model.generate_payload(mode="simple", model_key="chirp-hawk", text="x", tags="piano")
    with pytest.raises(InputError):
        model.generate_payload(mode="simple", model_key="chirp-hawk", text="  ")


def test_custom_mode_rules():
    assert custom(instrumental=True)["prompt"] == "" and custom(instrumental=True)["make_instrumental"] is True
    assert custom(title="")["title"] == ""  # empty string, never null
    sliders = custom(weirdness=30, style_influence=70)["metadata"]["control_sliders"]
    assert sliders == {"aug_creativity": 1, "weirdness_constraint": 0.3, "style_weight": 0.7}
    with pytest.raises(InputError):
        custom(text="", instrumental=False)
    with pytest.raises(InputError):
        custom(weirdness=101)
    with pytest.raises(InputError):
        custom(text="", tags="")


def test_limits_count_utf16_units():
    assert model.utf16_len("a\U0001F3B5") == 3
    with pytest.raises(InputError):
        custom(title="\U0001F3B5" * 51)  # 102 units
    custom(title="\U0001F3B5" * 50)
    with pytest.raises(InputError):
        custom(tags="x" * 11, limits={"tags": 10})


def test_with_token_always_keeps_the_provider_key():
    assert model.with_token(custom(), "tok", 2)["token_provider"] == 2
    bare = model.with_token(custom(), None, 2)
    assert bare["token"] is None and bare["token_provider"] is None


def test_model_names_resolve_against_the_account():
    b = billing()
    assert model.resolve_model("v6", b) == "chirp-hawk" and model.resolve_model("CHIRP-HAWK", b) == "chirp-hawk"
    assert model.default_model(b) == "chirp-hawk"
    with pytest.raises(InputError):
        model.resolve_model("v6-wild", b)  # in the catalogue, not in the plan
    with pytest.raises(InputError):
        model.resolve_model("v3", b)
    assert model.resolve_model("v6-mini", None) == "chirp-goose"


@pytest.mark.parametrize("ref,want", [(CLIP_A.upper(), CLIP_A), (f"https://suno.com/song/{CLIP_A}?sh=x", CLIP_A),
                                      ("0a0a0a0a", "0a0a0a0a")])
def test_parse_clip_ref(ref, want):
    assert model.parse_clip_ref(ref) == want


def test_parse_clip_ref_rejects_junk():
    with pytest.raises(InputError):
        model.parse_clip_ref("not an id")


def test_normalize_clip_and_names():
    clip = model.normalize_clip(raw_clip(title="Søng: Nº 1!", is_download_unlocked=True))
    assert clip["unlocked"] and clip["url"] == f"https://suno.com/song/{CLIP_A}"
    assert model.folder_name(clip) == "sng-no-1-0a0a0a0a"  # NFKD turns the numero sign into "No"
    assert model.fmt_duration(61.5) == "1:02" and model.fmt_duration(None) == "-"
    assert model.slug("!!!") == "song"


# -- timed lyrics ------------------------------------------------------------------------------


def test_lrc_from_line_timings():
    aligned = {"aligned_lyrics": [{"text": "First made-up line", "start_s": 1.208, "end_s": 4.5, "section": "Verse 1"},
                                  {"text": "Second made-up line", "start_s": 65.0, "end_s": 68.0, "section": "Verse 1"}]}
    assert model.to_lrc(aligned, "T") == "[ti:T]\n[00:01.21]First made-up line\n[01:05.00]Second made-up line\n"


def test_lines_are_rebuilt_from_words_for_older_clips():
    aligned = {"aligned_words": [{"word": "[Verse]\nOne ", "start_s": 1.0, "end_s": 1.4, "p_align": 0.9},
                                 {"word": "two\n", "start_s": 1.5, "end_s": 2.0, "p_align": 0.9},
                                 {"word": "Three", "start_s": 3.0, "end_s": 3.5, "p_align": 0.8}]}
    lines = model.timed_lines(aligned)
    assert [(line["text"], line["start"]) for line in lines] == [("One two", 1.0), ("Three", 3.0)]
    assert [w["text"] for w in model.timed_words(aligned)] == ["One", "two", "Three"]


# -- receipts ----------------------------------------------------------------------------------


def test_fingerprint_ignores_what_changes_on_every_send():
    a, b = custom(), custom()
    assert a["transaction_uuid"] != b["transaction_uuid"]
    assert fingerprint(a) == fingerprint(model.with_token(b, "tok", 2))
    assert fingerprint(a) != fingerprint(custom(tags="harp"))


def test_ledger_reuses_blocks_and_expires(tmp_path):
    now = [10_000.0]
    ledger = Ledger(tmp_path, clock=lambda: now[0])
    first = custom(request_id="req-1")
    assert ledger.check(first) is None
    receipt = ledger.open(first, {"title": "T"})
    with pytest.raises(Blocked):  # sent, no answer recorded yet
        ledger.check(first)
    ledger.close(receipt, "submitted", ids=[CLIP_A, CLIP_B])
    assert ledger.check(custom(request_id="req-1"))["ids"] == [CLIP_A, CLIP_B]
    with pytest.raises(Blocked):  # same id, other content
        ledger.check(custom(request_id="req-1", tags="harp"))
    with pytest.raises(Blocked):  # same content, new id, inside the window
        ledger.check(custom(request_id="req-2"))
    assert ledger.check(custom(request_id="req-2"), force=True) is None
    now[0] += 31 * 60
    assert ledger.check(custom(request_id="req-2")) is None
    assert "Line" not in (tmp_path / "receipts" / "req-1.json").read_text()  # no lyrics in a receipt


def test_a_rejected_request_does_not_block_a_second_try(tmp_path):
    ledger = Ledger(tmp_path, clock=lambda: 1.0)
    ledger.close(ledger.open(custom(request_id="req-1"), {}), "rejected")
    assert ledger.check(custom(request_id="req-2")) is None


# -- the CLI's spend gates ---------------------------------------------------------------------


def run(argv, client, tmp_path, fetch=None):
    ctx = cli.Ctx(client=client, ledger=Ledger(tmp_path), fetch=fetch or (lambda url, dest: 0))
    return cli.main(argv, ctx)


GEN = ["generate", "--title", "T", "--tags", "piano", "--instrumental"]


def test_generate_without_yes_sends_nothing(tmp_path, capsys):
    client, transport = make_client((200, billing()))
    assert run(GEN, client, tmp_path) == 4
    assert transport.paths("POST") == []
    assert "Pass --yes" in capsys.readouterr().err


def test_generate_dry_run_never_checks_the_gate_or_sends(tmp_path, capsys):
    client, transport = make_client((200, billing()))
    assert run(GEN + ["--dry-run"], client, tmp_path) == 0
    assert transport.paths("POST") == []
    assert json.loads(capsys.readouterr().out)["would_send"]["make_instrumental"] is True


def test_generate_sends_once_and_records_the_spend(tmp_path, capsys):
    client, transport = make_client((200, billing(500)), (200, {"required": False}),
                                    (200, {"clips": [raw_clip(CLIP_A, status="submitted"), raw_clip(CLIP_B, status="submitted")]}),
                                    (200, billing(490)))
    assert run(GEN + ["--yes", "--request-id", "req-1"], client, tmp_path) == 0
    assert transport.paths("POST") == ["/c/check", "/generate/v2-web/"]
    sent = transport.calls[2][2]
    assert sent["transaction_uuid"] == "req-1" and sent["token"] is None and sent["token_provider"] is None
    receipt = json.loads((tmp_path / "receipts" / "req-1.json").read_text())
    assert receipt["state"] == "submitted" and receipt["ids"] == [CLIP_A, CLIP_B]
    assert (receipt["credits_before"], receipt["credits_after"]) == (500, 490)
    spend = json.loads((tmp_path / "spend.jsonl").read_text())
    assert spend["kind"] == "generate" and spend["credits_before"] - spend["credits_after"] == 10
    assert "10 spent" in capsys.readouterr().err

    # The same request id again: the saved clips come back and no POST goes out.
    client2, transport2 = make_client((200, billing(490)), (200, [raw_clip(CLIP_A), raw_clip(CLIP_B)]))
    assert run(GEN + ["--yes", "--request-id", "req-1"], client2, tmp_path) == 0
    assert transport2.paths("POST") == []


def test_generate_with_no_answer_is_exit_6_and_blocks_a_repeat(tmp_path):
    client, _ = make_client((200, billing()), (200, {"required": False}), TimeoutError("timed out"))
    assert run(GEN + ["--yes", "--request-id", "req-1"], client, tmp_path) == 6
    assert json.loads((tmp_path / "receipts" / "req-1.json").read_text())["state"] == "unknown"
    client2, transport2 = make_client((200, billing()))
    assert run(GEN + ["--yes", "--request-id", "req-2"], client2, tmp_path) == 4
    assert transport2.paths("POST") == []


def test_generate_refused_by_suno_leaves_a_rejected_receipt(tmp_path):
    client, _ = make_client((200, billing()), (200, {"required": False}),
                            (422, {"detail": [{"loc": ["body", "params", "x"], "msg": "field required"}]}))
    assert run(GEN + ["--yes", "--request-id", "req-1"], client, tmp_path) == 5
    assert json.loads((tmp_path / "receipts" / "req-1.json").read_text())["state"] == "rejected"


def test_generate_with_too_few_credits_is_blocked(tmp_path):
    client, transport = make_client((200, billing(credits=4)))
    assert run(GEN + ["--yes"], client, tmp_path) == 4
    assert transport.paths("POST") == []


def test_a_version_1_bot_check_blocks_before_anything_is_sent(tmp_path):
    client, transport = make_client((200, billing()), (200, {"required": True, "captcha_version": 1}))
    assert run(GEN + ["--yes"], client, tmp_path) == 4
    assert transport.paths("POST") == ["/c/check"]
    assert not (tmp_path / "receipts").exists()


def test_describe_builds_the_simple_request(tmp_path):
    client, transport = make_client((200, billing()), (200, {"required": False}),
                                    (200, {"clips": [raw_clip(CLIP_A)]}), (200, billing(490)))
    assert run(["describe", "a quiet made-up song", "--yes"], client, tmp_path) == 0
    sent = transport.calls[2][2]
    assert sent["task"] == "agentic_thinking" and sent["gpt_description_prompt"] == "a quiet made-up song"
    assert sent["metadata"]["create_mode"] == "simple" and set(sent) == model.KEYS["simple"]


def test_download_of_a_locked_clip_needs_yes_and_does_not_unlock(tmp_path, capsys):
    client, transport = make_client((200, raw_clip()), (200, billing()))
    assert run(["download", CLIP_A], client, tmp_path) == 4
    assert transport.paths("POST") == []
    assert "costs 1 download: 20 of 20 left" in capsys.readouterr().err


def test_download_with_no_downloads_left_is_blocked(tmp_path):
    client, transport = make_client((200, raw_clip()), (200, billing(used=20, extra=0)))
    assert run(["download", CLIP_A, "--yes"], client, tmp_path) == 4
    assert transport.paths("POST") == []


def test_download_unlocks_once_then_saves_the_file_and_sidecars(tmp_path, capsys):
    saved = {}

    def fetch(url, dest):
        saved["url"] = url
        dest.write_bytes(b"ID3fake")
        return 7

    client, transport = make_client(
        (200, raw_clip()), (200, billing(used=0)), (200, {"ok": True}), (200, billing(used=1)),
        (200, {"ok": True, "status": "ready", "download_url": "https://files.invalid/a.mp3?sig=1"}),
        (200, {"aligned_lyrics": [{"text": "A made-up line", "start_s": 2.0, "end_s": 4.0}]}))
    out_dir = tmp_path / "out"
    assert run(["download", CLIP_A, "--yes", "--out", str(out_dir), "--json"], client, tmp_path, fetch) == 0
    assert transport.paths("POST") == ["/download/authorize"]
    assert transport.calls[2][2] == {"item_id": CLIP_A, "item_type": "clip"}
    record = json.loads(capsys.readouterr().out)
    assert record["unlock_spent"] is True and record["path"] == str(out_dir / "test-song.mp3")
    assert record["embed"] == f"![Test Song]({out_dir / 'test-song.mp3'})"
    assert (out_dir / "test-song.mp3").read_bytes() == b"ID3fake"
    assert (out_dir / "lyrics.lrc").read_text() == "[ti:Test Song]\n[00:02.00]A made-up line\n"
    assert json.loads((out_dir / "meta.json").read_text())["id"] == CLIP_A
    spend = json.loads((tmp_path / "spend.jsonl").read_text())
    assert spend["kind"] == "download" and (spend["left_before"], spend["left_after"]) == (20, 19)


def test_download_of_an_unlocked_clip_is_free(tmp_path):
    client, transport = make_client(
        (200, raw_clip(is_download_unlocked=True, metadata={"duration": 10, "make_instrumental": True})),
        (200, {"ok": True, "status": "ready", "download_url": "https://files.invalid/a.mp3"}))
    assert run(["download", CLIP_A, "--out", str(tmp_path / "o")], client, tmp_path,
               lambda url, dest: dest.write_bytes(b"x") or 1) == 0
    assert transport.paths("POST") == [] and not (tmp_path / "spend.jsonl").exists()


def test_short_ids_resolve_from_what_was_listed(tmp_path):
    old = raw_clip("deadbeef-0000-0000-0000-000000000000", title="Old One")
    client, _ = make_client((200, {"clips": [old], "has_more": False}), (200, old))
    ctx = cli.Ctx(client=client, ledger=Ledger(tmp_path))
    assert cli.main(["list", "-s", "old"], ctx) == 0
    assert cli.main(["info", "deadbeef"], ctx) == 0  # no library scan: the id was remembered


def test_restore_looks_for_a_short_id_in_the_trash(tmp_path):
    client, transport = make_client((200, {"clips": [raw_clip(is_trashed=True)], "has_more": False}), (200, {}))
    assert run(["restore", "0a0a0a0a"], client, tmp_path) == 0
    assert transport.calls[0][2]["filters"]["trashed"] == "True"
    assert transport.calls[1][2] == {"clip_ids": [CLIP_A], "trash": False}


def test_raw_refuses_the_paid_routes(tmp_path):
    client, transport = make_client()
    assert run(["raw", "POST", "/generate/v2-web/", "{}"], client, tmp_path) == 2
    assert run(["raw", "POST", "/download/authorize", "{}"], client, tmp_path) == 2
    assert transport.calls == []


def test_status_reports_suno_numbers(tmp_path, capsys):
    client, _ = make_client((200, billing(credits=1940, used=3)), (200, {"required": True, "captcha_version": 2}))
    assert run(["status", "--json"], client, tmp_path) == 0
    record = json.loads(capsys.readouterr().out)
    assert (record["credits_left"], record["downloads_left"], record["downloads_extra"]) == (1940, 17, 6)
    assert record["handle"] == "tester" and "example.invalid" not in json.dumps(record)


# -- drift -------------------------------------------------------------------------------------


def live_capture(mode: str, **body_over) -> dict:
    body = drift.our_request(mode, "chirp-hawk", PLAN)
    body["lyrics_project_id" if mode == "custom" else "transaction_uuid"] = "f" * 8 + "-live"
    body.update(body_over)
    return {"mode": mode, "path": drift.GENERATE_PATH, "body": body, "had_token": False, "sitekeys": ["0x4AAAAAAAAAAAAAAAAAAAAA"],
            "device_id": "dev-1"}


@pytest.mark.parametrize("mode", model.MODES)
def test_drift_compare_is_quiet_when_in_step(mode):
    assert drift.compare(live_capture(mode), PLAN, "dev-1", "0x4AAAAAAAAAAAAAAAAAAAAA") == []


def test_drift_compare_reports_each_kind_of_change():
    grown = live_capture("custom", new_field=1)
    del grown["body"]["negative_tags"]
    grown["body"]["metadata"]["create_mode"] = "advanced"
    grown["body"]["override_fields"] = {}
    grown["path"] = "/a/api/generate/v3-web/"
    problems = "\n".join(drift.compare(grown, PLAN, "dev-other", "0x4OLDKEYOLDKEYOLDKEYOLD"))
    for expected in ("top_missing_here: new_field", "top_extra_here: negative_tags", "metadata.create_mode",
                     "override_fields: live sends", "route is /a/api/generate/v3-web/", "device-id header",
                     "Turnstile site key"):
        assert expected in problems
    assert drift.compare(live_capture("simple", task="agentic_v2"), PLAN, "dev-1", "0x4AAAAAAAAAAAAAAAAAAAAA") == [
        "[simple] task: live value 'agentic_v2', here 'agentic_thinking'"]


# -- the official interface: sign-in and MCP ---------------------------------------------------


class HeaderFake:
    """Like FakeTransport, for the transport that also returns response headers."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        status, resp_headers, payload = self.responses.pop(0)
        return status, resp_headers, (payload if isinstance(payload, bytes) else json.dumps(payload).encode())


RESOURCE_META = {"authorization_servers": ["https://as.invalid/api/oauth"],
                 "scopes_supported": ["credits:spend", "download", "offline_access"]}
AS_META = {"authorization_endpoint": "https://as.invalid/api/oauth/authorize/",
           "token_endpoint": "https://as.invalid/api/oauth/token/",
           "registration_endpoint": "https://as.invalid/api/oauth/register/",
           "revocation_endpoint": "https://as.invalid/api/oauth/revoke_token/",
           "code_challenge_methods_supported": ["S256"]}
JSON_H = {"content-type": "application/json"}


def test_pkce_challenge_is_the_s256_of_the_verifier():
    import hashlib

    verifier, challenge = official.pkce_pair()
    want = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == want and "=" not in challenge and len(verifier) >= 43


def test_discover_reads_both_documents_and_needs_s256():
    transport = HeaderFake((200, JSON_H, RESOURCE_META), (200, JSON_H, AS_META))
    meta = official.discover(transport)
    assert meta["token_endpoint"].endswith("/token/") and meta["scopes_for_resource"] == RESOURCE_META["scopes_supported"]
    assert transport.calls[0][1] == official.RESOURCE_METADATA
    assert transport.calls[1][1] == "https://as.invalid/.well-known/oauth-authorization-server/api/oauth"
    weak = dict(AS_META, code_challenge_methods_supported=["plain"])
    with pytest.raises(official.McpError):
        official.discover(HeaderFake((200, JSON_H, RESOURCE_META), (200, JSON_H, weak)))


def test_sign_in_registers_opens_the_browser_and_trades_the_code():
    from urllib.parse import parse_qs, urlsplit

    transport = HeaderFake((200, JSON_H, RESOURCE_META), (200, JSON_H, AS_META),
                           (201, JSON_H, {"client_id": "dcr-test"}),
                           (200, JSON_H, {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 600,
                                          "scope": "credits:spend download"}))
    opened, seen_state = [], []

    def waiter(state):
        seen_state.append(state)
        return "code-1"

    state = official.sign_in(transport, opener=opened.append, waiter=waiter, clock=lambda: 1000.0,
                             persist=False, state={})
    query = parse_qs(urlsplit(opened[0]).query)
    assert query["client_id"] == ["dcr-test"] and query["redirect_uri"] == [official.REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"] and query["resource"] == [official.MCP_URL]
    assert query["scope"] == ["credits:spend download offline_access"] and query["state"] == seen_state
    form = parse_qs(transport.calls[3][2].decode())
    assert form["grant_type"] == ["authorization_code"] and form["code"] == ["code-1"]
    import hashlib

    digest = hashlib.sha256(form["code_verifier"][0].encode()).digest()
    assert base64.urlsafe_b64encode(digest).decode().rstrip("=") == query["code_challenge"][0]
    assert (state["access_token"], state["refresh_token"], state["expires_at"]) == ("at-1", "rt-1", 1600)


def test_sign_in_reuses_a_registered_client_and_stores_nothing_when_refused():
    transport = HeaderFake((200, JSON_H, RESOURCE_META), (200, JSON_H, AS_META))

    def refused(state):
        raise official.NotConnected("not available for the account")

    with pytest.raises(official.NotConnected):
        official.sign_in(transport, opener=lambda url: None, waiter=refused, persist=False,
                         state={"client_id": "dcr-kept"})
    assert len(transport.calls) == 2  # no registration, no token request


def auth_state(**over) -> dict:
    state = {"client_id": "dcr-test", "token_endpoint": AS_META["token_endpoint"], "access_token": "at-1",
             "refresh_token": "rt-1", "expires_at": 2000}
    state.update(over)
    return state


def test_access_token_is_reused_then_refreshed():
    transport = HeaderFake((200, JSON_H, {"access_token": "at-2", "expires_in": 600}))
    now = [1000.0]
    auth = official.OfficialAuth(transport, auth_state(), clock=lambda: now[0], persist=False)
    assert auth.token() == "at-1" and not transport.calls
    now[0] = 1950.0  # less than a minute left
    assert auth.token() == "at-2"
    assert b"grant_type=refresh_token" in transport.calls[0][2] and b"refresh_token=rt-1" in transport.calls[0][2]
    assert auth.state["refresh_token"] == "rt-1" and auth.state["expires_at"] == 2550


def test_a_refused_refresh_or_no_sign_in_is_not_connected():
    auth = official.OfficialAuth(HeaderFake((400, JSON_H, {"error": "invalid_grant"})), auth_state(expires_at=0),
                                 clock=lambda: 1000.0, persist=False)
    with pytest.raises(official.NotConnected):
        auth.token()
    with pytest.raises(official.NotConnected):
        official.OfficialAuth(HeaderFake(), {"client_id": "dcr-test"}, persist=False).token()


def test_parse_rpc_reads_json_and_event_streams():
    body = json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"ok": 1}}).encode()
    assert official.parse_rpc("application/json", body, 3)["result"] == {"ok": 1}
    stream = (b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
              b'event: message\r\ndata: {"jsonrpc":"2.0","id":3,\r\ndata: "result":{"ok":2}}\r\n\r\n')
    assert official.parse_rpc("text/event-stream; charset=utf-8", stream, 3)["result"] == {"ok": 2}
    with pytest.raises(official.McpError):
        official.parse_rpc("application/json", body, 4)


def rpc(result, rid, headers=None):
    return 200, {**JSON_H, **(headers or {})}, {"jsonrpc": "2.0", "id": rid, "result": result}


READ_TOOL = {"name": "get_credits", "description": "Show the balance.", "annotations": {"readOnlyHint": True}}
PAID_TOOL = {"name": "create_song", "description": "Make a song.\nSpends credits."}


def make_mcp(*responses, state=None):
    transport = HeaderFake(*responses)
    auth = official.OfficialAuth(HeaderFake(), state or auth_state(), clock=lambda: 1000.0, persist=False)
    return official.McpClient(auth, transport), transport


def test_mcp_handshake_paging_and_headers():
    mcp, transport = make_mcp(
        rpc({"protocolVersion": "2025-03-26", "serverInfo": {"name": "Test"}}, 1, {"mcp-session-id": "s-1"}),
        (202, {}, b""), rpc({"tools": [READ_TOOL], "nextCursor": "c2"}, 2), rpc({"tools": [PAID_TOOL]}, 3),
        rpc({"content": [{"type": "text", "text": '{"credits": 5}'}]}, 4))
    assert [t["name"] for t in mcp.tools()] == ["get_credits", "create_song"]
    assert json.loads(transport.calls[1][2]) == {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert json.loads(transport.calls[3][2])["params"] == {"cursor": "c2"}
    later = transport.calls[2][3]
    assert later["mcp-session-id"] == "s-1" and later["mcp-protocol-version"] == "2025-03-26"
    assert later["authorization"] == "Bearer at-1" and "mcp-session-id" not in transport.calls[0][3]
    assert mcp.call("get_credits")["data"] == {"credits": 5}
    assert json.loads(transport.calls[4][2])["params"] == {"name": "get_credits", "arguments": {}}


def test_mcp_errors_surface_and_a_dead_token_is_replaced_once():
    mcp, _ = make_mcp(rpc({"protocolVersion": "2025-06-18"}, 1), (202, {}, b""),
                      rpc({"content": [{"type": "text", "text": "not enough credits"}], "isError": True}, 2))
    with pytest.raises(official.McpError, match="not enough credits"):
        mcp.call("create_song", {"prompt": "x"})
    mcp, _ = make_mcp((200, JSON_H, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no such method"}}))
    with pytest.raises(official.McpError, match="no such method"):
        mcp.request("nope")
    mcp, transport = make_mcp((401, JSON_H, {"error": "expired"}), rpc({"protocolVersion": "2025-06-18"}, 1))
    mcp.auth.transport = HeaderFake((200, JSON_H, {"access_token": "at-9", "expires_in": 600}))
    mcp.request("initialize", {})
    assert transport.calls[1][3]["authorization"] == "Bearer at-9"
    mcp, _ = make_mcp((401, JSON_H, {}), (401, JSON_H, {}))
    mcp.auth.transport = HeaderFake((200, JSON_H, {"access_token": "at-9", "expires_in": 600}))
    with pytest.raises(official.NotConnected):
        mcp.request("initialize", {})


HANDSHAKE = (rpc({"protocolVersion": "2025-06-18"}, 1), (202, {}, b""))


def test_call_needs_yes_unless_the_server_marks_the_tool_read_only(tmp_path, capsys):
    mcp, transport = make_mcp(*HANDSHAKE, rpc({"tools": [READ_TOOL, PAID_TOOL]}, 2))
    ctx = cli.Ctx(client=make_client()[0], ledger=Ledger(tmp_path), mcp=mcp)
    assert cli.main(["call", "create_song", '{"prompt": "x"}'], ctx) == 4
    assert all(json.loads(c[2]).get("method") != "tools/call" for c in transport.calls)
    assert "not marked read-only" in capsys.readouterr().err

    mcp, transport = make_mcp(*HANDSHAKE, rpc({"tools": [READ_TOOL, PAID_TOOL]}, 2),
                              rpc({"content": [{"type": "text", "text": '{"credits": 5}'}]}, 3))
    ctx = cli.Ctx(client=make_client()[0], ledger=Ledger(tmp_path), mcp=mcp)
    assert cli.main(["call", "get_credits"], ctx) == 0
    assert json.loads(capsys.readouterr().out) == {"credits": 5}
    assert cli.main(["call", "nope"], cli.Ctx(client=make_client()[0], ledger=Ledger(tmp_path),
                                              mcp=make_mcp(*HANDSHAKE, rpc({"tools": []}, 2))[0])) == 2


def test_tools_listing_and_the_not_connected_exits(tmp_path, capsys, monkeypatch):
    mcp, _ = make_mcp(*HANDSHAKE, rpc({"tools": [READ_TOOL, PAID_TOOL]}, 2))
    assert cli.main(["tools"], cli.Ctx(client=make_client()[0], ledger=Ledger(tmp_path), mcp=mcp)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "read-only" in lines[0] and "spends/changes" in lines[1] and "Spends credits" not in lines[1]

    monkeypatch.setattr(official, "OAUTH_PATH", tmp_path / "oauth.json")
    assert cli.main(["connect", "--status"], cli.Ctx(client=make_client()[0], ledger=Ledger(tmp_path))) == 3
    unsigned = official.McpClient(official.OfficialAuth(HeaderFake(), {}, persist=False), HeaderFake())
    assert cli.main(["tools"], cli.Ctx(client=make_client()[0], ledger=Ledger(tmp_path), mcp=unsigned)) == 3
