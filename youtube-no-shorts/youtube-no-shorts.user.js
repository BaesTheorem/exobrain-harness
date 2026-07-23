// ==UserScript==
// @name         YouTube -- No Shorts
// @namespace    https://github.com/local/youtube-no-shorts
// @version      1.2.0
// @description  Removes YouTube Shorts everywhere (home, search, subscriptions, channels, sidebar/bottom nav) and redirects /shorts/ links to the normal player. Runs on the real youtube.com, so login, recommendations, and YouTube Premium background playback are untouched. Works on iOS Safari (Userscripts app), desktop (Tampermonkey/Violentmonkey), and the mobile web layout.
// @author       you
// @match        *://*.youtube.com/*
// @run-at       document-start
// @grant        none
// @noframes
// ==/UserScript==

(function () {
  'use strict';

  /* -------------------------------------------------------------------------
   * 1. CSS -- hide every known Shorts surface on both the desktop (ytd-*)
   *    and mobile-web (ytm-*) layouts. Injected at document-start so Shorts
   *    never flash in before the page settles.
   *
   *    Strategy is mostly structural (:has() on a /shorts/ link) so it keeps
   *    working when YouTube renames things or changes the UI language, rather
   *    than relying on the literal English word "Shorts".
   * ---------------------------------------------------------------------- */
  const CSS = `
/* ---------- Desktop: dedicated Shorts shelves & sections ---------- */
ytd-reel-shelf-renderer,
ytd-rich-shelf-renderer[is-shorts],
ytd-rich-section-renderer:has(ytd-rich-shelf-renderer[is-shorts]),
grid-shorts-renderer,
ytd-reel-item-renderer,

/* ---------- Desktop: any feed/search/grid item that is a Short ---------- */
ytd-video-renderer:has(a[href*="/shorts/"]),
ytd-grid-video-renderer:has(a[href*="/shorts/"]),
ytd-rich-item-renderer:has(a[href*="/shorts/"]),
ytd-compact-video-renderer:has(a[href*="/shorts/"]),

/* ---------- Desktop: left guide + mini-guide "Shorts" entries ---------- */
ytd-guide-entry-renderer:has(a[title="Shorts"]),
ytd-guide-entry-renderer:has(a[href="/shorts"]),
ytd-mini-guide-entry-renderer:has(a[title="Shorts"]),
ytd-mini-guide-entry-renderer:has(a[href="/shorts"]),

/* ---------- Desktop: channel-page "Shorts" tab ---------- */
yt-tab-shape[tab-title="Shorts"],
tp-yt-paper-tab:has(yt-formatted-string[title="Shorts"]),

/* ---------- Mobile web: shelves, sections & lockups ---------- */
ytm-reel-shelf-renderer,
ytm-rich-section-renderer:has(ytm-reel-shelf-renderer),
ytm-shorts-lockup-view-model,
ytm-shorts-lockup-view-model-v2,
ytm-video-with-context-renderer:has(a[href*="/shorts/"]),
ytm-rich-item-renderer:has(a[href*="/shorts/"]),
ytm-item-section-renderer:has(a[href*="/shorts/"]),

/* ---------- Mobile web: bottom pivot-bar "Shorts" button ---------- */
ytm-pivot-bar-item-renderer:has(a[href^="/shorts"]),
ytm-pivot-bar-item-renderer:has(.pivot-shorts),

/* ---------- Generic catch-all for newer lockup components ---------- */
ytd-rich-item-renderer:has(ytm-shorts-lockup-view-model),
yt-lockup-view-model:has(a[href*="/shorts/"])
{
  display: none !important;
}
`;

  function injectCSS() {
    if (document.getElementById('yt-no-shorts-style')) return;
    const style = document.createElement('style');
    style.id = 'yt-no-shorts-style';
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }
  injectCSS();
  // <head> may not exist yet at document-start; retry on DOM ready.
  document.addEventListener('DOMContentLoaded', injectCSS);

  /* -------------------------------------------------------------------------
   * 2. Redirect any /shorts/<id> URL to the normal watch page.
   *    The video still plays exactly as a regular video -- which means
   *    Premium background playback works on it too.
   * ---------------------------------------------------------------------- */
  function redirectShorts() {
    const m = location.pathname.match(/^\/shorts\/([\w-]+)/);
    if (m) {
      const target = location.origin + '/watch?v=' + m[1];
      location.replace(target);
      return true;
    }
    return false;
  }
  redirectShorts();

  // YouTube is a single-page app: listen for its internal navigation events
  // so the redirect + cleanup re-run without a full page load.
  window.addEventListener('yt-navigate-finish', () => {
    redirectShorts();
    sweep();
  });
  window.addEventListener('yt-navigate-start', redirectShorts);
  // Mobile web sometimes only fires popstate / state changes:
  window.addEventListener('popstate', redirectShorts);

  /* -------------------------------------------------------------------------
   * 3. JS sweep -- belt-and-suspenders for anything CSS :has() misses
   *    (e.g. lazily hydrated nav items). Hides Shorts links' containers and
   *    nav entries that point at /shorts.
   * ---------------------------------------------------------------------- */
  const ITEM_WRAPPERS = [
    'ytd-video-renderer', 'ytd-grid-video-renderer', 'ytd-rich-item-renderer',
    'ytd-compact-video-renderer', 'ytd-reel-item-renderer',
    'ytm-video-with-context-renderer', 'ytm-rich-item-renderer',
    'ytm-pivot-bar-item-renderer', 'yt-lockup-view-model'
  ];

  function hideClosest(el) {
    for (const sel of ITEM_WRAPPERS) {
      const w = el.closest(sel);
      if (w) { w.style.display = 'none'; return; }
    }
    // Fallback: hide the element itself if no known wrapper matched.
    el.style.display = 'none';
  }

  function sweep() {
    document.querySelectorAll('a[href*="/shorts/"], a[href^="/shorts"]').forEach(hideClosest);
  }

  // Run the sweep on any DOM mutation, throttled with rAF so infinite-scroll
  // feeds stay smooth.
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; sweep(); });
  });

  function startObserver() {
    if (document.body) {
      sweep();
      observer.observe(document.body, { childList: true, subtree: true });
    } else {
      document.addEventListener('DOMContentLoaded', startObserver);
    }
  }
  startObserver();
})();
