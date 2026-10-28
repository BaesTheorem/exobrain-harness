"""Tests for job-search/listings.py: near-miss retirement and per-listing folders."""

import json

from conftest import load_script

L = load_script("job-search/listings.py")


def note(status="candidate", **extra):
    fm = {"type": "job-listing", "company": "Acme", "role": "Analyst", "status": status,
          "apply_url": "https://boards.greenhouse.io/acme/jobs/1", **extra}
    return "---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items()) + "---\n# Acme\n\nbody\n"


def setup(tmp_path, monkeypatch):
    root = tmp_path / "Job Listings"
    root.mkdir()
    monkeypatch.setattr(L, "ledger_path", lambda: tmp_path / "ledger.jsonl")
    return root


def test_near_miss_classes():
    assert L.is_near_miss(note("skipped", declined="true"))
    assert L.is_near_miss(note("candidate", declined="true"))
    assert L.is_near_miss(note("candidate", verified="false"))
    assert not L.is_near_miss(note("candidate", verified="true"))
    assert not L.is_near_miss(note("rejected", declined="true"))
    assert not L.is_near_miss(note("skipped", reapply="true"))
    assert not L.is_near_miss(note("closed"))


def test_tidy_retires_to_ledger_and_folds(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    (root / "Acme - Skip.md").write_text(note("skipped", declined="true"))
    (root / "Acme - Live.md").write_text(note("applied", applied="true"))
    done = L.tidy(root, dry=False, min_age=0)
    assert done["retired"] == ["Acme - Skip"] and done["folded"] == ["Acme - Live"]
    assert not (root / "Acme - Skip.md").exists()
    assert (root / "Acme - Live" / "Acme - Live.md").exists()
    rec = json.loads((tmp_path / "ledger.jsonl").read_text().splitlines()[0])
    assert rec["company"] == "Acme" and rec["status"] == "skipped" and "body" in rec["text"]


def test_artifacts_block_retirement(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    d = root / "Acme - Skip"
    d.mkdir()
    (d / "Acme - Skip.md").write_text(note("skipped", declined="true"))
    (d / "Alex_Hedtke_Resume_Acme.pdf").write_bytes(b"%PDF")
    assert L.tidy(root, dry=False, min_age=0)["kept"] == ["Acme - Skip"]
    assert (d / "Acme - Skip.md").exists()


def test_snapshot_only_folder_is_removed_and_restore_round_trips(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    d = root / "Acme - Skip"
    d.mkdir()
    txt = note("skipped", declined="true")
    (d / "Acme - Skip.md").write_text(txt)
    (d / "Acme - Skip - posting 2026-10-01.png").write_bytes(b"png")
    L.tidy(root, dry=False, min_age=0)
    assert not d.exists()
    back = L.restore("Acme - Skip", root)
    assert back.read_text() == txt and L.load_ledger() == []


def test_fold_never_overwrites(tmp_path, monkeypatch):
    root = setup(tmp_path, monkeypatch)
    (root / "Acme - Live").mkdir()
    (root / "Acme - Live" / "Acme - Live.md").write_text(note())
    (root / "Acme - Live.md").write_text(note())
    assert L.tidy(root, dry=False, min_age=0)["clash"] == ["Acme - Live"]
    assert (root / "Acme - Live.md").exists()
