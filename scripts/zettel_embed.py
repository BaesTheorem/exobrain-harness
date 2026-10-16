#!/usr/bin/env python3
"""Embed zettels with nomic-embed-text-v1.5 and write their nearest neighbors.

Runs under a venv that has sentence-transformers (``SESSION_MEMORY_EMBED_PYTHON``,
default The Priory's venv, which already holds the model in the HF cache).
``scripts/session_memory.py embed`` calls it as a subprocess, so the writer
itself stays on the system interpreter and never loads a model.

    zettel_embed.py index <docs.jsonl> <cache_dir> [--k 10]
        docs lines are {"id": ..., "text": ...}. Re-embeds only texts whose hash
        changed, then writes <cache_dir>/vectors.npy, keys.json (id + text hash,
        row order) and neighbors.json (id -> [[id, cosine], ...], best first).
    zettel_embed.py embed <in.jsonl> <out.npy> [--query]
        one normalized row per {"text": ...} line; --query uses nomic's query prefix.

INVARIANTS
- Rows are L2-normalized, so a dot product is a cosine.
- Changing MODEL is a full re-embed: vectors from two models are not comparable,
  so the model name is part of every cache key.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

MODEL = "nomic-ai/nomic-embed-text-v1.5"
_model = None


def encode(texts: list[str], query: bool = False) -> np.ndarray:
    global _model
    if not texts:
        return np.zeros((0, 768), dtype=np.float32)
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL, trust_remote_code=True)
    prefix = "search_query: " if query else "search_document: "
    vecs = _model.encode([prefix + t[:4000] for t in texts], batch_size=16,
                         normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def key(text: str) -> str:
    return hashlib.sha1((MODEL + "\0" + text).encode("utf-8")).hexdigest()[:16]


def cmd_index(docs_path: str, cache: Path, k: int) -> int:
    docs = [json.loads(ln) for ln in open(docs_path, encoding="utf-8") if ln.strip()]
    cache.mkdir(parents=True, exist_ok=True)
    old: dict[str, np.ndarray] = {}
    try:
        keys = json.loads((cache / "keys.json").read_text())
        mat = np.load(cache / "vectors.npy")
        old = {kk: mat[i] for i, kk in enumerate(k_ for _, k_ in keys)}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    want = [(d["id"], key(d["text"]), d["text"]) for d in docs]
    todo = [(i, t) for i, (_, kk, t) in enumerate(want) if kk not in old]
    fresh = encode([t for _, t in todo])
    rows = []
    fi = iter(fresh)
    todo_set = {i for i, _ in todo}
    for i, (_, kk, _) in enumerate(want):
        rows.append(next(fi) if i in todo_set else old[kk])
    mat = np.vstack(rows) if rows else np.zeros((0, 768), dtype=np.float32)
    ids = [zid for zid, _, _ in want]
    np.save(cache / "vectors.npy", mat)
    (cache / "keys.json").write_text(json.dumps([[zid, kk] for zid, kk, _ in want]))
    sims = mat @ mat.T
    np.fill_diagonal(sims, -1.0)
    nb = {}
    for i, zid in enumerate(ids):
        top = np.argsort(-sims[i])[:k]
        nb[zid] = [[ids[j], round(float(sims[i, j]), 4)] for j in top]
    (cache / "neighbors.json").write_text(json.dumps(nb))
    print(f"embedded {len(todo)} new or changed of {len(ids)}", file=sys.stderr)
    return 0


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        return 2
    mode = sys.argv[1]
    if mode == "index":
        k = int(sys.argv[sys.argv.index("--k") + 1]) if "--k" in sys.argv else 10
        return cmd_index(sys.argv[2], Path(sys.argv[3]), k)
    if mode == "embed":
        texts = [json.loads(ln)["text"] for ln in open(sys.argv[2], encoding="utf-8") if ln.strip()]
        np.save(sys.argv[3], encode(texts, query="--query" in sys.argv[4:]))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
