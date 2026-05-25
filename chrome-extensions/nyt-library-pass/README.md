# KC Library NYT Pass

Chrome extension that redeems the Kansas City Public Library's New York Times
group pass with one click. The library's "Access Now" link routes through OCLC
EZproxy, which requires a library card number + PIN; this extension auto-fills
that form, then NYT signs you in via your existing Google session.

## Setup

1. Visit `chrome://extensions`, enable **Developer mode**, click **Load
   unpacked**, and select this directory.
2. Click the extension's toolbar icon — the options page opens.
3. Enter your library card number and PIN. Click **Save**.
4. Click the toolbar icon again to redeem.

Credentials live only in `chrome.storage.local` on this machine. Nothing leaves
the browser.

## Flow

1. Toolbar click → opens `https://kclibrary.idm.oclc.org/login?url=http://ezmyaccount.nytimes.com/grouppass/redir`
2. Content script auto-fills the EZproxy login form and submits it.
3. EZproxy redirects to `ezmyaccount.nytimes.com/grouppass/redir`, which
   redeems the pass.
4. NYT redirects to its sign-in flow; click **Continue with Google** (or it
   auto-signs in if you've used it before).

## Files

- `manifest.json` — MV3 manifest, scopes host permissions to the EZproxy and
  NYT domains only.
- `background.js` — service worker; toolbar click handler.
- `content-ezproxy.js` — runs on the EZproxy login page, fills the form.
- `options.html` / `options.js` — credential entry form.

## Customizing for a different library

Change `REDEEM_URL` in `background.js` and the `host_permissions` /
`content_scripts.matches` in `manifest.json` to your library's EZproxy host.
The form-field selectors in `content-ezproxy.js` cover the common OCLC
defaults but may need adjusting.

## Icons

The New York Times masthead "T" (black on transparent) lives in `icons/` at 16,
32, 48, and 128px, wired into `manifest.json` via `action.default_icon` and the
top-level `icons` block. Swap in your own PNGs at those sizes to rebrand.
