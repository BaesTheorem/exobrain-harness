#!/usr/bin/env python3
"""Held-out recall eval for the session-memory Zettelkasten.

Ground truth comes from the store itself: when the writer UPDATED a zettel that
an earlier session created, that zettel was prior knowledge the later session
needed. Each item is one later session: its first human prompt (from the
bin/traces DuckDB table), its transcript, and the zettels it updated.

Retrieval is scored against the store AS IT WAS before that session: zettels
created on or after the session date are left out, and dated lines appended on
or after it are cut from bodies, so the answer the session wrote cannot leak
into the index it is searched with.

    memory_eval.py build [--since YYYY-MM-DD]     write data/memory-eval/eval.jsonl
    memory_eval.py run [--k 5,10,30] [--methods ...] [--tag NAME]
        score each method for both query types (the first prompt, which is what a
        live session searches with, and the condensed transcript, which is what
        the writer sees) and append the result to data/memory-eval/results.jsonl

``run`` needs numpy and the embedder for the emb/rrf/hybrid methods, so it runs
under SESSION_MEMORY_EMBED_PYTHON; ``build`` runs on any python3. The data dir
is gitignored: it holds Alex's prompts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import session_memory as sm  # noqa: E402

DATA = HERE.parent / "data/memory-eval"
EVAL = DATA / "eval.jsonl"
RESULTS = DATA / "results.jsonl"
ROUTINE = re.compile(r"^(PREFLIGHT|Blocks marked UNTRUSTED|Run the daily|You are an? )")
APPENDED = re.compile(r"\n\n\*(\d{4}-\d{2}-\d{2}):\* ")


def cmd_build(a) -> int:
    store = sm.Store()
    first_src = {z: (n["meta"].get("sources") or [""])[0] for z, n in store.notes.items()}
    q = ("copy (select p.session_id, p.text from prompts p join (select session_id, min(ts) t from prompts "
         "where category='human' group by 1) f on p.session_id=f.session_id and p.ts=f.t "
         "where p.category='human') to '/dev/stdout' (format json)")
    rows = subprocess.run([str(HERE.parent / "bin/traces"), "sql", q], capture_output=True, text=True).stdout
    first: dict[str, str] = {}
    for ln in rows.splitlines():
        try:
            d = json.loads(ln)
            first[d["session_id"]] = d["text"]
        except (json.JSONDecodeError, KeyError):
            pass
    out: dict[str, dict] = {}
    for p, meta in sm.session_notes():
        if str(meta.get("date") or "") < a.since or not meta.get("session_id"):
            continue
        sid = meta["session_id"]
        text = first.get(sid)
        # routine runs open with boilerplate, not a need
        if not text or len(text) < 20 or ROUTINE.match(text):
            continue
        src = f"[[{p.stem}]]"
        gold = []
        for ln in meta.get("zettels") or []:
            m = re.search(r"(\d{12}[a-z]?)", ln)
            if m and m.group(1) in store.notes and first_src[m.group(1)] != src:
                gold.append(m.group(1))
        if gold:
            # deltas share a session id: one item per session, dated by its first note
            item = out.setdefault(sid, {"session_id": sid, "date": meta["date"], "notes": [],
                                        "query": sm.SYSTEM_REMINDER.sub("", text)[:2000], "gold": []})
            item["notes"].append(p.stem)
            item["gold"] = sorted(set(item["gold"]) | set(gold))
    DATA.mkdir(parents=True, exist_ok=True)
    EVAL.write_text("".join(json.dumps(r) + "\n" for r in out.values()))
    print(f"{len(out)} eval items, {sum(len(r['gold']) for r in out.values())} gold zettels -> {EVAL}")
    return 0


def as_of(store: sm.Store, day: str) -> dict[str, str]:
    """id -> indexed text for the zettels that existed before `day`, bodies cut at
    the first line appended on or after it."""
    docs = {}
    for zid, n in store.notes.items():
        if str(n["meta"].get("created") or "") >= day:
            continue
        body = n["body"]
        for m in APPENDED.finditer(body):
            if m.group(1) >= day:
                body = body[: m.start()]
                break
        docs[zid] = sm.note_text(dict(n, body=body))
    return docs


def keyword(docs: dict[str, str], query: str, k: int) -> list[str]:
    """What a session does with rg: rank by how many distinct query words a note contains."""
    q = set(sm.tokens(query))
    scored = [(len(q & set(sm.tokens(t))), z) for z, t in docs.items()]
    return [z for s, z in sorted(scored, reverse=True)[:k] if s]


def cmd_run(a) -> int:
    import numpy as np
    sys.path.insert(0, str(HERE))
    import zettel_embed as ze

    items = [json.loads(ln) for ln in EVAL.open()]
    store = sm.Store()
    ks = [int(x) for x in a.k.split(",")]
    kmax = max(ks)
    methods = a.methods.split(",")
    need_emb = any(m in methods for m in ("emb", "rrf"))
    vec_cache: dict[str, np.ndarray] = {}

    def doc_vecs(docs: dict[str, str]) -> tuple[list[str], np.ndarray]:
        ids = list(docs)
        todo = [z for z in ids if ze.key(docs[z]) not in vec_cache]
        for z, v in zip(todo, ze.encode([docs[z] for z in todo]), strict=True):
            vec_cache[ze.key(docs[z])] = v
        return ids, np.vstack([vec_cache[ze.key(docs[z])] for z in ids])

    transcripts = {}
    for it in items:
        hits = glob.glob(os.path.expanduser(f"~/.claude/projects/*/{it['session_id']}.jsonl"))
        if hits:
            transcripts[it["session_id"]] = sm.condense(Path(hits[0]))["text"]

    snap: dict[str, tuple] = {}
    for day in sorted({it["date"] for it in items}):
        docs = as_of(store, day)
        bm = sm.BM25(docs)
        ids, mat = doc_vecs(docs) if need_emb else ([], None)
        snap[day] = (docs, bm, ids, mat)

    qvec: dict[str, np.ndarray] = {}
    if need_emb:
        qs = [it["query"] for it in items]
        for it, v in zip(items, ze.encode(qs, query=True), strict=True):
            qvec[it["session_id"]] = v

    def rank(method: str, it: dict, qtype: str) -> list[str]:
        docs, bm, ids, mat = snap[it["date"]]
        query = it["query"] if qtype == "prompt" else transcripts.get(it["session_id"], it["query"])
        if method == "keyword":
            return keyword(docs, query, kmax)
        if method == "bm25":
            return [z for z, _ in bm.search(query, k=kmax)]
        if method in ("emb", "rrf"):
            if qtype != "prompt":
                return []   # a transcript is too long to embed as one query
            s = mat @ qvec[it["session_id"]]
            emb = [ids[j] for j in np.argsort(-s)[:kmax]]
            if method == "emb":
                return emb
            fused: dict[str, float] = {}
            for lst in (emb, [z for z, _ in bm.search(query, k=kmax)]):
                for r, z in enumerate(lst):
                    fused[z] = fused.get(z, 0.0) + 1.0 / (60 + r)
            return sorted(fused, key=lambda z: -fused[z])[:kmax]
        raise SystemExit(f"unknown method {method}")

    result = {"at": dt.datetime.now().isoformat(timespec="seconds"), "tag": a.tag,
              "items": len(items), "zettels": len(store.notes), "scores": {}}
    print(f"{len(items)} items, gold kept as of each session date")
    for qtype in ("prompt", "transcript"):
        for method in methods:
            if method in ("emb", "rrf") and qtype == "transcript":
                continue
            hit = {k: 0 for k in ks}
            total = 0
            for it in items:
                docs = snap[it["date"]][0]
                gold = [g for g in it["gold"] if g in docs]
                if not gold:
                    continue
                got = rank(method, it, qtype)
                total += len(gold)
                for k in ks:
                    hit[k] += len(set(got[:k]) & set(gold))
            row = {f"R@{k}": round(hit[k] / max(total, 1), 3) for k in ks}
            result["scores"][f"{qtype}/{method}"] = row
            print(f"  {qtype:10s} {method:8s} " + "  ".join(f"{kk} {v:.3f}" for kk, v in row.items())
                  + f"   (gold {total})")
    DATA.mkdir(parents=True, exist_ok=True)
    with RESULTS.open("a") as fh:
        fh.write(json.dumps(result) + "\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--since", default="2026-10-08")
    b.set_defaults(fn=cmd_build)
    r = sub.add_parser("run")
    r.add_argument("--k", default="5,10,40,200")
    r.add_argument("--methods", default="keyword,bm25,emb,rrf")
    r.add_argument("--tag", default="")
    r.set_defaults(fn=cmd_run)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
