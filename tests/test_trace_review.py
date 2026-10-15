"""traces/trace_review.py (trace condensing, labels) and the review server's access rules."""

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from conftest import load_script

tr = load_script("traces/trace_review.py")

REPO = Path(__file__).resolve().parent.parent
PY = REPO / "traces" / ".venv" / "bin" / "python"
FILE_ID = "-Users-x-proj/11111111-2222-3333-4444-555555555555.jsonl"


def line(**o) -> str:
    return json.dumps(o)


TRANSCRIPT = [
    line(type="user", timestamp="2026-10-01T10:00:00Z", message={"role": "user", "content": "Turn the lights off"}),
    line(type="assistant", timestamp="2026-10-01T10:00:02Z", message={"id": "m1", "model": "claude-x", "content": [
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "lights off --all"}}]}),
    line(type="user", timestamp="2026-10-01T10:00:03Z", message={"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "unknown flag --all"}]}),
    line(type="assistant", timestamp="2026-10-01T10:00:05Z", message={"id": "m2", "model": "claude-x", "content": [
        {"type": "text", "text": "Done. All four lights are off."}]}),
    line(type="user", timestamp="2026-10-01T09:59:58Z", message={"role": "user", "content": "[Request interrupted by user]"}),
    line(type="cost-state", totalCostUSD=0.5),
]


def test_condense_builds_turns_with_tool_errors_and_reply():
    out = tr.condense_lines(TRANSCRIPT, FILE_ID)
    (turn,) = out["turns"]
    assert turn["prompt"]["category"] == "human" and turn["prompt"]["text"] == "Turn the lights off"
    assert turn["reply"] == "Done. All four lights are off."
    assert (turn["n_tools"], turn["n_errors"]) == (1, 1)
    tool = next(s for s in turn["steps"] if s["type"] == "tool")
    assert tool["summary"] == "lights off --all" and tool["result"] == "unknown flag --all"
    assert any(s["type"] == "note" and s["category"] == "interrupt" for s in turn["steps"])
    assert (out["first_ts"], out["last_ts"]) == ("2026-10-01T09:59:58Z", "2026-10-01T10:00:05Z")
    assert out["models"] == ["claude-x"] and out["cost_usd"] == 0.5


def test_short_labels():
    assert tr.short_label(None, None, "<!-- session-memory-writer --> You are MIST") == "Session memory writer"
    assert tr.short_label(None, None, '<scheduled-task name="weekly-backup" file="x">') == "Scheduled task: weekly-backup"
    assert tr.short_label(None, None, "<command-message>x</command-message> <command-name>/fantasy</command-name>") == "/fantasy"
    assert tr.short_label("Lights", "turn them off", None) == "Lights"


def test_newest_label_wins_and_bad_verdicts_are_refused(tmp_path):
    tr.add_label("s", "a", "fail", "first try", tmp_path)
    tr.add_label("s", "a", "pass", "  second  ", tmp_path)
    assert tr.labels(tmp_path)["a"]["verdict"] == "pass"
    assert tr.labels(tmp_path)["a"]["note"] == "second"
    with pytest.raises(ValueError):
        tr.add_label("s", "a", "maybe", "", tmp_path)


@pytest.fixture
def server(tmp_path):
    if not PY.exists():
        pytest.skip("traces/.venv not built (see traces/README.md)")
    labels, archive = tmp_path / "labels", tmp_path / "archive"
    labels.mkdir()
    (labels / "s1.json").write_text(json.dumps({"name": "s1", "window": [], "items": [
        {"file_id": FILE_ID, "stratum": "chat", "title": None, "first_prompt": "Turn the lights off",
         "n_human_prompts": 1, "n_tool_calls": 1, "n_tool_errors": 1, "cost_usd": 0.5}]}))
    target = archive / (FILE_ID + ".zst")
    target.parent.mkdir(parents=True)
    pack = "import sys; from compression import zstd; open(sys.argv[1], 'wb').write(zstd.compress(sys.stdin.buffer.read()))"
    subprocess.run([str(PY), "-c", pack, str(target)], input="\n".join(TRANSCRIPT).encode(), check=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    code = ("import sys, pathlib; sys.path.insert(0, sys.argv[1]); import trace_server; "
            "trace_server.serve('s1', int(sys.argv[2]), pathlib.Path(sys.argv[3]), pathlib.Path(sys.argv[4]), 'tok')")
    proc = subprocess.Popen([str(PY), "-c", code, str(REPO / "traces"), str(port), str(labels), str(archive)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    yield base, port, labels
    proc.terminate()
    proc.wait(timeout=5)


def call(url, token="tok", body=None, host=None, raw=None):
    headers = {"X-Review-Token": token}
    if host:
        headers["Host"] = host
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read() or b"{}"), res.headers
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"{}"), err.headers


def test_api_needs_token_and_local_host(server):
    base, port, _ = server
    assert call(base + "/api/sample", token="")[0] == 403
    assert call(base + "/api/sample", token="wrong")[0] == 403
    assert call(base + "/api/sample", host=f"evil.example:{port}")[0] == 403
    status, data, _ = call(base + "/api/sample")
    assert status == 200 and len(data["items"]) == 1 and data["tally"]["total"] == 1


def test_only_sample_sessions_and_listed_files_are_served(server):
    base, _, _ = server
    assert call(base + "/api/trace?id=-Users-x-proj/other.jsonl")[0] == 404
    assert call(base + "/beer/../../trace_server.py")[0] == 404
    status, data, _ = call(base + "/api/trace?id=" + FILE_ID)
    assert status == 200 and data["turns"][0]["n_errors"] == 1
    with urllib.request.urlopen(base + "/", timeout=5) as res:
        assert "script-src 'self'" in res.headers["Content-Security-Policy"]


def test_labels_are_validated_and_appended(server):
    base, _, labels = server
    assert call(base + "/api/label", body={"id": FILE_ID, "verdict": "maybe", "note": ""})[0] == 400
    assert call(base + "/api/label", body={"id": "-Users-x-proj/other.jsonl", "verdict": "pass"})[0] == 404
    assert call(base + "/api/label", raw=b"x" * 20_000)[0] == 413
    status, data, _ = call(base + "/api/label", body={"id": FILE_ID, "verdict": "fail", "note": "used a bad flag"})
    assert status == 200 and data["tally"]["fail"] == 1
    rows = [json.loads(x) for x in (labels / "labels.jsonl").read_text().splitlines()]
    assert [(r["verdict"], r["note"]) for r in rows] == [("fail", "used a bad flag")]
