"""Tests for location/receiver.py and location/where.py (synthetic points only)."""

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "location" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


receiver = _load("receiver")
where = _load("where")

A = (39.0500, -94.5800)
B = (39.1000, -94.5800)  # about 5.6 km north of A


def _pt(dt, ll, motion=()):
    return {"t": dt.isoformat(), "dt": dt, "lat": ll[0], "lon": ll[1], "p": {"motion": list(motion)}}


def _day():
    t = datetime(2026, 10, 5, 8, 0).astimezone()
    pts = [_pt(t + timedelta(minutes=m), A) for m in range(0, 60, 5)]
    for k in range(1, 6):  # 10 min drive, A to B
        frac = k / 6
        ll = (A[0] + (B[0] - A[0]) * frac, A[1])
        pts.append(_pt(t + timedelta(minutes=60 + 2 * k), ll, ["driving"]))
    pts += [_pt(t + timedelta(minutes=m), B) for m in range(72, 140, 5)]
    return pts


def test_segment_stay_move_stay():
    segs = where.segment(_day())
    kinds = [s["kind"] for s in segs]
    assert kinds == ["stay", "move", "stay"]
    move = segs[1]
    assert move["mode"] == "driving"
    assert 5000 < move["meters"] < 6500


def test_gap_is_reported_not_hidden():
    t = datetime(2026, 10, 5, 8, 0).astimezone()
    pts = [_pt(t, A), _pt(t + timedelta(minutes=1), (A[0] + 0.01, A[1])),
           _pt(t + timedelta(hours=4), B), _pt(t + timedelta(hours=4, minutes=1), (B[0] + 0.01, B[1]))]
    segs = where.segment(pts)
    assert "gap" in [s["kind"] for s in segs]


def test_summary_names_home(monkeypatch):
    segs = where.segment(_day())
    env = {"MYKCMO_HOME_LAT": str(A[0]), "MYKCMO_HOME_LON": str(A[1])}
    monkeypatch.setattr(where, "PLACES_FILE", ROOT / "nonexistent.json")
    where.name_stays(segs, env, offline=True)
    summary = where.summarize("2026-10-05", _day(), segs)
    assert summary["segments"][0]["place"] == "Home"
    assert summary["left_home"] is True


def test_receiver_parses_overland_batch(tmp_path):
    batch = {"locations": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-94.58, 39.05]},
         "properties": {"timestamp": "2026-10-05T08:00:00-0500", "horizontal_accuracy": 10}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-94.58, 39.05]},
         "properties": {"timestamp": "2026-10-05T08:05:00Z"}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": []}, "properties": {}},
    ]}
    pairs = receiver.to_records(batch)
    assert len(pairs) == 2
    counts = receiver.append_records(pairs, points_dir=tmp_path)
    assert sum(counts.values()) == 2
    lines = [json.loads(x) for f in tmp_path.iterdir() for x in f.read_text().splitlines()]
    assert {r["lat"] for r in lines} == {39.05}


def test_google_both_export_formats():
    ios = [{"startTime": "2026-10-05T08:00:00.000-05:00", "endTime": "2026-10-05T09:00:00.000-05:00",
            "visit": {"topCandidate": {"placeLocation": "geo:39.050000,-94.580000"}}},
           {"startTime": "2026-10-05T09:00:00.000-05:00", "endTime": "2026-10-05T10:00:00.000-05:00",
            "timelinePath": [{"point": "geo:39.06,-94.58", "durationMinutesOffsetFromStartTime": "5"}]}]
    android = {"semanticSegments": [
        {"startTime": "2026-10-05T08:00:00.000-05:00", "endTime": "2026-10-05T09:00:00.000-05:00",
         "visit": {"topCandidate": {"placeLocation": {"latLng": "39.0500000°, -94.5800000°"}}}},
        {"startTime": "2026-10-05T09:00:00.000-05:00", "endTime": "2026-10-05T10:00:00.000-05:00",
         "timelinePath": [{"point": "39.06°, -94.58°", "time": "2026-10-05T09:05:00.000-05:00"}]}]}
    for data in (ios, android):
        pts = list(where.google_points(data))
        assert len(pts) == 3
        assert pts[0]["lat"] == 39.05 and pts[0]["lon"] == -94.58
        assert pts[2]["t"].startswith("2026-10-05")
