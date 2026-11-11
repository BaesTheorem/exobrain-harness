"""Compare this client's generate requests with the ones the live Create form builds.

Suno changes its web API without notice, and a wrong request shape fails only at the moment
credits are about to be spent. This check asks the real client: it opens suno.com/create in a
headless Chrome with the browser's own login, fills the form with a fixed test song, presses
Create, and stops the request inside the browser. It does that once for each tab of the form
(Advanced and Simple). Each captured body is then compared key by key with what
``model.generate_payload`` builds for the same input.

INVARIANTS:
- Nothing is submitted and no credits are spent. From the moment the form is filled, every
  write to a Suno API route that is not on ``SAFE_WRITES`` is aborted before it leaves the
  browser. The generate POST is one of them.
- The Advanced tab autosaves typed lyrics as a draft in the account ("Saved lyrics"). The
  check deletes every draft whose text is exactly ``PROBE_LYRICS``, and no other draft.
- Headless only. The login cookies are read from the browser at run time and are not stored.
- The captcha token in a captured body is dropped at once. It is never printed or saved.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sunocli import model, session as sess
from sunocli.api import SunoClient, SunoError

Json = dict[str, Any]

CREATE_URL = "https://suno.com/create"
GENERATE_PATH = "/a/api/generate/v2-web/"
# Writes the page makes on its own that change nothing: reads done as POST, and telemetry.
SAFE_WRITES = ("/api/c/check", "/api/feed/v3", "/api/unified/feed", "/api/realtime/token",
               "/api/statsig/", "/api/user/user_config", "/api/video_gen/pending_batches",
               "/api/notification", "/api/prompts")
PROBE_TITLE = "drift check"
PROBE_STYLE = "solo piano, slow"
PROBE_LYRICS = "[Verse]\nThis line is a test of the form\nNothing is sent from here"
PROBE_DESCRIPTION = "a slow solo piano piece, a test of the form"
SITEKEY_RE = re.compile(r"0x4[A-Za-z0-9_-]{18,}")
# Values that must be equal on both sides for the same input, by mode.
SAME_VALUES = {
    "custom": ("generation_type", "title", "tags", "negative_tags", "prompt", "make_instrumental",
               "override_fields"),
    "simple": ("task", "generation_type", "prompt", "gpt_description_prompt", "make_instrumental",
               "override_fields"),
}
SAME_METADATA = {
    "custom": ("web_client_pathname", "create_surface", "create_mode", "user_tier", "control_sliders",
               "is_max_mode", "is_mumble"),
    "simple": ("web_client_pathname", "create_surface", "create_mode", "user_tier", "lyrics_model",
               "is_max_mode", "is_mumble"),
}


class FormChanged(RuntimeError):
    """The Create page no longer has a control this check drives."""


def _fill(page: Any, mode: str) -> None:
    if mode == "custom":
        page.get_by_role("tab", name="Advanced").click(timeout=30000)
        page.locator("textarea[aria-label='Styles']").first.fill(PROBE_STYLE, timeout=10000)
        page.locator("input[placeholder='Song Title (Optional)']").first.fill(PROBE_TITLE, timeout=10000)
        page.locator("[aria-label='Lyrics editor']").first.fill(PROBE_LYRICS, timeout=10000)
    else:
        page.get_by_role("tab", name="Simple").click(timeout=30000)
        page.wait_for_timeout(1500)
        page.locator("textarea:visible").first.fill(PROBE_DESCRIPTION, timeout=10000)
    page.wait_for_timeout(1500)


def capture(mode: str = "custom", browser: str = "chrome", timeout: float = 90) -> Json:
    """Drive one tab of the live form and return the generate request it built (never sent)."""
    from patchright.sync_api import Error as PlaywrightError, sync_playwright

    caught: list[Json] = []
    seen_urls: list[str] = []
    armed = {"on": False}

    def handler(route: Any, request: Any) -> None:
        url = request.url
        is_api = "suno.com/a/api/" in url or "studio-api" in url
        if armed["on"] and is_api and request.method != "GET":
            path = re.sub(r"https?://[^/]+", "", url).split("?")[0]
            if not any(safe in path for safe in SAFE_WRITES):
                caught.append({"method": request.method, "path": path, "body": request.post_data,
                               "headers": request.headers})
                route.abort("aborted")
                return
        route.continue_()

    with sync_playwright() as p:
        chrome = p.chromium.launch(channel="chrome", headless=True)
        try:
            context = chrome.new_context(user_agent=sess.user_agent(), viewport={"width": 1440, "height": 900})
            context.add_cookies(sess.browser_cookies(browser))  # type: ignore[arg-type]
            page = context.new_page()
            page.route("**/*", handler)
            page.on("request", lambda r: seen_urls.append(r.url))
            page.goto(CREATE_URL, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            try:
                _fill(page, mode)
                button = page.get_by_role("button", name="Create song").first
                if button.is_disabled():
                    raise FormChanged("the Create button stayed disabled after the form was filled")
                armed["on"] = True
                button.click(timeout=10000)
            except PlaywrightError as err:
                raise FormChanged(f"a control on the Create page was not found ({str(err).splitlines()[0]})") from err
            for _ in range(int(timeout * 2)):
                if any("/generate/" in c["path"] for c in caught):
                    break
                page.wait_for_timeout(500)
        finally:
            chrome.close()
    hit = next((c for c in caught if "/generate/" in c["path"]), None)
    if not hit:
        raise FormChanged("the form sent no generate request; blocked instead: "
                          + (", ".join(sorted({c['path'] for c in caught})) or "nothing"))
    body = json.loads(hit["body"] or "{}")
    had_token = bool(body.get("token"))
    body["token"] = None
    sitekeys = sorted({m.group(0) for u in seen_urls if "challenges.cloudflare.com" in u
                       for m in [SITEKEY_RE.search(u)] if m})
    return {"mode": mode, "path": hit["path"], "body": body, "had_token": had_token, "sitekeys": sitekeys,
            "device_id": hit["headers"].get("device-id")}


def remove_probe_drafts(client: SunoClient) -> int:
    """Delete the lyric drafts this check's form fill left behind. Returns how many."""
    removed = 0
    projects = (client.call("GET", "/lyrics-projects") or {}).get("projects") or []
    for project in projects:
        if str(project.get("lyrics") or "").strip() == PROBE_LYRICS:
            client.call("DELETE", f"/lyrics-projects/{project['id']}")
            removed += 1
    return removed


def our_request(mode: str, model_key: str, plan_id: str) -> Json:
    """What this client builds for the same input the check typed into the form."""
    if mode == "custom":
        return model.generate_payload(mode="custom", model_key=model_key, title=PROBE_TITLE,
                                      tags=PROBE_STYLE, text=PROBE_LYRICS, plan_id=plan_id)
    return model.generate_payload(mode="simple", model_key=model_key, text=PROBE_DESCRIPTION, plan_id=plan_id)


def compare(captured: Json, plan_id: str, device_id: str, sitekey: str) -> list[str]:
    """Every difference between the live request and this client's. Empty means in step."""
    mode, theirs = captured["mode"], captured["body"]
    ours = model.with_token(our_request(mode, str(theirs.get("mv")), plan_id),
                            "x" if captured["had_token"] else None, theirs.get("token_provider"))
    problems: list[str] = []
    if captured["path"] != GENERATE_PATH:
        problems.append(f"route is {captured['path']}, this client sends to {GENERATE_PATH}")
    for label, keys in model.key_diff(ours, theirs).items():
        problems.append(f"{label}: {', '.join(keys)}")
    ours_shape, theirs_shape = model.shape_of(ours), model.shape_of(theirs)
    for key in sorted(set(ours) & set(theirs)):
        if key in ("token", "lyrics_project_id"):  # a string in the live request, null here, by design
            continue
        if ours_shape[key] != theirs_shape[key]:
            problems.append(f"{key}: live sends {json.dumps(theirs_shape[key])}, "
                            f"this client sends {json.dumps(ours_shape[key])}")
    for key in SAME_VALUES[mode]:
        if key in ours and key in theirs and ours[key] != theirs[key]:
            problems.append(f"{key}: live value {theirs[key]!r}, here {ours[key]!r}")
    their_meta = theirs.get("metadata") or {}
    for key in SAME_METADATA[mode]:
        if key in ours["metadata"] and key in their_meta and ours["metadata"][key] != their_meta[key]:
            problems.append(f"metadata.{key}: live value {their_meta[key]!r}, here {ours['metadata'][key]!r}")
    if captured["device_id"] and captured["device_id"] != device_id:
        problems.append("the device-id header differs from the stored one; run `suno auth import`")
    if captured["sitekeys"] and sitekey not in captured["sitekeys"]:
        problems.append(f"the Turnstile site key is now {captured['sitekeys']}")
    return [f"[{mode}] {p}" for p in problems]


def report(client: SunoClient, browser: str = "chrome") -> str:
    """Run the check on both tabs. One line when in step; raises SunoError with the differences."""
    from sunocli.captcha import TURNSTILE_SITEKEY

    captures: list[Json] = []
    removed = 0
    try:
        for mode in model.MODES:
            captures.append(capture(mode, browser))
    finally:
        try:
            removed = remove_probe_drafts(client)
        except SunoError:
            removed = -1
    plan_id = str((client.billing().get("plan") or {}).get("id") or "")
    problems = [p for c in captures for p in compare(c, plan_id, client.session.device_id, TURNSTILE_SITEKEY)]
    tail = "" if removed >= 0 else (" (the test lyric draft was not removed; delete 'This line is a test "
                                    "of the form' under Saved lyrics)")
    if problems:
        raise SunoError("the live form differs: " + "; ".join(problems) + tail)
    sizes = ", ".join(f"{c['mode']} {len(c['body'])} keys" for c in captures)
    return f"in step with the live form ({sizes}; bot check {'on' if captures[0]['had_token'] else 'off'}){tail}"
