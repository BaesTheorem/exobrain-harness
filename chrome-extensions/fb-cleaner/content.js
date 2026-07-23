// FB Cleaner -- hides Reels sections, Stories tray, and Sponsored posts on Facebook.
//
// Facebook obfuscates the "Sponsored" label (split text, decoy chars, off-screen nodes)
// so we walk the post's aria-labelledby target and only count text from elements that
// are actually rendered to the user.
//
// Toggle state lives in chrome.storage.local under `enabled` (default true). When the
// user flips the toggle in the popup we either re-run the hiders or restore everything
// we've hidden so far.

const HIDDEN_ATTR = "data-fbc-hidden";
const CHECKED_ATTR = "data-fbc-checked";
const STYLE_ID = "fbc-style";

// Fast-path CSS: injected at document_start so these elements never render. Sponsored
// detection requires DOM walking (label obfuscation) so it stays in JS. The reels
// region is also CSS-hidden here; JS walks up to also hide the wrapper that holds
// the "Reels" header sibling.
const FAST_PATH_CSS = `
  [role="region"][aria-label*="Reels" i],
  [aria-label="Stories"],
  [aria-label="Stories tray"],
  [data-pagelet*="Stories"] {
    display: none !important;
  }
  /* Optimistic hide for posts the MO has tagged as "pending verification". JS
     applies this attribute ONLY to mutations that happen after the feed has
     settled -- during the initial hydration our observer isn't even attached,
     so this never blocks FB's first render. */
  [role="article"][data-fbc-pending]:not([data-fbc-hidden]) {
    opacity: 0 !important;
    pointer-events: none !important;
  }
`;

const PENDING_ATTR = "data-fbc-pending";
const REVEAL_DELAY_MS = 800;

let enabled = true;
let observer = null;
let mutedSet = new Set();

function injectStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = FAST_PATH_CSS;
  (document.head || document.documentElement).appendChild(style);
}

function removeStyle() {
  const style = document.getElementById(STYLE_ID);
  if (style) style.remove();
}

// Inject the stylesheet optimistically -- before we know the toggle state. If the
// user has the extension disabled, the storage callback below removes it. This
// trades a brief flicker (rare disabled case) for instant blocking (common case).
injectStyle();

function isVisible(el) {
  if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
  const style = window.getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden") return false;
  if (parseFloat(style.opacity) === 0) return false;
  // FB hides decoy "Sponsored" characters with absolute positioning + clip.
  if (style.position === "absolute" && (style.clip === "rect(0px, 0px, 0px, 0px)" || style.clipPath === "inset(50%)")) return false;
  const rect = el.getBoundingClientRect();
  if (rect.width === 0 && rect.height === 0) return false;
  return true;
}

function getVisibleText(el) {
  if (!el) return "";
  if (el.nodeType === Node.TEXT_NODE) return el.textContent;
  if (!isVisible(el)) return "";
  let text = "";
  for (const child of el.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) {
      text += child.textContent;
    } else if (child.nodeType === Node.ELEMENT_NODE) {
      text += getVisibleText(child);
    }
  }
  return text;
}

function hide(el, reason) {
  if (!el || el.getAttribute(HIDDEN_ATTR)) return;
  el.setAttribute(HIDDEN_ATTR, reason);
  el.style.setProperty("display", "none", "important");
  // Collapse any wrapper that now contains nothing but this hidden child. Margin /
  // separator spacing often lives on these outer wrappers, so leaving them visible
  // produces gaps between remaining posts. We only collapse when the wrapper has
  // exactly one child (the one we just hid) -- that way we never accidentally hide
  // siblings that FB might add later.
  let parent = el.parentElement;
  let depth = 0;
  while (parent && parent !== document.body && depth < 4) {
    if (parent.children.length !== 1) break;
    if (parent.getAttribute(HIDDEN_ATTR)) break;
    parent.setAttribute(HIDDEN_ATTR, "collapsed");
    parent.style.setProperty("display", "none", "important");
    parent = parent.parentElement;
    depth++;
  }
}

function unhideAll() {
  document.querySelectorAll(`[${HIDDEN_ATTR}]`).forEach((el) => {
    el.style.removeProperty("display");
    el.removeAttribute(HIDDEN_ATTR);
  });
  document.querySelectorAll(`[${CHECKED_ATTR}]`).forEach((el) => {
    el.removeAttribute(CHECKED_ATTR);
  });
}

function checkPostForSponsored(post) {
  const labelledLinks = post.querySelectorAll("[aria-labelledby]");
  for (const link of labelledLinks) {
    const ids = (link.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
    for (const id of ids) {
      const target = document.getElementById(id);
      if (!target) continue;
      const text = getVisibleText(target).trim();
      if (/^Sponsored\b/i.test(text) && text.length < 40) {
        return true;
      }
    }
  }
  return false;
}

// Patterns Facebook uses in the post subtitle to mark algorithmic recommendations
// from pages/groups the user does not follow. User-curated reshares from friends
// don't carry these labels.
const SUGGESTED_PATTERNS = [
  /^Suggested for you\b/i,
  /^Suggested\s*·/i,
  /^Followed by /i,
  /\bfollows this (Page|Group)\b/i,
  /\b(Page|Group) you might like\b/i,
];

function checkPostForSuggested(post) {
  // FB renders the "Suggested for you" / "Followed by" label inside a plain <span>
  // that doesn't always carry dir="auto" -- so scan all spans. We filter by length
  // (< 80 chars) so this can't accidentally match a post body that mentions one of
  // the trigger phrases.
  const spans = post.querySelectorAll('span');
  for (const span of spans) {
    const text = (span.textContent || "").trim();
    if (text.length === 0 || text.length > 80) continue;
    for (const pattern of SUGGESTED_PATTERNS) {
      if (pattern.test(text)) return true;
    }
  }
  // A visible "Follow" (Page) or "Join" (Group) button means the user doesn't
  // already follow / belong. Pages the user follows show "Following"; groups the
  // user is in show "Joined" or no button at all. We match leniently because FB
  // sometimes renders "+ Follow" with an icon glyph in the text content.
  const buttons = post.querySelectorAll('[role="button"], button');
  for (const btn of buttons) {
    const text = (btn.textContent || "").replace(/\s+/g, " ").trim();
    const ariaLabel = (btn.getAttribute("aria-label") || "").trim();
    if (/^\+?\s*(Follow|Join)$/i.test(text)) return true;
    if (/^(Follow|Join)(\s|$)/i.test(ariaLabel)) return true;
  }
  return false;
}

function screenPosts() {
  // We deliberately do NOT cache per-post screening results. The Follow/Join button
  // (and sometimes the "Suggested for you" subtitle) is rendered AFTER the initial
  // post header hydrates -- caching would mark the post safe before those tells
  // arrive, then skip it forever. The observer is already debounced to one pass per
  // animation frame, so re-screening visible posts each tick is cheap.
  const posts = document.querySelectorAll(`[role="article"]:not([${HIDDEN_ATTR}])`);
  posts.forEach((post) => {
    try {
      if (checkPostForSponsored(post)) {
        hide(post, "sponsored");
        return;
      }
      if (checkPostForSuggested(post)) {
        hide(post, "suggested");
        return;
      }
    } catch (e) {
      // Swallow per-post errors so one bad node doesn't kill the loop.
    }
  });
}

const SECTION_HEADER_TEXT = new Set([
  "Reels",
  "Reels and short videos",
  "Suggested reels",
  "Stories",
]);

function hideHeaderSections() {
  // Feed modules whose header text matches Reels / Stories. We only hide if the header
  // sits inside a [role="article"] -- that's the module wrapper. We deliberately do NOT
  // fall back to <section>, because Facebook wraps the whole feed in a <section> and
  // we'd nuke it.
  const headings = document.querySelectorAll(`h2, h3, span[dir="auto"]`);
  headings.forEach((h) => {
    if (h.hasAttribute(CHECKED_ATTR)) return;
    const text = (h.textContent || "").trim();
    if (!SECTION_HEADER_TEXT.has(text)) return;
    h.setAttribute(CHECKED_ATTR, "1");
    const article = h.closest('[role="article"]');
    if (article) hide(article, "section:" + text);
  });
}

function hideReels() {
  // CSS already hides the [role="region"] itself (height becomes 0). Walk up from it
  // to find the wrapper that includes the "Reels" header sibling above the region.
  // The header lives ~3 levels up -- we detect it by walking until a parent's height
  // exceeds the (now-zero) region's height by a noticeable margin.
  document.querySelectorAll('[role="region"][aria-label*="Reels" i]').forEach((region) => {
    if (region.closest(`[${HIDDEN_ATTR}]`)) return;
    let target = region;
    for (let i = 0; i < 8 && target.parentElement; i++) {
      const parentHeight = target.parentElement.getBoundingClientRect().height;
      if (parentHeight > 10) {
        target = target.parentElement;
        break;
      }
      target = target.parentElement;
    }
    if (target !== region) hide(target, "reels-module");
  });

  // Left-rail nav entries to Reels -- safe because they aren't inside posts.
  document.querySelectorAll(`a[href$="/reel/"], a[href$="/reels/"], a[href^="https://www.facebook.com/reel/"]`).forEach((a) => {
    const nav = a.closest('[role="navigation"], [role="listitem"], li');
    if (nav) hide(nav, "reels-nav");
  });
}

function screenSuggestedTextGlobal() {
  // For posts not wrapped in [role="article"], a plain-text "Suggested for you"
  // span can still flag them. Scan globally; the closest [role="article"] OR a
  // walk-up to a post-sized container catches both feed shapes.
  document.querySelectorAll('span').forEach((span) => {
    if (span.closest(`[${HIDDEN_ATTR}]`)) return;
    const text = (span.textContent || "").trim();
    if (text.length === 0 || text.length > 80) return;
    for (const pattern of SUGGESTED_PATTERNS) {
      if (pattern.test(text)) {
        const container = span.closest('[role="article"]') || findSuggestionContainer(span);
        if (container) hide(container, "suggested");
        return;
      }
    }
  });
}

function detectObfuscatedLabel(target) {
  const text = getVisibleText(target).trim();
  if (text.length === 0 || text.length > 80) return null;
  if (/^Sponsored\b/i.test(text)) return "sponsored";
  for (const p of SUGGESTED_PATTERNS) {
    if (p.test(text)) return "suggested";
  }
  return null;
}

function screenLabeledPostsGlobal() {
  // FB hides "Sponsored" (and sometimes "Suggested for you") behind an
  // aria-labelledby reference whose target contains decoy + visible chars. Our
  // visible-text walk reconstructs the actual label. Doing this globally -- not
  // just inside [role="article"] -- catches sponsored Reels and bare-div Page
  // posts that skip the article wrapper entirely.
  document.querySelectorAll('[aria-labelledby]').forEach((el) => {
    if (el.closest(`[${HIDDEN_ATTR}]`)) return;
    const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
    for (const id of ids) {
      const target = document.getElementById(id);
      if (!target) continue;
      const label = detectObfuscatedLabel(target);
      if (label) {
        const container = el.closest('[role="article"]') || findSuggestionContainer(el);
        if (container) hide(container, label);
        return;
      }
    }
  });
}

function findSuggestionContainer(btn) {
  // Walk up from an anchor (Follow button, Sponsored label span, etc.) to the
  // OUTERMOST same-sized wrapper. We need the outer wrapper, not the inner one,
  // because FB stacks several wrapper divs around each post and the margin /
  // separator that creates space between posts often lives on those outer
  // wrappers -- stopping at the inner one leaves visible empty space.
  let el = btn;
  let candidate = null;
  let postHeight = null;
  for (let i = 0; i < 16 && el && el.parentElement; i++) {
    const rect = el.parentElement.getBoundingClientRect();
    if (rect.width > 800) break; // exited the column into page chrome
    if (rect.width >= 480 && rect.height > 100) {
      if (candidate === null) {
        postHeight = rect.height;
        candidate = el.parentElement;
      } else if (rect.height <= postHeight * 1.25) {
        // Still a same-sized wrapper -- keep walking outward.
        candidate = el.parentElement;
      } else {
        // Height jumped substantially -- we've hit a multi-post container.
        break;
      }
    }
    el = el.parentElement;
  }
  return candidate;
}

function hideMutedAuthors() {
  if (mutedSet.size === 0) return;
  // Match the muted name against either aria-label or visible text on any link in
  // the post. To avoid hiding posts because a muted person *commented*, we require
  // the matched link to sit in the post's top ~100px (header region -- name lives
  // there, comments and replies live further down).
  document.querySelectorAll('a, [role="link"]').forEach((link) => {
    if (link.closest(`[${HIDDEN_ATTR}]`)) return;
    const ariaLabel = (link.getAttribute("aria-label") || "").trim().toLowerCase();
    const text = (link.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
    if (!ariaLabel && !text) return;
    if (!mutedSet.has(ariaLabel) && !mutedSet.has(text)) return;
    const container = link.closest('[role="article"]') || findSuggestionContainer(link);
    if (!container) return;
    const containerTop = container.getBoundingClientRect().top;
    const linkTop = link.getBoundingClientRect().top;
    if (linkTop - containerTop > 100) return;
    hide(container, "muted-author");
  });
}

function hideFollowJoinPosts() {
  document.querySelectorAll('[role="button"], button').forEach((btn) => {
    if (btn.closest(`[${HIDDEN_ATTR}]`)) return;
    const text = (btn.textContent || "").replace(/\s+/g, " ").trim();
    if (!/^\+?\s*(Follow|Join)$/i.test(text)) return;
    const container = findSuggestionContainer(btn);
    if (container) hide(container, "follow-join");
  });
}

function hideStories() {
  // Stories tray in the top feed -- announced via aria-label or data-pagelet.
  document.querySelectorAll('[aria-label="Stories"], [aria-label="Stories tray"]').forEach((el) => {
    hide(el, "stories-tray");
  });
  document.querySelectorAll('[data-pagelet*="Stories"]').forEach((el) => hide(el, "stories-pagelet"));
  // NOTE: we intentionally do NOT hide articles based on /stories/ links -- every
  // friend with an active story renders a story-ring link around their avatar inside
  // their normal posts, which would hide all of their posts.
}

// Leading-edge throttled scheduler. When a mutation arrives we want to scan
// immediately (so a new post is hidden before the user perceives it), but no more
// often than every SCAN_INTERVAL_MS -- global scans iterate thousands of elements
// on a long feed, and running every animation frame caused scroll jank.
//
// Behavior: first call after idle runs synchronously; subsequent calls within the
// window are coalesced into a single trailing run at the end of the window. This
// catches late-arriving tells like Follow buttons that appear a few hundred ms
// after the post's header initially hydrates.
let lastRunTime = 0;
let trailingTimer = null;
// Per-subtree scanning (deferred via setTimeout) is the primary hide path. The
// throttled global sweep is a safety net for bare-div posts and very late tells,
// so it can run much less frequently. 1500 ms keeps CPU low while still catching
// stragglers within ~1.5 s.
const SCAN_INTERVAL_MS = 1500;

function runScans() {
  lastRunTime = Date.now();
  if (!enabled) return;
  try {
    screenPosts();
    screenLabeledPostsGlobal();
    screenSuggestedTextGlobal();
    hideFollowJoinPosts();
    hideMutedAuthors();
    hideHeaderSections();
    hideReels();
    hideStories();
  } catch (e) {
    console.warn("[FB Cleaner]", e);
  }
}

function scheduleRun() {
  if (!enabled) return;
  const elapsed = Date.now() - lastRunTime;
  if (elapsed >= SCAN_INTERVAL_MS) {
    if (trailingTimer) {
      clearTimeout(trailingTimer);
      trailingTimer = null;
    }
    runScans();
  } else if (!trailingTimer) {
    trailingTimer = setTimeout(() => {
      trailingTimer = null;
      runScans();
    }, SCAN_INTERVAL_MS - elapsed);
  }
}

// Per-subtree scanner. When the MutationObserver tells us new content has been
// added, we run all the hide checks against just that subtree synchronously
// inside the MO callback. This catches blockable posts the moment they're
// inserted -- whether they're [role="article"] or bare-div page posts -- without
// running expensive global scans on every mutation. Late-arriving tells (a
// Follow button added 500 ms after its parent post) come in as their own
// addedNodes mutation, so they're caught by the same path.
function scanSubtreeForBlockables(root) {
  if (!root || root.nodeType !== 1) return;
  if (root.closest?.(`[${HIDDEN_ATTR}]`)) return;

  const matchesAndDescendants = (selector) => {
    const out = [];
    if (root.matches?.(selector)) out.push(root);
    if (root.querySelectorAll) {
      for (const el of root.querySelectorAll(selector)) out.push(el);
    }
    return out;
  };

  // 1) Sponsored / Suggested via aria-labelledby (obfuscated decoy labels).
  for (const el of matchesAndDescendants('[aria-labelledby]')) {
    if (el.closest(`[${HIDDEN_ATTR}]`)) continue;
    const ids = (el.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
    for (const id of ids) {
      const target = document.getElementById(id);
      if (!target) continue;
      const label = detectObfuscatedLabel(target);
      if (label) {
        const container = el.closest('[role="article"]') || findSuggestionContainer(el);
        if (container) hide(container, label);
        break;
      }
    }
  }

  // 2) Plain-text "Suggested for you" / "Followed by …" in any span.
  for (const span of matchesAndDescendants('span')) {
    if (span.closest(`[${HIDDEN_ATTR}]`)) continue;
    const text = (span.textContent || "").trim();
    if (text.length === 0 || text.length > 80) continue;
    let matched = false;
    for (const pattern of SUGGESTED_PATTERNS) {
      if (pattern.test(text)) { matched = true; break; }
    }
    if (!matched) continue;
    const container = span.closest('[role="article"]') || findSuggestionContainer(span);
    if (container) hide(container, "suggested");
  }

  // 3) Follow / Join buttons (post from non-followed Page/Group).
  for (const btn of matchesAndDescendants('[role="button"], button')) {
    if (btn.closest(`[${HIDDEN_ATTR}]`)) continue;
    const text = (btn.textContent || "").replace(/\s+/g, " ").trim();
    if (!/^\+?\s*(Follow|Join)$/i.test(text)) continue;
    const container = findSuggestionContainer(btn);
    if (container) hide(container, "follow-join");
  }

  // 4) Muted-author check (any link in the post's top region matches mute list).
  if (mutedSet.size > 0) {
    for (const link of matchesAndDescendants('a, [role="link"]')) {
      if (link.closest(`[${HIDDEN_ATTR}]`)) continue;
      const al = (link.getAttribute("aria-label") || "").trim().toLowerCase();
      const tx = (link.textContent || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (!al && !tx) continue;
      if (!mutedSet.has(al) && !mutedSet.has(tx)) continue;
      const container = link.closest('[role="article"]') || findSuggestionContainer(link);
      if (!container) continue;
      const top = container.getBoundingClientRect().top;
      if (link.getBoundingClientRect().top - top > 100) continue;
      hide(container, "muted-author");
    }
  }
}

function tagPendingArticle(post) {
  if (!post || post.nodeType !== 1) return;
  if (post.getAttribute(HIDDEN_ATTR)) return;
  if (post.getAttribute(PENDING_ATTR)) return;
  post.setAttribute(PENDING_ATTR, "1");
  post._fbcRevealTimer = setTimeout(() => {
    post._fbcRevealTimer = null;
    if (!post.isConnected) return;
    if (post.getAttribute(HIDDEN_ATTR)) return;
    post.removeAttribute(PENDING_ATTR);
  }, REVEAL_DELAY_MS);
}

function tagPendingArticlesIn(node) {
  if (!node || node.nodeType !== 1) return;
  if (node.matches?.('[role="article"]')) tagPendingArticle(node);
  node.querySelectorAll?.('[role="article"]').forEach(tagPendingArticle);
}

let feedAttachTimer = null;
let feedRetries = 0;

function attachFeedObserver(feed) {
  if (observer || !enabled) return;
  // Sweep anything already in the feed before we attached.
  scheduleRun();
  observer = new MutationObserver((mutations) => {
    // Synchronous (cheap) work: tag any newly added articles as pending so the
    // CSS rule hides them via opacity immediately. Collect added nodes for
    // deferred heavy scanning.
    const added = [];
    for (const m of mutations) {
      if (m.type !== "childList") continue;
      for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        tagPendingArticlesIn(n);
        added.push(n);
      }
    }
    // Defer expensive scanning to a macrotask so FB's hydration / rendering can
    // run between batches. Pending tag keeps newly-added articles invisible
    // until the deferred scan resolves them, so deferring doesn't reintroduce
    // flicker for role="article" posts. Bare-div posts get caught by the
    // throttled global sweep.
    if (added.length > 0) {
      setTimeout(() => {
        if (!enabled) return;
        for (const node of added) {
          if (node.isConnected) scanSubtreeForBlockables(node);
        }
      }, 0);
    }
    scheduleRun();
  });
  observer.observe(feed, { childList: true, subtree: true });
}

function startObserver() {
  if (observer || feedAttachTimer) return;
  // Wait for [role="main"] (FB's feed wrapper) to exist, then give FB a settling
  // window so we don't compete with initial hydration. Once attached, we observe
  // only the feed -- page chrome / sidebars never trigger our scans.
  const tryAttach = () => {
    feedAttachTimer = null;
    if (!enabled) return;
    const feed = document.querySelector('[role="main"]');
    if (feed) {
      feedAttachTimer = setTimeout(() => {
        feedAttachTimer = null;
        attachFeedObserver(feed);
      }, 800);
      return;
    }
    if (++feedRetries > 60) {
      // Fallback: feed wrapper never appeared. Use the safe throttled-only mode.
      observer = new MutationObserver(scheduleRun);
      observer.observe(document.documentElement, { childList: true, subtree: true });
      return;
    }
    feedAttachTimer = setTimeout(tryAttach, 100);
  };
  tryAttach();
}

function stopObserver() {
  if (feedAttachTimer) {
    clearTimeout(feedAttachTimer);
    feedAttachTimer = null;
  }
  feedRetries = 0;
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  if (trailingTimer) {
    clearTimeout(trailingTimer);
    trailingTimer = null;
  }
  // Clear any pending reveal timers and the pending tag.
  document.querySelectorAll(`[${PENDING_ATTR}]`).forEach((el) => {
    if (el._fbcRevealTimer) { clearTimeout(el._fbcRevealTimer); el._fbcRevealTimer = null; }
    el.removeAttribute(PENDING_ATTR);
  });
}

function applyState(next) {
  enabled = next;
  if (enabled) {
    injectStyle();
    startObserver();
    scheduleRun();
  } else {
    removeStyle();
    stopObserver();
    unhideAll();
  }
}

function setMuted(list) {
  mutedSet = new Set((list || []).map((s) => String(s).trim().toLowerCase()).filter(Boolean));
}

chrome.storage.local.get({ enabled: true, muted: [] }, ({ enabled: initial, muted }) => {
  setMuted(muted);
  applyState(initial);
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.muted) {
    setMuted(changes.muted.newValue);
    // A name was removed from the mute list -- unhide anything we hid for it.
    document.querySelectorAll(`[${HIDDEN_ATTR}="muted-author"]`).forEach((el) => {
      el.style.removeProperty("display");
      el.removeAttribute(HIDDEN_ATTR);
    });
    scheduleRun();
  }
  if (changes.enabled) {
    applyState(!!changes.enabled.newValue);
  }
});
