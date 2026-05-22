# FB Cleaner

Chrome extension that hides Facebook **Reels**, **Stories**, and **Sponsored posts** on facebook.com. Toggle on/off from the toolbar icon.

## How it works

- **Sponsored posts:** Facebook obfuscates the "Sponsored" label (split characters, off-screen decoys, etc.). The script reads each post's `aria-labelledby` target and assembles only the *visibly rendered* text, then matches against "Sponsored". Whole post (`role="article"`) is hidden when matched.
- **Reels:** hides feed modules whose header is "Reels" / "Reels and short videos", standalone `/reel/...` posts, and the Reels left-nav link.
- **Stories:** hides the stories tray (`aria-label="Stories"`), individual `/stories/...` links, and any `data-pagelet*="Stories"` container.
- A `MutationObserver` re-runs on feed updates (debounced via `requestAnimationFrame`). When disabled, the observer is disconnected and previously hidden elements are restored.

## Toggle

Click the toolbar icon to open the popup, flip the switch. State is stored in `chrome.storage.local` under `enabled` (default on). Changes apply instantly in all open Facebook tabs.

## Install (unpacked)

1. Open `chrome://extensions`.
2. Toggle **Developer mode** (top right).
3. Click **Load unpacked** and select this `fb-cleaner/` folder.
4. Visit facebook.com — reels, stories, and sponsored posts should be gone.

## Notes

- Facebook changes their DOM frequently. If something stops working, open DevTools on facebook.com, inspect the offending block, and update the selectors in `content.js`.
- Only permission used is `storage` (for the toggle). Content script runs on `*.facebook.com` only.
