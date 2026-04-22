#!/usr/bin/env python3
"""Download the 6 HPMOR cover.png + contents.pdf files from ianstormtaylor/hpmor."""
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).parent
DOWNLOADS = HERE / "downloads"
DOWNLOADS.mkdir(exist_ok=True)

BASE = "https://raw.githubusercontent.com/ianstormtaylor/hpmor/master"

VOLUME_DIRS = {
    1: "1 - Harry Potter and the Methods of Rationality",
    2: "2 - Harry Potter and the Professor's Games",
    3: "3 - Harry Potter and the Shadows of Death",
    4: "4 - Hermione Granger and the Phoenix's Call",
    5: "5 - Harry Potter and the Last Enemy",
    6: "6 - Harry Potter and the Philosopher's Stone",
}


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  exists: {dest.name}")
        return
    print(f"  fetching: {url}")
    result = subprocess.run(
        ["curl", "-sSLf", "-o", str(dest), url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  FAILED: {result.stderr}", file=sys.stderr)
        dest.unlink(missing_ok=True)
        sys.exit(1)


def main() -> None:
    for num, dirname in VOLUME_DIRS.items():
        print(f"Volume {num}")
        encoded = quote(dirname, safe="")
        fetch(f"{BASE}/{encoded}/cover.png", DOWNLOADS / f"volume-{num}-cover.png")
        fetch(f"{BASE}/{encoded}/contents.pdf", DOWNLOADS / f"volume-{num}-contents.pdf")
    print(f"\nDone. Files in {DOWNLOADS}")


if __name__ == "__main__":
    main()
