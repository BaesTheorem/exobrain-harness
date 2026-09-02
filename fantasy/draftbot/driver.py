"""Long-running ESPN draft-room driver.

Holds one Playwright browser open in a persistent profile so the Disney SSO
login survives restarts (log in by hand once; it is good for the real draft
too). MIST talks to it through files, because each of her shell calls is a
separate process and a 30-second pick clock leaves no time to boot a browser.

Protocol
    cmd.json     {"id": <int>, "op": "<name>", "arg": "<string>"}   written by MIST
    result.json  {"id": <int>, "ok": bool, "data": ...}             written by driver
    state.json   refreshed every poll: on-the-clock, my roster, timer text
    shot.png     screenshot, taken only by the `shot` op (a capture makes the
                 headful window flash, so it is never taken on the poll beat)

Ops: ping, shot, dom, search, draft, click, eval, pages, switch

The active page follows the newest tab. ESPN's mock draft lobby opens the draft
room with window.open(), so a driver pinned to ctx.pages[0] sits on the lobby
watching nothing while the draft runs in a window it cannot see.
"""

import json
import pathlib
import time
import traceback

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PROFILE = HERE / "profile"
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"
STATE = HERE / "state.json"
SHOT = HERE / "shot.png"
LOG = HERE / "driver.log"

URL = (HERE / "url.txt").read_text().strip()


def log(msg):
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        fh.flush()


def visible_text(page):
    try:
        return page.evaluate("() => document.body.innerText")
    except Exception:
        return ""


def snapshot(page):
    """Cheap poll of the things that decide the next action."""
    txt = visible_text(page)
    logged_in = "Enter your email" not in txt and "MyDisney" not in txt
    return {
        "ts": time.strftime("%H:%M:%S"),
        "url": page.url,
        "logged_in": logged_in,
        "text": txt[:4000],
    }


def op_dom(page, arg):
    """Dump interactive elements so selectors can be written against reality."""
    out = []
    for sel in ["button", "[role=button]", "input", "a[href*=draft]"]:
        for el in page.query_selector_all(sel)[:60]:
            try:
                if not el.is_visible():
                    continue
                out.append(
                    {
                        "sel": sel,
                        "text": (el.inner_text() or "").strip()[:60],
                        "class": (el.get_attribute("class") or "")[:80],
                        "placeholder": el.get_attribute("placeholder"),
                    }
                )
            except Exception:
                pass
    return out


def op_search(page, name):
    """Type a player name into the draft-room search box."""
    box = None
    for sel in [
        "input[placeholder*='Search']",
        "input[placeholder*='search']",
        "input[type='text']",
    ]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            box = el
            break
    if not box:
        return {"error": "no search box found"}
    box.click()
    box.fill("")
    box.type(name, delay=20)
    page.wait_for_timeout(1200)
    return {"typed": name, "text": visible_text(page)[:2500]}


def op_draft(page, name):
    """Search for a player, then hit the draft control on their row."""
    op_search(page, name)
    page.wait_for_timeout(600)
    for label in ["Draft", "DRAFT", "Select", "Pick"]:
        btn = page.query_selector(f"button:has-text('{label}')")
        if btn and btn.is_visible():
            btn.click()
            page.wait_for_timeout(900)
            # ESPN usually raises a confirm modal
            for conf in ["Confirm", "Yes", "Draft Player", "OK"]:
                c = page.query_selector(f"button:has-text('{conf}')")
                if c and c.is_visible():
                    c.click()
                    page.wait_for_timeout(800)
                    break
            return {"drafted": name, "via": label, "text": visible_text(page)[:1500]}
    return {"error": "no draft button", "text": visible_text(page)[:2500]}


def op_click(page, text):
    el = page.query_selector(f"text={text}")
    if not el:
        return {"error": f"no element matching {text!r}"}
    el.click()
    page.wait_for_timeout(900)
    return {"clicked": text, "text": visible_text(page)[:1500]}


def is_ours(url):
    """True for pages that could be the lobby or the draft room.

    The lobby opens ad-exchange sync tabs (sync.inmobi.com and friends) with
    window.open, which look exactly like the draft room to a follow-the-newest
    rule. Following one blinds every later command.
    """
    return "espn.com" in url or url.startswith("about:")


def op_pages(page, arg):
    ctx = page.context
    return {
        "active": page.url,
        "all": [p.url for p in ctx.pages if not p.is_closed()],
    }


def op_shot(page, arg):
    """Screenshot on demand only.

    A headful Chromium repaints visibly every time Playwright captures it, so
    the old every-poll screenshot made the window flash on a 1.5s beat for as
    long as the driver ran (reported 2026-09-02). Nothing reads shot.png but a
    human, so it is taken when a human asks.
    """
    page.screenshot(path=str(SHOT))
    return {"shot": str(SHOT)}


def op_reload(page, arg):
    """Reload the active page. The recovery for a hung draft room ('Loading
    your draft' while the clock runs) is reload + re-arm, proven 2026-08-24."""
    page.reload(wait_until="domcontentloaded", timeout=60000)
    return {"reloaded": page.url}


OPS = {
    "ping": lambda page, arg: {"pong": True, "url": page.url},
    "pages": op_pages,
    "reload": op_reload,
    "switch": None,  # bound in main(), needs the active-page cell
    "shot": op_shot,
    "dom": op_dom,
    "search": op_search,
    "draft": op_draft,
    "click": op_click,
    "eval": lambda page, arg: page.evaluate(arg),
}


def main():
    PROFILE.mkdir(exist_ok=True)
    last_id = -1
    beat = 0
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE),
            headless=False,
            viewport={"width": 1680, "height": 1020},
            args=["--window-size=1700,1060"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # Follow the newest tab. ESPN opens the draft room via window.open(),
        # and a driver pinned to the first page would keep polling the lobby.
        # But the lobby ALSO spawns ad-exchange sync tabs (sync.inmobi.com and
        # friends), and following one of those points every command at a blank
        # page that then closes under us. Only ESPN tabs count as the room.
        active = {"page": page}

        def on_page(new_page):
            try:
                new_page.wait_for_load_state("domcontentloaded", timeout=8000)
            except Exception:
                pass
            url = new_page.url
            if not is_ours(url):
                log(f"new tab: {url!r} -- not ESPN, ignoring")
                return
            log(f"new tab: {url!r} -- following it")
            active["page"] = new_page

        ctx.on("page", on_page)

        def op_switch(_page, arg):
            """Point the driver at an open tab whose URL contains `arg`."""
            alive = [p for p in ctx.pages if not p.is_closed()]
            for cand in reversed(alive):
                if arg in cand.url:
                    active["page"] = cand
                    cand.bring_to_front()
                    return {"switched": cand.url}
            return {"error": f"no open tab matching {arg!r}", "open": [p.url for p in alive]}

        OPS["switch"] = op_switch

        page.goto(URL, wait_until="domcontentloaded", timeout=90000)
        log(f"opened {URL}")

        while True:
            page = active["page"]
            if page.is_closed():
                alive = [p for p in ctx.pages if not p.is_closed()]
                if not alive:
                    log("all pages closed; exiting")
                    return
                ours = [p for p in alive if is_ours(p.url)]
                page = active["page"] = (ours or alive)[-1]
                log(f"active page was closed; fell back to {page.url!r}")

            try:
                STATE.write_text(json.dumps(snapshot(page), indent=1))
            except Exception as exc:
                log(f"snapshot failed: {exc}")

            if CMD.exists():
                try:
                    cmd = json.loads(CMD.read_text())
                except Exception:
                    cmd = None
                if cmd and cmd.get("id") != last_id:
                    last_id = cmd["id"]
                    op = cmd.get("op", "ping")
                    log(f"cmd {last_id}: {op} {cmd.get('arg', '')!r}")
                    try:
                        data = OPS[op](page, cmd.get("arg", ""))
                        res = {"id": last_id, "ok": True, "data": data}
                    except Exception as exc:
                        res = {
                            "id": last_id,
                            "ok": False,
                            "error": str(exc),
                            "tb": traceback.format_exc()[-900:],
                        }
                    RESULT.write_text(json.dumps(res, indent=1, default=str))

            beat += 1
            if beat % 20 == 0:
                log(f"alive beat={beat}")
            time.sleep(1.5)


if __name__ == "__main__":
    main()
