"""Photo fingerprints for repost detection: a 64-bit difference hash (dHash) of the card photo.

The search card photo is Facebook's square center crop of the primary photo, so the same photo
posted again gives the same crop, and a recompressed copy differs in a few bits only. Photos come
from the image CDN with no Facebook cookies: the request does not touch the account.
"""

from __future__ import annotations

import io

from shoptools.common import session

_cdn = None


def dhash(data: bytes) -> str:
    """Gray 9x8, one bit per left-right brightness step. 16 hex characters."""
    from PIL import Image   # here, not at the top: the store and its tests do not need Pillow

    img = Image.open(io.BytesIO(data)).convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = img.tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return f"{bits:016x}"


def photo_hash(url: str) -> str:
    global _cdn
    if _cdn is None:
        _cdn = session()
    r = _cdn.get(url, timeout=20)
    if r.status_code != 200:
        raise OSError(f"photo HTTP {r.status_code}")
    return dhash(r.content)
