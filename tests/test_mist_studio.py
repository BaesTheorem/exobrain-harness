"""MIST Studio: request clamping, the Space parameter map, the job queue, and
the on-disk library. No GPU and no network; the Space is a fake API dict."""

import os
import sys
import time

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "mist-music"))

from studio import engine, jobs, library  # noqa: E402


# -- GenRequest -------------------------------------------------------------

def test_from_dict_clamps_and_defaults():
    r = engine.GenRequest.from_dict({
        "task": "bogus", "steps": 99, "batch_size": 40, "duration": 5, "bpm": 900,
        "cover_strength": 3, "seed": "-1", "lm_top_p": 7, "vocal_language": "klingon",
        "model": "nope", "audio_format": "wav", "time_signature": "9",
    })
    assert r.task == "text2music"
    assert r.steps == 20 and r.batch_size == 8
    assert r.duration == 10 and r.bpm == 300
    assert r.cover_strength == 1.0 and r.seed is None and r.lm_top_p == 1.0
    assert r.vocal_language == "unknown" and r.model == engine.MODELS[0]
    assert r.audio_format == "mp3" and r.time_signature == ""


def test_instrumental_forces_lyrics_tag_and_language():
    r = engine.GenRequest.from_dict({"caption": "jazz", "lyrics": "la la", "instrumental": True,
                                     "vocal_language": "en"})
    assert r.effective_lyrics() == engine.INSTRUMENTAL_TAG
    assert r.vocal_language == "unknown"


def test_validate_requires_source_for_cover_and_content_for_text2music():
    with pytest.raises(engine.EngineError):
        engine.GenRequest.from_dict({"task": "cover", "caption": "x"}).validate()
    with pytest.raises(engine.EngineError):
        engine.GenRequest.from_dict({"task": "text2music"}).validate()
    engine.GenRequest.from_dict({"caption": "lo-fi"}).validate()
    engine.GenRequest.from_dict({"generation_mode": "simple", "description": "a song"}).validate()


# -- Space parameter map ----------------------------------------------------

def _fake_api():
    """The 49-slot /generation_wrapper signature as the live Space reports it."""
    names = ["selected_model", "generation_mode", "simple_query_input", "simple_vocal_language"]
    names += [f"param_{i}" for i in range(4, 40)] + [f"param_{i}" for i in range(41, 50)]
    assert len(names) == 49
    labels = {"param_10": "DiT Inference Steps", "param_16": "batch size", "param_17": "Source Audio",
              "param_30": "Audio Format", "param_43": "Get Scores", "param_44": "Get LRC"}
    params = [{"parameter_name": n, "label": labels.get(n, n), "parameter_default": None} for n in names]
    return {"named_endpoints": {"/generation_wrapper": {"parameters": params, "returns": []}}}


def test_vector_writes_every_logical_field_by_name():
    eng = engine.SpaceEngine("fake/space", None)
    eng._api = _fake_api()
    req = engine.GenRequest.from_dict({"caption": "surf rock", "lyrics": "[Verse]\nhi", "seed": 7,
                                       "batch_size": 3, "steps": 12, "duration": 90, "bpm": 140})
    vec = eng._vector(req)
    assert len(vec) == 49
    idx = {n: i for i, n in enumerate(p["parameter_name"] for p in
                                      eng._api["named_endpoints"]["/generation_wrapper"]["parameters"])}
    assert vec[idx["param_4"]] == "surf rock"
    assert vec[idx["param_5"]] == "[Verse]\nhi"
    assert vec[idx["param_6"]] == 140.0
    assert vec[idx["param_10"]] == 12
    assert vec[idx["param_12"]] is False and vec[idx["param_13"]] == "7"
    assert vec[idx["param_15"]] == 90.0 and vec[idx["param_16"]] == 3
    assert vec[idx["param_21"]] == engine.TASK_INSTRUCTIONS["text2music"]
    assert vec[idx["param_23"]] == "text2music" and vec[idx["generation_mode"]] == "custom"
    assert vec[idx["param_43"]] is False and vec[idx["param_44"]] is False
    assert vec[idx["param_47"]] == "strings" and vec[idx["param_48"]] == []
    assert eng.drift == []


def test_vector_cover_mode_uses_cover_task_and_source_length(tmp_path):
    src = tmp_path / "src.mp3"
    src.write_bytes(b"x")
    eng = engine.SpaceEngine("fake/space", None)
    eng._api = _fake_api()
    req = engine.GenRequest.from_dict({"task": "cover", "caption": "bossa nova", "cover_strength": 0.4,
                                       "duration": 120, "src_audio": str(src)})
    # handle_file needs gradio_client; stub it so the mapping is testable offline
    import types
    fake = types.ModuleType("gradio_client")
    setattr(fake, "handle_file", lambda p: {"path": p})  # noqa: B010 - stub module attribute
    sys.modules["gradio_client"] = fake
    try:
        vec = eng._vector(req)
    finally:
        del sys.modules["gradio_client"]
    params = eng._api["named_endpoints"]["/generation_wrapper"]["parameters"]
    idx = {p["parameter_name"]: i for i, p in enumerate(params)}
    assert vec[idx["generation_mode"]] == "cover" and vec[idx["param_23"]] == "cover"
    assert vec[idx["param_15"]] == -1.0          # cover output matches the source length
    assert vec[idx["param_22"]] == 0.4
    assert vec[idx["param_17"]] == {"path": str(src)}
    assert vec[idx["param_21"]] == engine.TASK_INSTRUCTIONS["cover"]


def test_drift_is_reported_when_the_space_moves_a_slot():
    eng = engine.SpaceEngine("fake/space", None)
    api = _fake_api()
    api["named_endpoints"]["/generation_wrapper"]["parameters"][42]["label"] = "Something Else"
    eng._api = None
    eng._client = type("C", (), {"view_api": lambda self, return_format: api})()
    eng.api()
    assert any("param_43" in d for d in eng.drift)


def test_quota_error_parsing():
    err = engine.classify_error(RuntimeError(
        "You have exceeded your free ZeroGPU quota (180s requested vs. 84s left). "
        "Try again in 23:55:16. Subscribe to PRO"))
    assert isinstance(err, engine.QuotaError)
    assert err.retry_in == 23 * 3600 + 55 * 60 + 16
    assert err.requested == 180 and err.left == 84
    assert not isinstance(engine.classify_error(RuntimeError("boom")), engine.QuotaError)


# -- job queue --------------------------------------------------------------

def test_queue_runs_in_order_and_cancels_queued_jobs():
    q = jobs.JobQueue()
    seen = []

    def slow(job):
        time.sleep(0.2)
        seen.append(job.payload["n"])
        return job.payload["n"]

    a = q.submit("t", {"n": 1}, slow)
    b = q.submit("t", {"n": 2}, slow)
    c = q.submit("t", {"n": 3}, slow)
    assert q.cancel(b.id) is True
    deadline = time.time() + 5
    while time.time() < deadline and c.status not in ("done", "error"):
        time.sleep(0.05)
    assert a.status == "done" and a.result == 1
    assert b.status == "cancelled"
    assert c.status == "done" and seen == [1, 3]


def test_queue_records_errors_with_retry_hint():
    q = jobs.JobQueue()

    def boom(job):
        raise engine.QuotaError("spent", retry_in=42)

    j = q.submit("t", {}, boom)
    deadline = time.time() + 5
    while time.time() < deadline and j.status == "queued" or j.status == "running":
        time.sleep(0.05)
    assert j.status == "error" and j.error == "spent" and j.retry_in == 42
    assert j.error_kind == "QuotaError"


# -- library ----------------------------------------------------------------

@pytest.fixture
def lib_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setattr(library, "UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(library, "probe_duration", lambda p: 12.5)
    return tmp_path


def test_library_add_list_update_delete(lib_dirs, tmp_path):
    take = tmp_path / "take.mp3"
    take.write_bytes(b"ID3fake")
    m = library.add_song(str(take), {"caption": "surf rock, upbeat", "lyrics": "[Verse]\nFirst line here"})
    assert m["title"] == "First line here"
    assert m["duration"] == 12.5
    assert os.path.isfile(library.song_path(m["id"]))
    assert library.list_songs()[0]["id"] == m["id"]
    assert library.list_songs(query="surf")[0]["id"] == m["id"]
    assert library.list_songs(query="polka") == []
    library.update_song(m["id"], {"favorite": True, "title": "", "secret": "no"})
    got = library.get_song(m["id"])
    assert got["favorite"] is True and got["title"] == "First line here" and "secret" not in got
    assert library.list_songs(favorites=True)[0]["id"] == m["id"]
    assert library.delete_song(m["id"]) is True
    assert library.get_song(m["id"]) is None
    assert library.get_song("../etc") is None


def test_uploads_and_source_resolution(lib_dirs, tmp_path):
    import io
    with pytest.raises(ValueError):
        library.add_upload(io.BytesIO(b"x"), "notes.txt")
    up = library.add_upload(io.BytesIO(b"RIFFfake"), "My Song.wav")
    assert up["name"] == "My Song.wav" and library.upload_path(up["id"]).endswith(".wav")
    assert library.resolve_source("upload", up["id"]) == library.upload_path(up["id"])
    assert library.resolve_source("upload", "nope") is None
    sd = library.upload_stems_dir(up["id"])
    os.makedirs(sd)
    with open(os.path.join(sd, "vocals.mp3"), "wb") as f:
        f.write(b"x")
    assert library.get_upload(up["id"])["stems"] == {"vocals": "vocals.mp3"}
    assert library.resolve_source("stem", f"upload:{up['id']}:vocals").endswith("vocals.mp3")
    assert library.resolve_source("stem", f"upload:{up['id']}:../x") is None
    assert library.delete_upload(up["id"]) is True and library.list_uploads() == []
