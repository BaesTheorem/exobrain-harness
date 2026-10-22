"""offline-library/kiwix_sync.py: version pick, metalink parse, swap invariant."""

import hashlib

from conftest import load_script

ks = load_script("offline-library/kiwix_sync.py")

LISTING = """
<a href="wikipedia_en_all_maxi_2026-02.zim">wikipedia_en_all_maxi_2026-02.zim</a>
<a href="wikipedia_en_all_maxi_2026-08.zim">wikipedia_en_all_maxi_2026-08.zim</a>
<a href="wikipedia_en_all_maxi_2026-09.zim.torrent">x</a>
<a href="wikipedia_en_all_nopic_2026-10.zim">wikipedia_en_all_nopic_2026-10.zim</a>
"""

META4 = """<?xml version="1.0" encoding="UTF-8"?>
<metalink xmlns="urn:ietf:params:xml:ns:metalink">
  <file name="{name}"><size>{size}</size>
    <hash type="md5">00</hash><hash type="sha-256">{sha}</hash>
  </file>
</metalink>"""

CFG = {"mirror": "https://mirror.test/zim", "volume": "Test SSD", "min_free_margin_gb": 0}
BOOK = {"name": "wikipedia_en_all_maxi", "dir": "wikipedia"}


def test_newest_version_ignores_other_flavours_and_sidecars():
    assert ks.versions_in_listing(LISTING, "wikipedia_en_all_maxi") == ["2026-02", "2026-08"]


def test_parse_meta4():
    size, sha = ks.parse_meta4(META4.format(name="a.zim", size=12, sha="ABC").encode())
    assert (size, sha) == (12, "abc")


def _run(tmp_path, monkeypatch, payload, claimed_sha):
    monkeypatch.setenv("KIWIX_SYNC_NO_NOTIFY", "1")
    (tmp_path / "wikipedia_en_all_maxi_2026-02.zim").write_bytes(b"old")
    meta = META4.format(name="x", size=len(payload), sha=claimed_sha).encode()
    monkeypatch.setattr(ks, "fetch", lambda url, timeout=60: meta if url.endswith(".meta4") else LISTING.encode())

    def fake_download(_url, partial):
        (partial / "wikipedia_en_all_maxi_2026-08.zim").write_bytes(payload)
        return 0

    monkeypatch.setattr(ks, "download", fake_download)
    state = ks.State(tmp_path / ".kiwix-sync.json")
    return ks.sync_book(BOOK, CFG, tmp_path, state, dry_run=False)


def test_verified_download_replaces_old(tmp_path, monkeypatch):
    payload = b"new dump"
    result = _run(tmp_path, monkeypatch, payload, hashlib.sha256(payload).hexdigest())
    assert result == "updated"
    assert ks.local_versions(tmp_path, "wikipedia_en_all_maxi") == ["2026-08"]


def test_hash_mismatch_keeps_old_and_drops_partial(tmp_path, monkeypatch):
    result = _run(tmp_path, monkeypatch, b"corrupt", "0" * 64)
    assert result == "failed"
    assert ks.local_versions(tmp_path, "wikipedia_en_all_maxi") == ["2026-02"]
    assert not list((tmp_path / ".partial").glob("*.zim"))
