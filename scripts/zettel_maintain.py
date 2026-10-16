#!/usr/bin/env python3
"""Weekly maintenance pass for the session-memory Zettelkasten (vault ``Claude/``).

The nightly writer (scripts/session_memory.py) adds and updates notes one session
at a time. This pass works on the whole store, the way a Zettelkasten keeper
revisits the box: it links orphans, merges duplicates, closes or escalates stale
open threads, merges synonym tags, rewrites structure notes for the big topics,
and records health metrics. Principles and sources: the /session-memory skill.

    zettel_maintain.py [--steps embed,orphans,dupes,threads,tags,structure,health]
                       [--limit N] [--dry-run] [--force-structure] [--quiet]

Steps (each one is optional and runs in this order):
    embed      refresh the embedding cache and neighbor lists (session_memory embed)
    orphans    zettels no other zettel links to: the model picks real links, with a
               reason, from each orphan's nearest embedding neighbors
    dupes      pairs at cosine >= DUP_COS: the model judges duplicate (merge into
               one, supersede the other), related (link with a reason) or distinct.
               Each duplicate is also recorded as a retrieval miss: was the older
               note in the writer's candidates when the newer one was created?
    threads    active open threads untouched for STALE_DAYS: the model reads later
               zettels and session notes and closes the ones the record shows are
               done; the rest older than ESCALATE_DAYS go to Alex in the digest
    tags       one model call over the tag vocabulary merges synonyms and one-off tags
    structure  a structure note (Structure/<tag>.md) for each tag with more than
               STRUCTURE_MIN zettels: an overview, at most four entry points and
               grouped sections. Regenerated when membership moved 20% or the note
               is older than 30 days (the Zep finding: incremental summaries drift)
    health     metrics to Claude/Health.md and zettel-health.jsonl

INVARIANTS
- No zettel is deleted. A merged duplicate is ``superseded`` and links to the survivor.
- The model never writes files: it returns JSON, this module validates every id
  against the store and applies the change through session_memory's Store.
- Every change is listed in one ``Sessions/<stamp>_maintain.md`` note, and that
  note is the source each touched zettel cites.
- Zettel text reaches the model framed UNTRUSTED (it was distilled from transcripts
  that quote third parties), and every written file passes the injection scanner.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import session_memory as sm  # noqa: E402

DUP_COS = 0.88          # planted-duplicate test 2026-10-15: 40/40 paraphrases at >= 0.889
STALE_DAYS = 14
ESCALATE_DAYS = 30
STRUCTURE_MIN = 25
STRUCTURE_MAX_AGE_DAYS = 30
STRUCTURE = sm.ROOT / "Structure"
HEALTH = sm.ROOT / "Health.md"
HEALTH_LOG = sm.LOG_DIR / "zettel-health.jsonl"
MISS_LOG = sm.LOG_DIR / "zettel-dup-misses.jsonl"
NOTIFY = sm.HARNESS / "mist-voice/bin/mist-notify"
LINK_ID = re.compile(r"\[\[(\d{12}[a-z]?)[ \]|]")
ZID = re.compile(r"\b(\d{12}[a-z]?)\b")
SESSION_STEM = re.compile(r"\b(\d{4}-\d{2}-\d{2}_\d{4}(?:_delta)?(?:-\d+)?)\b")
TICKED = re.compile(r"^- \[[xX]\] \[\[(\d{12}[a-z]?)[ \]|]", re.M)
ALEX_MAX = 12            # open threads per weekly digest; the oldest first


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------

def today() -> dt.date:
    return dt.datetime.now(sm.LOCAL_TZ).date()


def link_graph(store: sm.Store) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(outgoing, incoming) id sets, from the links in zettel bodies."""
    out = {z: set(LINK_ID.findall(n["body"])) & store.notes.keys() - {z} for z, n in store.notes.items()}
    inc: dict[str, set[str]] = {z: set() for z in store.notes}
    for z, targets in out.items():
        for t in targets:
            inc[t].add(z)
    return out, inc


def active(store: sm.Store, z: str) -> bool:
    return store.notes[z]["meta"].get("status", "active") == "active"


def card(store: sm.Store, z: str, chars: int = 700) -> str:
    n = store.notes[z]
    body = sm.split_links(n["body"])[0]
    return f"[{store.row(z)}]\n{body[:chars]}"


def ask(rules: str, payload: str, label: str) -> dict | None:
    """One model call. The payload is MIST's own notes, framed as data."""
    return sm.run_claude(rules + "\n\n" + sm.frame(payload, "zettels"), label)


class Change:
    """Collects what the pass did, for the _maintain note and the digest."""

    def __init__(self, dry: bool) -> None:
        self.dry = dry
        self.lines: dict[str, list[str]] = {}
        self.written: set[Path] = set()
        self.alex: list[str] = []

    def add(self, section: str, line: str) -> None:
        self.lines.setdefault(section, []).append(line)


# --------------------------------------------------------------------------
# orphans
# --------------------------------------------------------------------------

ORPHAN_RULES = """You are MIST maintaining your own Zettelkasten. Each ORPHAN below is a zettel no other zettel links to, shown with its nearest notes by meaning. For each orphan, choose the links a careful reader would want: from a neighbor to the orphan (the neighbor leads the reader on to it), or from the orphan to a neighbor. A link must state a real relation in 3-8 words ("same bug on the phone build", "the rule this applies", "earlier attempt at this"). Topic overlap alone is not a relation. Zero links is a valid answer for an orphan that stands alone.

Return ONE JSON object: {"links": [{"from": "id", "to": "id", "why": "3-8 words"}]}. Every link must have the orphan at one end."""


def step_orphans(store: sm.Store, nb: dict, ch: Change, source: str, limit: int) -> None:
    _, inc = link_graph(store)
    orphans = [z for z in sorted(store.notes, reverse=True) if not inc[z] and active(store, z)]
    ch.add("Orphans", f"{len(orphans)} active zettel(s) had no incoming link; {min(len(orphans), limit)} reviewed")
    orphans = orphans[:limit]
    added = 0
    for i in range(0, len(orphans), 20):
        batch = orphans[i:i + 20]
        parts, allowed = [], {}
        for z in batch:
            neigh = [x for x, _ in (nb.get(z) or []) if x in store.notes and x != z][:6]
            allowed[z] = set(neigh)
            parts.append(f"## ORPHAN {card(store, z)}\nNeighbors:\n" + "\n\n".join(card(store, x, 350) for x in neigh))
        data = ask(ORPHAN_RULES, "\n\n".join(parts), f"maintain orphans {i}")
        for ln in (data or {}).get("links") or []:
            if not isinstance(ln, dict):
                continue
            a, b, why = str(ln.get("from") or ""), str(ln.get("to") or ""), str(ln.get("why") or "").strip()
            orphan = a if a in allowed else b if b in allowed else None
            other = b if orphan == a else a
            if not orphan or other not in allowed[orphan] or not why:
                continue
            if not ch.dry:
                p = store.update({"id": a, "links": [{"id": b, "why": why}]}, now(), source)
                if p:
                    ch.written.add(p)
            added += 1
    ch.add("Orphans", f"{added} link(s) added")


def now() -> dt.datetime:
    return dt.datetime.now(sm.LOCAL_TZ)


# --------------------------------------------------------------------------
# duplicates
# --------------------------------------------------------------------------

DUP_RULES = """You are MIST maintaining your own Zettelkasten. Each PAIR below is two zettels whose text is very close. Judge each pair:
- "duplicate": they state the same idea. Pick the one to keep (the clearer, better linked one), and write "merge" = the facts from the other note that the kept note lacks, in 0-3 sentences (empty if none). The other note will be marked superseded and point to the kept one.
- "related": different ideas with a real relation. Give "why" in 3-8 words.
- "distinct": no relation worth a link.
Two notes about the same system that state different facts are related, not duplicates.

Return ONE JSON object: {"pairs": [{"a": "id", "b": "id", "verdict": "duplicate|related|distinct", "keep": "id", "merge": "...", "why": "..."}]}."""


def _writer_saw(older: str, newer_source: str) -> bool | None:
    """Was `older` among the candidates when the session that made `newer` was written?"""
    sid = None
    stem = newer_source.strip("[]")
    p = sm.SESSIONS / f"{stem}.md"
    if p.exists():
        sid = sm.split_frontmatter(p.read_text(encoding="utf-8"))[0].get("session_id")
    if not sid or not sm.RETRIEVAL_LOG.exists():
        return None
    for ln in sm.RETRIEVAL_LOG.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if d.get("by") == "writer" and d.get("ref") == sid:
            return older in (d.get("shown") or [])
    return None


def step_dupes(store: sm.Store, nb: dict, ch: Change, source: str, limit: int) -> None:
    out, _ = link_graph(store)
    pairs, seen = [], set()
    for z, lst in nb.items():
        for x, cos in lst:
            key = tuple(sorted((z, x)))
            if cos < DUP_COS or key in seen or z not in store.notes or x not in store.notes:
                continue
            seen.add(key)
            if active(store, z) and active(store, x):
                pairs.append((cos, *key))
    pairs.sort(reverse=True)
    ch.add("Duplicates", f"{len(pairs)} active pair(s) at cosine >= {DUP_COS}; {min(len(pairs), limit)} reviewed")
    merged = linked = 0
    for i in range(0, min(len(pairs), limit), 10):
        batch = pairs[i:i + 10]
        payload = "\n\n".join(f"## PAIR {a} / {b} (cosine {cos:.3f})\n{card(store, a)}\n\n{card(store, b)}"
                              for cos, a, b in batch)
        data = ask(DUP_RULES, payload, f"maintain dupes {i}")
        valid = {(a, b) for _, a, b in batch}
        for v in (data or {}).get("pairs") or []:
            if not isinstance(v, dict):
                continue
            a, b = sorted((str(v.get("a") or ""), str(v.get("b") or "")))
            if (a, b) not in valid or not (active(store, a) and active(store, b)):
                continue
            verdict = v.get("verdict")
            if verdict == "duplicate":
                keep = str(v.get("keep") or "")
                if keep not in (a, b):
                    continue
                drop = b if keep == a else a
                older, newer = sorted((a, b))
                newer_src = (store.notes[newer]["meta"].get("sources") or [""])[0]
                saw = _writer_saw(older, newer_src)
                _log_miss(older, newer, saw)
                ch.add("Duplicates", f"merged {store.link(drop)} into {store.link(keep)}"
                       + ("" if saw is None else f" (writer {'was' if saw else 'was not'} shown the older note)"))
                if not ch.dry:
                    merge = str(v.get("merge") or "").strip()
                    if merge:
                        store.update({"id": keep, "append": merge}, now(), source)
                    written, _, _ = sm.apply_ops(store, {"supersede": [
                        {"id": drop, "by": keep, "why": "duplicate merged by the maintenance pass"}]}, now(), source)
                    ch.written.update(written)
                    ch.written.add(store.notes[keep]["path"])
                merged += 1
            elif verdict == "related" and str(v.get("why") or "").strip() and b not in out.get(a, set()):
                if not ch.dry:
                    p = store.update({"id": a, "links": [{"id": b, "why": str(v["why"]).strip()}]}, now(), source)
                    if p:
                        ch.written.add(p)
                linked += 1
    ch.add("Duplicates", f"{merged} merged, {linked} linked as related")


def _log_miss(older: str, newer: str, saw: bool | None) -> None:
    try:
        sm.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with MISS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": now().isoformat(timespec="seconds"), "older": older,
                                 "newer": newer, "writer_shown_older": saw}) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# stale open threads
# --------------------------------------------------------------------------

THREAD_RULES = """You are MIST maintaining your own Zettelkasten. Each THREAD below is an open-thread zettel nobody has touched for two weeks or more, followed by the later zettels and session notes that are closest to it. Decide from that record only:
- "resolved": a later note shows the work was done, decided, or dropped on purpose. Name that note in "evidence" (its id or session note name exactly as shown) and say what closed it in one sentence.
- "open": nothing later closes it.
Do not guess: no evidence means "open". For an open thread, "next" is the one concrete action that would close it (8-15 words).

Return ONE JSON object: {"threads": [{"id": "id", "verdict": "resolved|open", "evidence": "...", "why": "...", "next": "..."}]}."""


def close_ticked(store: sm.Store, ch: Change, source: str) -> None:
    """Threads Alex ticked in an earlier _maintain note: done, or dropped on purpose."""
    n = 0
    for p in sorted(sm.SESSIONS.glob("*_maintain.md")):
        for z in TICKED.findall(p.read_text(encoding="utf-8")):
            if z in store.notes and active(store, z) and store.notes[z]["meta"].get("kind") == "open-thread":
                n += 1
                ch.add("Open threads", f"closed {store.link(z)}: Alex ticked it in [[{p.stem}]]")
                if not ch.dry:
                    q = store.update({"id": z, "status": "resolved",
                                      "append": f"Alex marked this done or dropped in [[{p.stem}]]."}, now(), source)
                    if q:
                        ch.written.add(q)
    if n:
        ch.add("Open threads", f"{n} closed from Alex's ticks")


def step_threads(store: sm.Store, ch: Change, source: str, limit: int) -> None:
    close_ticked(store, ch, source)
    cutoff = f"{today() - dt.timedelta(days=STALE_DAYS):%Y-%m-%d}"
    stale = [z for z, n in store.notes.items() if n["meta"].get("kind") == "open-thread"
             and active(store, z) and str(n["meta"].get("updated") or "") <= cutoff]
    stale.sort(key=lambda z: str(store.notes[z]["meta"].get("updated")))
    ch.add("Open threads", f"{len(stale)} active thread(s) untouched for {STALE_DAYS}+ days; {min(len(stale), limit)} reviewed")
    stale = stale[:limit]
    sessions = [(p, m) for p, m in sm.session_notes() if m.get("type") not in ("skipped", "maintenance")]
    closed = 0
    escalate: list[tuple[str, str]] = []
    for i in range(0, len(stale), 12):
        batch = stale[i:i + 12]
        parts, evidence_ok = [], {}
        for z in batch:
            since = str(store.notes[z]["meta"].get("updated") or "")
            later_z = {x: sm.note_text(n) for x, n in store.notes.items()
                       if str(n["meta"].get("updated") or "") > since and x != z}
            later_s = {p.stem: p.read_text(encoding="utf-8")[:3000] for p, m in sessions
                       if str(m.get("date") or "") > since}
            q = sm.note_text(store.notes[z])
            zh = [x for x, _ in sm.BM25(later_z).search(q, k=4)] if later_z else []
            sh = [x for x, _ in sm.BM25(later_s).search(q, k=3)] if later_s else []
            evidence_ok[z] = set(zh) | set(sh)
            parts.append(f"## THREAD {card(store, z)}\nLater zettels:\n"
                         + ("\n\n".join(card(store, x, 400) for x in zh) or "(none)")
                         + "\nLater session notes:\n"
                         + ("\n\n".join(f"[{s}]\n{sm.split_frontmatter(later_s[s])[1][:900]}" for s in sh) or "(none)"))
        data = ask(THREAD_RULES, "\n\n".join(parts), f"maintain threads {i}")
        decided = set()
        for v in (data or {}).get("threads") or []:
            if not isinstance(v, dict) or str(v.get("id")) not in evidence_ok:
                continue
            z = str(v["id"])
            decided.add(z)
            raw = str(v.get("evidence") or "")
            m = ZID.search(raw) or SESSION_STEM.search(raw)
            ev = m.group(1) if m else raw.strip()
            if v.get("verdict") == "resolved" and ev in evidence_ok[z]:
                ev_link = store.link(ev) if ev in store.notes else f"[[{ev}]]"
                ch.add("Open threads", f"closed {store.link(z)}: {str(v.get('why') or '').strip()} ({ev_link})")
                if not ch.dry:
                    p = store.update({"id": z, "status": "resolved",
                                      "append": f"Closed by the maintenance pass: {str(v.get('why') or '').strip()} "
                                                f"Evidence: {ev_link}.",
                                      "links": [{"id": ev, "why": "closed this thread"}] if ev in store.notes else []},
                                     now(), source)
                    if p:
                        ch.written.add(p)
                closed += 1
            else:
                upd = str(store.notes[z]["meta"].get("updated") or "")
                if upd <= f"{today() - dt.timedelta(days=ESCALATE_DAYS):%Y-%m-%d}":
                    escalate.append((z, str(v.get("next") or "").strip()))
        for z in batch:
            if z not in decided:
                log_line = f"no verdict for {store.link(z)}"
                ch.add("Open threads", log_line)
    ch.add("Open threads", f"{closed} closed with evidence; {len(escalate)} open for {ESCALATE_DAYS}+ days need Alex")
    escalate.sort(key=lambda e: str(store.notes[e[0]]["meta"].get("updated")))
    for z, nxt in escalate[:ALEX_MAX]:
        ch.alex.append(f"- [ ] {store.link(z)}" + (f": {nxt}" if nxt else ""))
    if len(escalate) > ALEX_MAX:
        ch.alex.append(f"\n{len(escalate) - ALEX_MAX} more wait for later passes. Tick a box when the "
                       "thread is done or you are dropping it; the next pass closes it.")
    elif escalate:
        ch.alex.append("\nTick a box when the thread is done or you are dropping it; the next pass closes it.")


# --------------------------------------------------------------------------
# tags
# --------------------------------------------------------------------------

TAG_RULES = """You are MIST maintaining the tag vocabulary of your own Zettelkasten. A tag names the subject a zettel is about (a project, a system, a person, a practice). Below is every tag with its count and sample titles. Find:
- synonyms and spelling variants of one subject ("mist-console" / "console"; "fantasy" / "fantasy-football"),
- tags used once or twice that belong under an existing, more common subject tag,
- broad bucket tags that name no subject ("decision", "misc", "harness-stuff") and the subject tag(s) that should replace them, if any.
Merge only when every note under the old tag would be correctly described by the new one. Prefer the more common, more specific spelling as the target. Leave a tag alone when unsure.
Also list "buckets": tags of any size that name a kind of note or an activity rather than a subject ("follow-up", "gotcha", "verification", "tools", "research", "debugging", "deadline", "preference"). Each zettel already has a kind field for that. A bucket tag is removed from every note that has another tag, and new notes stop using it.

Return ONE JSON object: {"merge": [{"from": ["old-tag", ...], "into": "target-tag", "why": "short reason"}], "buckets": ["tag", ...]}."""


def step_tags(store: sm.Store, ch: Change, source: str) -> None:
    by_tag: dict[str, list[str]] = {}
    for z, n in store.notes.items():
        for t in n["meta"].get("tags") or [] if isinstance(n["meta"].get("tags"), list) else []:
            by_tag.setdefault(t, []).append(z)
    before = len(by_tag)
    rows = [f"{t} ({len(zs)}): " + " | ".join(store.notes[z]["title"][:60] for z in zs[:2])
            for t, zs in sorted(by_tag.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    data = ask(TAG_RULES, "\n".join(rows), "maintain tags")
    moved = 0
    for m in (data or {}).get("merge") or []:
        if not isinstance(m, dict):
            continue
        into = sm.norm_tags([m.get("into")])
        olds = [t for t in sm.norm_tags(m.get("from")) if t in by_tag]
        if not into or not olds:
            continue
        target = into[0]
        olds = [t for t in olds if t != target]
        if not olds:
            continue
        ch.add("Tags", f"{', '.join(olds)} -> {target}: {str(m.get('why') or '').strip()}")
        for old in olds:
            for z in by_tag.get(old, []):
                moved += 1
                if ch.dry:
                    continue
                n = store.notes[z]
                meta, body = sm.split_frontmatter(n["path"].read_text(encoding="utf-8"))
                tags = [target if t == old else t for t in sm.norm_tags(meta.get("tags"))]
                meta["tags"] = list(dict.fromkeys(tags))
                body, links = sm.split_links(body)
                n["path"].write_text(sm.render_zettel(meta, body, links), encoding="utf-8")
                n["meta"] = meta
                ch.written.add(n["path"])
    buckets = sm.bucket_tags() | {t for t in sm.norm_tags((data or {}).get("buckets")) if t in by_tag}
    stripped = 0
    for n in store.notes.values():
        tags = sm.norm_tags(n["meta"].get("tags"))
        keep = [t for t in tags if t not in buckets]
        if keep and len(keep) < len(tags):
            stripped += 1
            if not ch.dry:
                meta, body = sm.split_frontmatter(n["path"].read_text(encoding="utf-8"))
                meta["tags"] = [t for t in sm.norm_tags(meta.get("tags")) if t not in buckets]
                body, links = sm.split_links(body)
                n["path"].write_text(sm.render_zettel(meta, body, links), encoding="utf-8")
                n["meta"] = meta
                ch.written.add(n["path"])
    if not ch.dry:
        sm.BUCKETS.write_text(json.dumps(sorted(buckets), indent=0), encoding="utf-8")
    ch.add("Tags", f"bucket tags: {', '.join(sorted(buckets)) or 'none'}; removed from {stripped} note(s) "
           "that have a subject tag")
    after = len({t for n in store.notes.values() for t in (n["meta"].get("tags") or [])
                 if isinstance(n["meta"].get("tags"), list)})
    ch.add("Tags", f"{moved} tag use(s) rewritten; {before} tags before, {after} after")


# --------------------------------------------------------------------------
# structure notes
# --------------------------------------------------------------------------

STRUCTURE_RULES = """You are MIST writing a structure note for one topic of your own Zettelkasten, the way Luhmann's hub notes worked: a short map into the topic that a reader with no memory of it can enter. Below are the topic's zettels (id | title | kind | status | tags, then how many notes link to each).

Write:
- "overview": 2-4 plain sentences on what this topic covers and how its parts relate.
- "entry": at most 4 zettel ids, the best places to start (the register keeps only a few pointers per keyword; the links lead on from there).
- "sections": 3-8 groups by subtopic. Each has a "heading", a one-sentence "summary", and 2-8 "items" ({"id", "gloss": 4-12 words on why this note matters here}). Prefer active, well-linked notes; leave out notes a reader would not need to find the topic's structure. Resolved and superseded notes appear only when the history matters.

Plain prose, no em dashes, no praise. Return ONE JSON object: {"overview": "...", "entry": ["id"], "sections": [{"heading": "...", "summary": "...", "items": [{"id": "...", "gloss": "..."}]}]}."""


def structure_due(tag: str, count: int, force: bool) -> bool:
    p = STRUCTURE / f"{tag}.md"
    if force or not p.exists():
        return True
    meta, _ = sm.split_frontmatter(p.read_text(encoding="utf-8"))
    try:
        old = int(str(meta.get("members") or 0))
        made = dt.date.fromisoformat(str(meta.get("generated") or "2000-01-01"))
    except ValueError:
        return True
    return (today() - made).days >= STRUCTURE_MAX_AGE_DAYS or abs(count - old) > 0.2 * max(old, 1)


def step_structure(store: sm.Store, ch: Change, force: bool, limit: int) -> None:
    _, inc = link_graph(store)
    by_tag: dict[str, list[str]] = {}
    for z, n in store.notes.items():
        for t in n["meta"].get("tags") or [] if isinstance(n["meta"].get("tags"), list) else []:
            by_tag.setdefault(t, []).append(z)
    buckets = sm.bucket_tags()
    big = {t: zs for t, zs in by_tag.items() if len(zs) > STRUCTURE_MIN and t not in buckets}
    STRUCTURE.mkdir(parents=True, exist_ok=True)
    written = 0
    for tag, zs in sorted(big.items(), key=lambda kv: -len(kv[1])):
        if written >= limit:
            break
        if not structure_due(tag, len(zs), force):
            continue
        zs = sorted(zs, key=lambda z: (not active(store, z), -len(inc[z]), z))[:300]
        rows = "\n".join(f"{store.row(z)} | {len(inc[z])} in" for z in zs)
        data = ask(STRUCTURE_RULES, f"Topic tag: {tag} ({len(by_tag[tag])} zettels)\n\n{rows}",
                   f"maintain structure {tag}")
        if not data:
            continue
        members = set(by_tag[tag])
        entry = [z for z in (data.get("entry") or []) if z in members][:4]
        sections = []
        for s in (data.get("sections") or [])[:8]:
            if not isinstance(s, dict):
                continue
            items = [(str(i.get("id")), str(i.get("gloss") or "").strip()) for i in (s.get("items") or [])
                     if isinstance(i, dict) and str(i.get("id")) in members][:8]
            if items:
                sections.append((str(s.get("heading") or "").strip() or "Notes",
                                 str(s.get("summary") or "").strip(), items))
        if not sections:
            continue
        lines = ["---", "type: structure", f"tag: {sm.yaml_str(tag)}", f"members: {len(by_tag[tag])}",
                 f"generated: {today():%Y-%m-%d}", f"entry: {sm.yaml_list([store.link(z) for z in entry])}", "---",
                 "<!-- generated by scripts/zettel_maintain.py structure; the zettels are the source -->",
                 f"# {tag}", "", str(data.get("overview") or "").strip(), "",
                 "Start here: " + ", ".join(store.link(z) for z in entry) if entry else "", ""]
        for heading, summary, items in sections:
            lines += [f"## {heading}", summary, *(f"- {store.link(z)}" + (f" : {g}" if g else "") for z, g in items), ""]
        lines.append(f"All {len(by_tag[tag])} zettels: [[Maps/{tag}|{tag} map]]")
        if not ch.dry:
            path = STRUCTURE / f"{tag}.md"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ch.written.add(path)
        written += 1
        ch.add("Structure notes", f"[[Structure/{tag}|{tag}]] ({len(by_tag[tag])} zettels, {len(entry)} entry points)")
    ch.add("Structure notes", f"{written} written; {len(big)} tags have more than {STRUCTURE_MIN} zettels")


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def read_ids_from_traces(days: int = 90) -> dict[str, int]:
    """Zettel ids that sessions opened or grepped, from the bin/traces tool_calls table."""
    q = ("copy (select input from tool_calls where input like '%Claude/Zettel%' "
         f"and ts > now() - interval {days} day) to '/dev/stdout' (format json)")
    try:
        r = subprocess.run([str(sm.HARNESS / "bin/traces"), "sql", q], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    counts: dict[str, int] = {}
    for ln in r.stdout.splitlines():
        for z in set(re.findall(r"(\d{12}[a-z]?) ", ln)):
            counts[z] = counts.get(z, 0) + 1
    return counts


def health(store: sm.Store) -> dict:
    out, inc = link_graph(store)
    n = len(store.notes) or 1
    links_total = links_why = 0
    for z in store.notes:
        for ln in sm.split_links(store.notes[z]["body"])[1]:
            links_total += 1
            links_why += " : " in ln
    tags: dict[str, int] = {}
    for x in store.notes.values():
        for t in x["meta"].get("tags") or [] if isinstance(x["meta"].get("tags"), list) else []:
            tags[t] = tags.get(t, 0) + 1
    cutoff = f"{today() - dt.timedelta(days=STALE_DAYS):%Y-%m-%d}"
    threads = [z for z, x in store.notes.items() if x["meta"].get("kind") == "open-thread" and active(store, z)]
    reads = read_ids_from_traces()
    if sm.RETRIEVAL_LOG.exists():
        for ln in sm.RETRIEVAL_LOG.read_text(encoding="utf-8").splitlines():
            try:
                for z in json.loads(ln).get("used") or []:
                    reads[z] = reads.get(z, 0) + 1
            except json.JSONDecodeError:
                continue
    window = [z for z, x in store.notes.items()
              if f"{today() - dt.timedelta(days=90):%Y-%m-%d}" <= str(x["meta"].get("created") or "")
              <= f"{today() - dt.timedelta(days=14):%Y-%m-%d}"]
    return {
        "date": f"{today():%Y-%m-%d}", "zettels": len(store.notes),
        "active": sum(active(store, z) for z in store.notes),
        "no_incoming_pct": round(100 * sum(1 for z in store.notes if not inc[z]) / n, 1),
        "no_outgoing_pct": round(100 * sum(1 for z in store.notes if not out[z]) / n, 1),
        "mean_out_links": round(sum(map(len, out.values())) / n, 2),
        "links_with_reason_pct": round(100 * links_why / max(links_total, 1), 1),
        "tags": len(tags), "tags_used_once": sum(1 for c in tags.values() if c == 1),
        "structure_notes": len(list(STRUCTURE.glob("*.md"))) if STRUCTURE.exists() else 0,
        "open_threads": len(threads),
        "open_threads_stale": sum(1 for z in threads if str(store.notes[z]["meta"].get("updated") or "") <= cutoff),
        "read_within_90d_pct": round(100 * sum(1 for z in window if z in reads) / max(len(window), 1), 1),
        "created_last_7d": sum(1 for x in store.notes.values()
                               if str(x["meta"].get("created") or "") >= f"{today() - dt.timedelta(days=7):%Y-%m-%d}"),
    }


def write_health(h: dict, dry: bool) -> None:
    rows = "\n".join(f"| {k} | {v} |" for k, v in h.items())
    text = ("---\ntype: health\n---\n<!-- generated by scripts/zettel_maintain.py health -->\n# Zettelkasten health\n\n"
            "| metric | value |\n| --- | --- |\n" + rows + "\n\nTrend: ~/Library/Logs/exobrain/zettel-health.jsonl. "
            "Targets: no_incoming_pct under 10, links_with_reason_pct over 90, open_threads_stale under 30, "
            "read_within_90d_pct rising.\n")
    if dry:
        print(text)
        return
    HEALTH.write_text(text, encoding="utf-8")
    sm.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with HEALTH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(h) + "\n")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def wait_for_writers(max_wait: int = 1800) -> bool:
    """Writers hold a lock dir per session; two processes rewriting one zettel lose an edit."""
    import time
    deadline = time.time() + max_wait
    while True:
        live = [p for p in sm.LOCK_DIR.glob("*")
                if time.time() - p.stat().st_mtime < sm.CLAUDE_TIMEOUT_SEC + 60] if sm.LOCK_DIR.exists() else []
        if not live:
            return True
        if time.time() > deadline:
            return False
        time.sleep(30)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--steps", default="embed,orphans,dupes,threads,tags,structure,health")
    ap.add_argument("--limit", type=int, default=200, help="items per step per run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-structure", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="no notification")
    a = ap.parse_args(argv)
    os.environ["MIST_UNATTENDED"] = "1"
    steps = a.steps.split(",")
    if not a.dry_run and not wait_for_writers():
        sm.log("maintain: session writers still running after 30 min; skipped this pass")
        return 1
    sm.ensure_dirs()
    stamp = f"{now():%Y-%m-%d_%H%M}"
    note = sm.SESSIONS / f"{stamp}_maintain.md"
    source = f"[[{note.stem}]]"
    ch = Change(a.dry_run)
    h0 = health(sm.Store())
    if "embed" in steps and not a.dry_run:
        sm.cmd_embed(None)
    nb = sm.load_neighbors()
    for step in ("orphans", "dupes", "threads", "tags", "structure"):
        if step not in steps:
            continue
        store = sm.Store()   # reload: an earlier step changed files
        sm.log(f"maintain: {step}")
        if step == "orphans":
            step_orphans(store, nb, ch, source, a.limit)
        elif step == "dupes":
            step_dupes(store, nb, ch, source, a.limit)
        elif step == "threads":
            step_threads(store, ch, source, a.limit)
        elif step == "tags":
            step_tags(store, ch, source)
        elif step == "structure":
            step_structure(store, ch, a.force_structure, a.limit)
    if not a.dry_run:
        sm.rebuild_index()
    h1 = health(sm.Store())
    if "health" in steps:
        write_health(h1, a.dry_run)
    delta = ", ".join(f"{k} {h0[k]} -> {h1[k]}" for k in ("no_incoming_pct", "tags", "open_threads_stale",
                                                           "links_with_reason_pct") if h0[k] != h1[k])
    body = [f"## Maintenance pass {stamp}", "", f"Health: {delta or 'unchanged'}.", ""]
    for section, lines in ch.lines.items():
        body += [f"## {section}", *(f"- {ln}" for ln in lines), ""]
    if ch.alex:
        body += ["## Open threads that need Alex", *ch.alex, ""]
    meta = {"date": f"{now():%Y-%m-%d}", "time": f"{now():%H:%M}", "type": "maintenance",
            "title": "Zettelkasten maintenance pass", "trigger": "maintain"}
    if a.dry_run:
        print("\n".join(body))
        return 0
    note.write_text(sm.render_session(meta, "\n".join(body)), encoding="utf-8")
    flagged = sm.scan([note, *sorted(ch.written)])
    sm.log(f"maintain: wrote {note.name}, touched {len(ch.written)} file(s)"
           + (f"; SCANNER FLAGGED {len(flagged)} line(s)" if flagged else ""))
    if not a.quiet:
        link = "obsidian://open?vault=Exobrain&file=" + str(note.relative_to(sm.VAULT).with_suffix("")).replace(" ", "%20")
        msg = (f"Zettel maintenance: {len(ch.written)} notes touched; health {delta or 'unchanged'}"
               + (f"; {len(ch.alex)} open threads need you" if ch.alex else "")
               + ("; INJECTION SCAN FLAGGED OUTPUT" if flagged else ""))
        try:
            subprocess.run([str(NOTIFY), msg, "Zettelkasten", "Purr", link, "--discord",
                            "--context", "\n".join(body)[:4000]], timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    print(str(note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
