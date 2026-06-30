---
name: dnd-sheet
description: Work on Alex's self-contained D&D 5e character sheet web app (the MPMB replacement) — a single ~13MB index.html with all CSS/JS/sourcebook data baked in. Use when Alex says "the D&D sheet", "character sheet app", "the MPMB replacement", "the dnd-character-sheet repo", mentions a bug or feature on that sheet, asks to add a class/feat/spell/item mechanic, the Universal (formerly D&D Beyond) or Classic theme, the rest system, magic items, the coverage oracle, or wants to ship/deploy a change to it. NOT for solo-dm, ttrpg-player, or TTRPG-campaign-manager (those are play/GM skills). Read this before touching index.html so you don't retread known gotchas.
---

# D&D Character Sheet

Alex's from-scratch, single-file D&D 5e (2014 rules) character sheet app — a clean-room replacement for MPMB's PDF sheet, built because MPMB's automation is inseparable from its Adobe/look (reskin proven impossible). The whole app is one self-contained `index.html`: inline CSS + JS, no frameworks, no Adobe, with the full 5etools sourcebook baked into a `#source-data` `<script>` (~5MB of the ~13MB file) so GitHub Pages serves it self-contained and it works fully offline.

- **Local repo:** `~/Documents/dnd-character-sheet`
- **GitHub:** `BaesTheorem/dnd-character-sheet` (`main`, origin set, gh auth = BaesTheorem)
- **The app:** `index.html` (~13MB). That's it. Everything ships in this one file.
- **Deploy = push to `main`.** Alex runs the GitHub Pages build (`baestheorem.github.io/dnd-character-sheet`), not the local file or stale Drive/iCloud copies. When he says "I don't see my change," the answer is almost always "reload the Pages tab," not a code bug.

## First moves every session

1. **Read `VERSION`** (current SemVer) and the top of the in-app changelog before bumping anything. Alex commits in PARALLEL during sessions — a stale assumption about the current version will regress it (I once clobbered 2.32.0→2.31.1). Never assume the last value you set is current; re-read first.
2. **For ANY D&D rules value, read the source data — never use memory.** This is absolute here. My recall of stat blocks, spell dice, level progressions, feature text, DCs, HP formulas has been wrong repeatedly and silently corrupted the sheet (shipped Primal Companion from memory, got passive Perception / HP formula / attack dice / grapple DC all wrong). Pull from `~/My Drive/5etools/data` (override via `FIVETOOLS_DATA`; same path `build-data.py` uses). A server may run at `http://localhost:5050` but is often down — the raw JSON on disk is always there. Key files: `class/class-<class>.json`, `optionalfeatures.json` (FS:*/EI/MV:B/MM by featureType), `bestiary/bestiary-<src>.json`, `spells/`, `races.json`, `feats.json`, `items.json`, `magicvariants.json`. Strip `{@tag ...}` markup when reading. Verify finished work with a programmatic diff against source when feasible.
3. At the end of every change set, follow **"After every change set" below** — auto-commit + push, then update THIS skill with anything new you learned.

## After every change set (auto-commit, then update this skill)

Two steps, every time, in order — don't ask first:

1. **Auto-commit + push to the SHEET repo.** From `~/Documents/dnd-character-sheet`: `git add -A && git commit -m "<specific message>" && git push -q origin main`. The `.gitignore` already excludes the copyrighted artifacts (`source-data.json`, baked `*(Source Data)*.html`), so `-A` is safe — EXCEPT when Alex may have parallel uncommitted work, then `git status` first and `git add <specific files>` (a `git add -A` once swept his in-progress theme into my commit). End messages with the Co-Authored-By trailer; write a real message describing what changed and why, never "auto-commit". (Use `--no-verify` for commits that don't touch shipped `index.html`, per the version section below.)

2. **Update THIS skill with anything that will make future-you's job easier.** Whenever a session surfaces a new gotcha, a load-bearing file/function/line, a testing seam, a corrected assumption, a shipped feature, or a "don't re-attempt that" finding — edit `.claude/skills/dnd-sheet/SKILL.md` (in the harness repo, `~/Documents/Exobrain harness`) to fold it in, then commit + push the harness too (privacy-check first: no real names or personal data). Prefer revising an existing section over appending; keep durable lessons, drop stale specifics. The point is that no future session has to rediscover what this one learned. (The long-form project memory at `…/memory/project_dnd_sheet.md` is the deeper archive; this skill is the fast-start distillation — keep the two roughly in sync, but the skill should stay lean and actionable.)

## Two version numbers (do not conflate)

- **`APP_VERSION` = `vN`** — a build id the `.githooks/pre-commit` hook auto-bumps EVERY commit. Drives update detection + `sw.js` cache-bust. Don't hand-edit.
- **`APP_SEMVER`** — read from the `VERSION` file, HAND-CURATED. The app shows/names downloads by SemVer (`appLabel()`), so if you don't bump `VERSION`, the visible version looks frozen even as code ships. **Bump `VERSION` (MINOR for features, PATCH for fixes) when shipping user-facing changes.** Report the SemVer to Alex (e.g. "2.39.2"), never the `vN` build number — SemVer is what he thinks in. The hook prints both after commit.
- The repo sets `core.hooksPath .githooks`; fresh clones must set it or the stamp won't run.
- Use `git commit --no-verify` for any commit that does NOT change shipped `index.html` (e.g. `build-data.py`, coverage tooling) so the hook doesn't bump `APP_VERSION` and trigger a no-op 13MB "update available" for offline players.

## Testing protocol (this matters — read it)

The `<script>`-extract-then-`node --check` syntax check is **UNRELIABLE** on this ~13MB file: a `</script>` literal inside a string truncates the regex extraction (false "Unexpected end of input"); brace-count deltas are noise from strings/regex. A duplicated `function compute(){` once would have shipped a fully-broken sheet and node-on-extracted-script missed it.

**Always verify edits by loading the page in Playwright** and checking `page.on("pageerror")` + `typeof compute === 'function'`. That catches the real breaks. When an Edit looks balanced but the page breaks, `git diff` to spot an accidental duplicated/dropped line (a common cause: an Edit `new_string` that re-includes the trailing context line).

- **Playwright = the PYTHON package** (`/opt/homebrew/bin/playwright`, `pip install --break-system-packages playwright && python3 -m playwright install chromium`), NOT Node. Click `#intro-skip` to dismiss the welcome overlay.
- **Do NOT use `--headless=old`** on this file — it renders the whole `<style>` block as visible body text (a headless artifact, not a real bug) and `--dump-dom` can DEADLOCK forever (a render once hung 57 min and froze the whole session). macOS has no `timeout` binary (use `gtimeout` or a `&`+poll watchdog). Prefer the **browser-render skill** for flash-free capture, or Playwright `evaluate()` + `full_page` screenshot. If a render hangs: kill the Chrome chain on `user-data-dir=/tmp/render-e` + `rm -rf` the lock dir.
- **Preview a theme** by copying index.html and swapping `const DEFAULT_THEME = "dndbeyond"` → the target theme id, and `let darkMode = prefBool(DARK_KEY)` → `true` for dark.
- **Headless test seams** (things that don't render the way you'd expect): hand-pushed `asiChoices` get wiped by `compute()→syncAsiSlots()` (truncates to `asiCount()`, 0 without a class) — set `#classlevel='Fighter 4'` for a real slot; the ASI panel DOM only renders when its panel is open. Class-resource Limited rows (Arcane Recovery, Channel Divinity, Bardic Inspiration) come from `LIMITED_RESOURCES` via `fillLimitedFeatures(cls,lvl)` at char generation, NOT `refreshLimitedFeatures` — seed them to test. Write-in spell rows hold the name in an INPUT VALUE, not textContent (search `input.sp-name` value). A headless wizard sheet needs `spellMaxByInst[0]=9` + `spellEntriesOf(0)[L]` set to render spell rows.

## Keep app CODE copyright-clean (load-bearing constraint)

Alex may one day **sell or more widely distribute the sheet itself**, so the app code must stay free of copyrighted WotC material. The design rule: **the baked `#source-data` blob is the ONLY place copyrighted content is allowed to live.** Null out `#source-data` and what's left should be a copyright-clean app (point it at a 5etools source to reconstitute). The whole-file-with-data-baked-in is fine for Alex's own use *today*; the separation is what keeps a future strip-and-sell viable.

**What this means for every edit that adds content:**
- Never hardcode copyrightable WotC TEXT into app JS (spell/feature/item/invocation/maneuver/metamagic/fighting-style descriptions, stat-block prose). It belongs in `#source-data`, pulled in by a loader. This is already done — `OPTIONAL_FEATURES` and `FIGHTING_STYLES` text were de-baked into `#source-data` (via `etOptionalFeatures`) so app code is text-free. Keep it that way; don't reintroduce verbatim text into a registry.
- **Names + mechanics + formulas are NOT copyrightable** and are fine to keep hardcoded — that's why the hand-coded registries (`FEAT_SPELLS`, `FEAT_SKILLS`, `FEATURE_ATTACKS`, `LIMITED_RESOURCES`, `ELSEWHERE_ITEMS`) live in app JS and survive a rebake. Alex's OWN paraphrase prose (`SPELL_CHANGES`, `TCE_RULES`) is also fine to keep — it's his words.
- Audit reference: nulling `#source-data` takes the file ~13.3MB → ~2.85MB with a graceful "load a sourcebook" prompt; reload works via a local 5etools server OR a CORS mirror (e.g. the jsDelivr 5etools-2014 mirror). If you add a new content type, route its TEXT through `#source-data` + a loader, not into app code.

## Architecture / where things live

- **Storage = IndexedDB** (`dnd-sheet` db): char data + portraits + thumbnails, fronted by a synchronous in-memory cache `_cs` (moved off localStorage to escape the ~10MB cap). `SOURCES_KEY` + settings stay in localStorage. Opening a sheet that carries baked characters partitions into `dnd-sheet-file-<hash>` localStorage so it shows the FILE's chars, not yours.
- **Runtime data = the baked `#source-data`** (`DATA_VERSION` const, now 31+). `source-data.json` is a gitignored, STALE local artifact and `build-data.py` is the offline CLI baker (reads local 5etools → `source-data.json`, never writes the committed index.html). Do NOT run a full `build-data.py` rebuild to ship data — it's behind on hand-patched fields and regresses. New data gets injected SURGICALLY into `#source-data` via Python string-insert (the established pattern for itemSpells, attackSpells, draconic ancestry, etc.).
- **Three data representations that DIVERGED, not duplication to collapse:** (1) `build-data.py` = global superset baker (extracts across ALL 5etools files), (2) the in-browser JS loader `etBook`/`mergeBook`/`bakeSourceData()` = the LIVE per-loaded-book generator, (3) the baked `#source-data` that ships. `build-data.py` is NOT redundant/deletable — keep it. As of v2.30.0+ the loader was brought to parity (it had silently lagged, dropping hand-patched fields on every "Reload all sources").
- **Hand-coded registries survive a rebake** (names + mechanics, non-copyrightable, or Alex's own prose): `FEAT_SPELLS`, `FEAT_SKILLS`, `FEATURE_ATTACKS`, `LIMITED_RESOURCES`, `SPELL_CHANGES`, `ELSEWHERE_ITEMS`, `TCE_RULES`. Base-class feature choices (Fighting Styles, Infusions, invocations/metamagic/maneuvers) are hand-coded in app JS too (names/mechanics only — their TEXT lives in `#source-data`, per "Keep app code copyright-clean" above).

### The DATA_VERSION gotcha (causes "Sourcebooks out of date" forever)

When you bump the `DATA_VERSION` const, you **MUST also re-stamp the baked `#source-data` `_meta.dataVersion`** to match (there's exactly ONE `"dataVersion":N` in the baked blob, in `_meta` before `"pendingAug"`). A const-only bump makes the baked data SELF-STALE; a clobbered stored copy ties-and-wins and the flag shows forever. Because the Edit tool's file-state tracking fights this 13MB file (and SOH `\x01` separators in some sigs can't be matched by Edit at all), use a **verified Python byte-level replace** for these edits, not the Edit tool.

## Themes

There are effectively **two** themes — the old standalone "Universal" theme was FOLDED INTO the "D&D Beyond" theme, which is now displayed as **"Universal Character Sheet"** (the trademark name is gone from the UI). Don't treat Universal and D&D Beyond as separate options.

- **"Universal Character Sheet"** is the DEFAULT. Its **internal id stays `dndbeyond`** for save compat — do NOT rename the id; legacy saved `theme:"universal"` migrates to `dndbeyond`, and `"universal"` survives only as the default `:root` palette used for printing. Landscape dashboard on screen via a JS layout engine (`activate()` builds the `#ddb-*` scaffold, `relocate()`s cards by `data-csec` key); on PRINT it falls back to the original portrait sheet (clean B&W via the `universal` palette).
- **"Classic"** theme = a COMPLETE pixel-for-pixel rebuild of the official WotC 2014 fillable PDF (all 3 pages, light + dark). NOT a restyle — Alex explicitly rejected a CSS reskin as not faithful. Official page art is the background; live automated fields are absolutely positioned over it at the PDF's AcroForm rects, synced app↔overlay by id/selector. Engine is `CLASSIC_PAGES`, gated on `body.classic-layout`. Source PDF: `~/Downloads/5E_CharacterSheet_Fillable.pdf`.

## Coverage oracle (MPMB parity tracking)

`coverage/` holds `coverage-oracle.py` + `capability-manifest.json` (hand-maintained source of truth; status `verified` = locked) + `COVERAGE-REPORT.md`. Diffs the sheet's mechanics vs MPMB's full WotC+UA library and ranks the punch-list by *in-your-data* impact. Run with `--sheet-data index.html` (the runtime `#source-data`, ~983 entities), NOT bare `source-data.json` (stale, ~232 entities) or the numbers collapse. As of the last deep pass the count was **57/65 (87%)**, treated as the honest ceiling — the remaining 8 (`allModes`, `fixedSpAttack`, `ammoAdd`/`ammoOptions`, `amendTo`, `page3notes`, `popupName`, `stopeval`) are architectural mismatches with a declarative sheet or zero-data, documented N/A in the manifest. Don't re-attempt those without new justification.

## Distribution model

Primary distribution is the **offline HTML file** (web/Pages is the iPhone-only exception), so there's no auto-update. The in-app "update available" banner polls `version.json` (Pages URL + raw.githubusercontent fallback, both CORS-open); `updateApp()` re-bakes the user's characters into a fresh download. A CRITICAL channel exists: a one-line root `update-note.txt` → the pre-commit hook folds it into `version.json` as `{critical:true, note}` → the banner bypasses the dismissed flag and resurfaces every load until they update (sticky — rides every release until you DELETE the file). KEY LIMIT: older clients ignore the extra fields, so a critical flag only reaches users already on a build that understands it; the fix-introducing update needs out-of-band notice too.

## Design taste (this app specifically)

- **Flat / sharp:** square corners, no shadows, no shading, hairline borders, flat colors. "Straight, clean, sharp angles." NOTE: this is a D&D-sheet-ONLY preference — do NOT generalize it to Alex's other apps.
- **No emoji as icons** (rest buttons once shipped with 🏕️/🌙, replaced with sun/crescent SVG). Use small inline SVG drawn with `currentColor` so it inherits theme color. Default icon source for new icons: https://iconstash.io.
- Faithful use of WotC trade dress (the Classic art) is fine — Alex's personal tool, the PDF grants personal-use photocopy. Alex is the sole judge of what content ships; do NOT flag/warn/moralize about committing WotC data (he removed that clause).

## Open / pending (as of last session)

- "Recreate existing character" wizard path (enter final scores + max HP directly, park delta in misc bucket) — awaiting Alex's go.
- Warlock Pact Boon, Arcane Shot, Rune Knight runes.
- `weaponOptions`: Polearm Master is the only other in-data case.
- Natural-weapon races (tabaxi/lizardfolk) + feature-attack subclasses (soulknife/armorer/beast barb) are ABSENT from baked data — need those books loaded + a prose natural-weapon extractor.
- The **feature-attack mechanism** (`setBreathWeapon`/`breathWeaponRow`, re-linked by name after reload like Unarmed Strike) is the pattern to extend for other feature-granted attacks.

**Note:** these living details (current SemVer, exact coverage count, open items) drift between sessions. Trust `VERSION`, the changelog, and `capability-manifest.json` in the repo over any number written here.
