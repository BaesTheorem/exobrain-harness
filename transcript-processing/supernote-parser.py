#!/usr/bin/env python3
"""
Extract PNG page images from Supernote .note files using supernotelib.

Usage:
    python3 supernote-parser.py <note_file> <output_dir>
    python3 supernote-parser.py /path/to/file.note /tmp/pages

Outputs one PNG per page: page_0.png, page_1.png, etc.
Prints JSON summary to stdout for Claude to parse.
"""

import hashlib
import json
import os
import sys

import supernotelib


def sha256_file(path: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pages(note_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)

    with open(note_path, "rb") as f:
        notebook = supernotelib.load(f)

    total_pages = notebook.get_total_pages()
    converter = supernotelib.converter.ImageConverter(notebook)

    pages = []
    page_hashes = {}
    for i in range(total_pages):
        out_path = os.path.join(output_dir, f"page_{i}.png")
        img = converter.convert(i)
        img.save(out_path)
        pages.append(out_path)
        page_hashes[str(i)] = sha256_file(out_path)

    return {
        "source": note_path,
        "total_pages": total_pages,
        "output_dir": output_dir,
        "pages": pages,
        "page_hashes": page_hashes,
    }


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <note_file> <output_dir>", file=sys.stderr)
        sys.exit(1)

    result = extract_pages(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
