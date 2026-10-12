"""mcp-lazy: the shim answers from cache without the server, and starts it on a tool call."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SHIM = REPO / "mcp-lazy" / "bin" / "mcp-lazy"

FAKE = r'''
import json, sys, os
open(os.environ["STARTS"], "a").write("start\n")
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        continue
    meth, r = m["method"], None
    if meth == "initialize":
        r = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "1"}}
    elif meth == "tools/list":
        r = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    elif meth == "tools/call":
        r = {"content": [{"type": "text", "text": "pong " + m["params"]["arguments"]["x"]}]}
    print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": r}), flush=True)
'''


class Session:
    def __init__(self, tmp: Path):
        env = {**os.environ, "MCP_LAZY_SERVERS": str(tmp / "servers.json"), "MCP_LAZY_CACHE": str(tmp / "cache"),
               "STARTS": str(tmp / "starts")}
        self.p = subprocess.Popen([sys.executable, "-I", "-S", str(SHIM), "fake"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)

    def req(self, rid, method, params=None):
        assert self.p.stdin and self.p.stdout
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def note(self, method):
        assert self.p.stdin
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.p.stdin.flush()

    def close(self):
        assert self.p.stdin
        self.p.stdin.close()
        self.p.wait(10)


def starts(tmp: Path) -> int:
    f = tmp / "starts"
    return len(f.read_text().splitlines()) if f.exists() else 0


def test_lazy_lifecycle(tmp_path):
    (tmp_path / "fake.py").write_text(FAKE)
    (tmp_path / "servers.json").write_text(json.dumps({"fake": {"command": sys.executable, "args": [str(tmp_path / "fake.py")]}}))

    # First session ever: no cache, so the server starts at initialize and the cache gets written.
    s = Session(tmp_path)
    assert s.req(1, "initialize")["result"]["serverInfo"]["name"] == "fake"
    s.note("notifications/initialized")
    assert s.req(2, "tools/list")["result"]["tools"][0]["name"] == "echo"
    s.close()
    assert starts(tmp_path) == 1
    for _ in range(50):
        if (tmp_path / "cache" / "fake.json").exists():
            break
        time.sleep(0.1)
    assert "tools/list" in json.loads((tmp_path / "cache" / "fake.json").read_text())

    # Second session: initialize, tools/list and ping come from the cache; no server start.
    s = Session(tmp_path)
    assert s.req("a", "initialize")["result"]["serverInfo"]["name"] == "fake"
    s.note("notifications/initialized")
    assert s.req("b", "tools/list")["result"]["tools"][0]["name"] == "echo"
    assert s.req("c", "ping")["result"] == {}
    assert starts(tmp_path) == 1

    # A tool call starts the server and gets the real answer with the client's own id.
    resp = s.req("d", "tools/call", {"name": "echo", "arguments": {"x": "hi"}})
    assert resp["id"] == "d"
    assert resp["result"]["content"][0]["text"] == "pong hi"
    assert starts(tmp_path) == 2
    s.close()


def test_start_failure_is_an_error_response(tmp_path):
    (tmp_path / "servers.json").write_text(json.dumps({"fake": {"command": str(tmp_path / "missing")}}))
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "fake.json").write_text(json.dumps({"initialize": {"capabilities": {"tools": {}}}, "tools/list": {"tools": []}}))
    s = Session(tmp_path)
    s.req(1, "initialize")
    resp = s.req(2, "tools/call", {"name": "x", "arguments": {}})
    assert resp["id"] == 2 and "could not start" in resp["error"]["message"]
    s.close()
