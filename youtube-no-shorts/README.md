# YouTube — No Shorts

A "wrapper" for YouTube that looks and works **exactly** like the real site, just with Shorts removed — on iPhone and desktop.

## Why it's done this way (not a proxy)

A self-hosted site that proxies youtube.com **cannot** stay identical: it breaks your login, your recommendations, and — critically — **YouTube Premium background playback**, because YouTube signs and DRM-protects its video streams against your logged-in session.

So instead of replacing YouTube, this runs a tiny script **on the real youtube.com** inside Safari and removes Shorts from the page. Your Premium session, background audio, and everything else are 100% untouched, because it *is* YouTube.

What it removes:
- Shorts shelf on the home feed
- Shorts in search results and subscriptions
- The Shorts tab on channel pages
- The Shorts button in the bottom nav (mobile) / left sidebar (desktop)
- Redirects any `youtube.com/shorts/<id>` link to the normal `watch?v=<id>` player (so tapping a Shorts link just plays it as a regular video — which also means Premium background play works on it)

---

## iPhone setup (primary — ~3 minutes)

1. Install the free **Userscripts** app from the App Store (by Justin Wasack). It's an open-source Safari extension, no account, nothing leaves your phone.
2. Open **Settings → Apps → Safari → Extensions → Userscripts** and turn it **On**. Tap it and set permission for `youtube.com` to **Allow** (or "Always Allow on Every Website").
3. Open the Userscripts app once. It creates a scripts folder and shows a directory location — tap **Set Userscripts Directory** if prompted and pick/confirm the folder.
4. Get `youtube-no-shorts.user.js` onto the phone: AirDrop it from the Mac, or open it in Safari and use the Userscripts toolbar. Easiest path:
   - In Safari, go to youtube.com, tap the **`aA`** (or extensions puzzle) button → **Userscripts**.
   - Tap the **+** → **New Userscript** (or the file-import option) and paste the contents of `youtube-no-shorts.user.js`.
   - Save.
5. Reload youtube.com. Shorts are gone. Use YouTube exactly as before — Premium background playback works (lock the screen / switch apps and audio keeps going).

> Tip: add youtube.com to your Home Screen (Safari → Share → **Add to Home Screen**) for an app-like icon. The userscript still runs there.

### Premium background playback on iPhone
With YouTube Premium, mobile Safari already lets audio keep playing when you lock the screen or leave the tab. This script doesn't touch that — and because it redirects Shorts to the normal player, even former Shorts play in the background.

---

## Desktop setup (optional)

1. Install **Tampermonkey** (or Violentmonkey) in your browser.
2. Open `youtube-no-shorts.user.js` — Tampermonkey will offer to install it. Confirm.
3. Reload YouTube.

---

## Alternative: content blocker (no userscript app)

If you'd rather use a content blocker (AdGuard for iOS, 1Blocker) than the Userscripts app, paste the rules from `content-blocker-rules.txt` into its user-rules section. Note: content blockers can only **hide** Shorts — they can't redirect `/shorts/` links to the normal player, so the userscript is the more complete option.

---

## Files

| File | What it is |
|------|------------|
| `youtube-no-shorts.user.js` | The userscript (iPhone via Userscripts app, desktop via Tampermonkey). The full solution. |
| `content-blocker-rules.txt` | Cosmetic hide rules for AdGuard/1Blocker, if you prefer no userscript app. |

## Maintenance

YouTube occasionally renames its internal components, which can let a Shorts surface slip back in. The script leans on structural selectors (`:has(a[href*="/shorts/"])`) rather than the literal word "Shorts" to minimize this, but if Shorts ever reappear somewhere, tell your Claude "Shorts are showing up in X again" and the selector list in `youtube-no-shorts.user.js` can be updated.
