"""The bot check on generation: Suno's own Turnstile widget, run in a headless Chrome.

Before a generation the web client asks ``POST /c/check`` whether a check is necessary. When
the answer is ``{"required": true, "captcha_version": 2}`` it runs a Cloudflare Turnstile
widget and sends the widget's token with the request. This module does the same: it opens a
suno.com page in the installed Chrome with no window, runs the widget with Suno's site key,
and returns the token.

INVARIANTS:
- Headless only. No window is ever opened, on screen or off it. A windowed Chrome takes
  focus from whoever is at the Mac.
- No solver service and no answer to a challenge. When the widget asks for interaction, or
  Suno asks for hCaptcha (version 1), this raises ``CaptchaBlocked`` and the person makes one
  song on suno.com by hand.
- The widget needs no login. The page is opened with no cookies, so the session never enters
  the automated browser. Measured 2026-11-11: token in about 2.5 s from ``/robots.txt``.
- The site key is public (it is in the page's own script). It can change; ``suno doctor
  --drift`` reads the current one from the live Create flow.
"""

from __future__ import annotations

from sunocli.session import user_agent

TURNSTILE = 2  # the other value Suno sends, 1, means hCaptcha
TURNSTILE_SITEKEY = "0x4AAAAAADI7xDNyj-3LcIbi"
PAGE = "https://suno.com/robots.txt"

_WIDGET_JS = """async ([sitekey, budget]) => {
    if (!window.turnstile) {
        await new Promise((res, rej) => {
            const s = document.createElement('script');
            s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
            s.onload = res; s.onerror = () => rej(new Error('the widget script did not load'));
            (document.head || document.documentElement).appendChild(s);
        });
    }
    for (let i = 0; i < 80 && !(window.turnstile && window.turnstile.render); i++)
        await new Promise(r => setTimeout(r, 100));
    return await new Promise(resolve => {
        const div = document.createElement('div');
        (document.body || document.documentElement).appendChild(div);
        let done = false;
        const fin = v => { if (!done) { done = true; resolve(v); } };
        setTimeout(() => fin({error: 'timeout'}), budget);
        try {
            const w = window.turnstile.render(div, {
                sitekey, execution: 'execute', appearance: 'interaction-only',
                callback: token => fin({token}),
                'error-callback': code => { fin({error: 'widget error ' + code}); return true; },
                'before-interactive-callback': () => fin({error: 'interaction'}),
            });
            window.turnstile.execute(w);
        } catch (e) { fin({error: String(e)}); }
    });
}"""


class CaptchaBlocked(RuntimeError):
    """The bot check did not pass without a person. Nothing was submitted."""


def turnstile_token(timeout: float = 45, sitekey: str = TURNSTILE_SITEKEY) -> str:
    try:
        from patchright.sync_api import sync_playwright
    except ImportError as err:  # the bin/suno launcher supplies it
        raise CaptchaBlocked("patchright is not installed; run the CLI through suno/bin/suno") from err
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_context(user_agent=user_agent(),
                                       viewport={"width": 1280, "height": 800}).new_page()
            page.goto(PAGE, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            result = page.evaluate(_WIDGET_JS, [sitekey, int(timeout * 1000)], isolated_context=False)
        finally:
            browser.close()
    token = (result or {}).get("token")
    if token:
        return token
    error = (result or {}).get("error", "no result")
    if error == "interaction":
        raise CaptchaBlocked("Suno's bot check asked for a person. Make one song on suno.com by "
                             "hand, then run the command again.")
    raise CaptchaBlocked(f"Suno's bot check did not give a token ({error}). Nothing was submitted.")


def token_for(gate: dict) -> tuple[str | None, int | None]:
    """The (token, provider) pair for a ``/c/check`` answer. (None, None) when no check is due."""
    if not gate.get("required"):
        return None, None
    version = gate.get("captcha_version")
    if version == TURNSTILE:
        return turnstile_token(), TURNSTILE
    raise CaptchaBlocked(f"Suno asked for a bot check this tool does not run (version {version}). "
                         "Make one song on suno.com by hand, then run the command again.")
