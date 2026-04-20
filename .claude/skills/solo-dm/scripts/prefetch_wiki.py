#!/usr/bin/env python3
"""Prefetch wiki summaries + seed campaign-specific homebrew notes for every
marker in the theory-of-magic campaign.

Writes `wiki_cache: {title, extract, url, fetched_at}` to each marker so the
dashboard can open the info panel instantly without a live fetch. Also writes
`homebrew_notes` for the handful of locations that matter to Session 1's story.
"""
from __future__ import annotations
import json, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

# Pull in the fetcher from webui.py (don't duplicate the parsing logic)
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import webui  # noqa: E402

DB_PATH = Path(
    "/Users/alexhedtke/Documents/Exobrain harness/data/solo-dm/theory-of-magic/state.sqlite"
)


# Campaign-specific notes per marker label. Alex can edit these in the UI;
# the DM (Claude) is expected to append here as the story adds context.
HOMEBREW_NOTES: dict[str, str] = {
    "Calimshan": (
        "Charles's homeland, fled ~2 tendays ago (early Flamerule 1491 DR) "
        "after Lord Erispar of House Erispar murdered Oma adh Erispar.\n\n"
        "House Erispar has posted a private bounty — descriptions vague "
        "enough to muddy the trail, but any senior pasha-contact or "
        "Shoon-adjacent scholar here will recognize Charles by name. "
        "House Erispar reach: STRONG in Calimshan, moderate in Amn "
        "(merchant ties), weak-to-none further north."
    ),
    "Calimport": (
        "Capital of Calimshan and seat of House Erispar. Unrest in the "
        "merchant wards per local reports.\n\n"
        "Rumor of Charles's 'Genasi blood' is in circulation here — "
        "verity unknown. The Erispar bounty was first posted here; "
        "circulation rate through Amn bureaucracy unknown but probable."
    ),
    "Amn": (
        "Current region as of 15 Flamerule 1491 DR. Amn Council patrols "
        "active along the Trade Way under standing orders since last "
        "Tarsakh — checks for forged travel documents.\n\n"
        "NPCs met:\n"
        "• **Sergeant Daeron** — Crimmor-born, mid-career, professional-"
        "but-tired, family man. Gave Charles benefit-of-doubt after "
        "forged-letter pivot to partial-truth. Waved through without "
        "paper trail beyond 'Calishite scholar, no papers, let pass on "
        "judgment.' Volunteered intel: Zhent outriders cutting the verge "
        "of the pilgrim path past the Reaching Woods in the last "
        "fortnight — stay on the marked path.\n"
        "• **Pria** — Copper Kettle caravanserai proprietor, Amnish, "
        "mid-40s. Identified Brother Olwin's cart for 1sp tip.\n\n"
        "House Erispar has moderate merchant reach here — risk of "
        "recognition scales with proximity to coast and pasha-adjacent "
        "scholars."
    ),
    "Candlekeep": (
        "**Primary destination.** Brother Olwin is Charles's entry "
        "vector — possible sponsor, currently on trial travel with "
        "Charles (Copper Kettle → Green Reed departing first light "
        "16 Flamerule). Gate-entry requires a unique tome never before "
        "in the library's collection.\n\n"
        "**Named research contact:** Reader Halaena of the North Court "
        "— mid-40s, passed over for Chanter advancement twice, works "
        "the physical-catalog wing, corresponds with outside inquirers, "
        "likely predictive-criterion-aligned. Olwin pointed Charles at "
        "her as 'the honest answer to your museum-of-dissatisfied-"
        "Chanters framing.'\n\n"
        "**Research leads to chase in the stacks:**\n"
        "• **Eveth Brelwick** — marginalia in commentary on *The "
        "Catalogue of Ordered Things*. Thesis: *diffusion into the "
        "common.* Died before Olwin's novitiate; thesis never formally "
        "accepted or refuted.\n"
        "• **Thenric of Berdusk** — permission-frame theology. Caster "
        "draws on Mystra's latent permission; energy never local. "
        "Olwin: 'tidy in a way that makes me suspicious of it.'\n"
        "• **Tanivara of the Brackwell Commentaries** — 40-year "
        "framework arguing *why* and *what* are equivalent questions. "
        "Precise on the what, silent on the ought. Charles has NOT read "
        "Brackwell directly — only secondary citation in his master's "
        "library (he volunteered this to Olwin)."
    ),
    "Berdusk": (
        "Homeland of **Thenric of Berdusk** — previous-generation "
        "Candlekeep Chanter. Author of the permission-frame theology: "
        "caster draws on Mystra's latent permission, energy never "
        "local. Widely cited but Olwin considers it 'tidy in a way "
        "that makes me suspicious of it.'\n\n"
        "Research lead for Charles to follow up on, but probably via "
        "Candlekeep's archives rather than in-person — Thenric is of "
        "the previous generation."
    ),
    "Baldur's_Gate": (
        "On the overland route Copper Kettle → Green Reed → Esmel "
        "Crossing → Candlekeep pilgrim branch. Not yet visited by "
        "Charles. No established threads. Big enough to disappear in "
        "if the Candlekeep plan falls through."
    ),
    "Waterdeep": (
        "Considered by Charles at campaign open as the 'farthest, "
        "safest, expensive' destination. Deferred in favor of "
        "Candlekeep's research access. House Erispar's reach is "
        "weak-to-none this far north — Waterdeep remains a viable "
        "fallback if Candlekeep entry is denied."
    ),
    "Silverymoon": (
        "Considered by Charles at campaign open as the 'most "
        "progressive magical scholarship' destination. Deferred in "
        "favor of Candlekeep's named-contact (Reader Halaena) + "
        "breadth-of-collection advantage. Viable fallback if "
        "Candlekeep or Waterdeep both close."
    ),
}


def main():
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT value FROM world_state WHERE key='map_markers'"
    ).fetchone()
    markers = json.loads(row[0])
    print(f"loaded {len(markers)} markers")

    now = datetime.now(timezone.utc).isoformat()
    fetched = 0
    hit = 0
    for m in markers:
        slug = m.get("wiki_slug")
        label = m.get("label", "")
        # Homebrew notes first (no network required)
        if label in HOMEBREW_NOTES:
            m["homebrew_notes"] = HOMEBREW_NOTES[label]
        if not slug:
            continue
        # Skip if already cached with non-empty extract (idempotent)
        cache = m.get("wiki_cache") or {}
        if cache.get("extract"):
            hit += 1
            continue
        # Live fetch
        result = webui.api_wiki_summary(slug)
        m["wiki_cache"] = {
            "title": result.get("title") or label,
            "extract": result.get("extract", ""),
            "url": result.get("url", ""),
            "error": result.get("error"),
            "fetched_at": now,
        }
        fetched += 1
        short = (result.get("extract", "") or "").replace("\n", " ")[:80]
        marker = "✓" if result.get("extract") else "∅"
        print(f"  {marker} {label:22} {short}")
        time.sleep(0.4)  # polite rate limit to fandom

    cid = conn.execute("SELECT id FROM campaigns LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO world_state (campaign_id, key, value) VALUES (?,?,?) "
        "ON CONFLICT(campaign_id, key) DO UPDATE SET value=excluded.value, "
        "updated_at=datetime('now')",
        (cid, "map_markers", json.dumps(markers)),
    )
    conn.commit()
    print(f"\nfetched {fetched} fresh, {hit} already cached")
    print(f"homebrew notes seeded on {len(HOMEBREW_NOTES)} markers")


if __name__ == "__main__":
    main()
