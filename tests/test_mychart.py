"""mychart: store, change detection, write guards, the bridge, FHIR, EHI.

No test touches the network, the real Keychain, or a real MyChart account.
The bridge tests run bridge.mjs against a stub engine written to tmp_path.
"""

import base64
import hashlib
import http.server
import json
import shutil
import sqlite3
import sys
import threading
import zipfile
from pathlib import Path

import pytest

ISLAND = Path(__file__).resolve().parent.parent / "mychart"
sys.path.insert(0, str(ISLAND))

import mychart_cli as cli  # noqa: E402
import mychart_core as core  # noqa: E402
import mychart_ehi as ehi  # noqa: E402
import mychart_fhir as fhir  # noqa: E402
import mychart_store as st  # noqa: E402

# The real Keychain functions, kept before the autouse fixture swaps them out.
REAL_KEYCHAIN_GET, REAL_KEYCHAIN_SET = core.keychain_get, core.keychain_set


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own data dir and an in-memory Keychain."""
    monkeypatch.setenv("MYCHART_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MIST_UNATTENDED", raising=False)
    vault: dict[str, str] = {}
    monkeypatch.setattr(core, "keychain_get", lambda key: vault.get(key))
    monkeypatch.setattr(core, "keychain_set", lambda key, value: vault.__setitem__(key, value))
    monkeypatch.setattr(core, "keychain_delete", lambda key: vault.pop(key, None) is not None)
    return vault


def lab_standard(*results):
    """results: (key, name, when, status, result_type, components)"""
    orders = []
    for key, name, when, status, rtype, comps in results:
        orders.append({"orderName": name, "key": key, "results": [{
            "name": name, "key": key, "isAbnormal": False,
            "orderMetadata": {"prioritizedInstantISO": when, "latestUpdateInstantISO": when,
                              "resultStatus": status, "resultType": rtype,
                              "collectionTimestampsDisplay": "Jan 10, 2026 9:00 AM",
                              "resultingLab": {"name": "Lab A"}},
            "resultComponents": [{"componentInfo": {"componentID": cid, "name": cname, "units": "mg/dL"},
                                  "componentResultInfo": {"valueText": str(val), "numericValue": val,
                                                          "referenceRange": {"low": 0, "high": 100,
                                                                             "formattedReferenceRange": "0 - 100"}}}
                                 for cid, cname, val in comps],
        }]})
    return {"orders": orders}


def action(capability, standard, ok=True, envelope=None):
    return {"event": "action", "id": capability, "ok": ok, "args": {}, "standard": standard,
            "envelope": envelope if envelope is not None else {"requests": [{"path": "/x", "body": standard}]},
            "error": None if ok else {"name": "MyChartResponseError", "message": "500"}}


# ── store and change detection ──────────────────────────────────────────────


def test_first_read_is_a_baseline_and_never_notifies(tmp_path):
    s = st.Store(tmp_path / "s.db")
    res = s.record_snapshot(1, "north", action("get_lab_results", lab_standard(
        ("R1", "CMP", "2026-01-10T10:30:00", "Final", "LAB", [("GLU", "Glucose", 92)]))))
    assert res["baseline"] is True
    assert [c["change"] for c in res["changes"]] == ["new"]
    assert not any(c["notify"] for c in res["changes"])


def test_new_result_after_baseline_notifies_and_status_change_counts(tmp_path):
    s = st.Store(tmp_path / "s.db")
    first = ("R1", "CMP", "2026-01-10T10:30:00", "Final", "LAB", [("GLU", "Glucose", 92)])
    s.record_snapshot(1, "north", action("get_lab_results", lab_standard(first)))
    second = ("R2", "Lipid", "2026-03-01T08:00:00", "Preliminary", "LAB", [("LDL", "LDL", 150)])
    res = s.record_snapshot(2, "north", action("get_lab_results", lab_standard(first, second)))
    assert [(c["change"], c["notify"]) for c in res["changes"]] == [("new", True)]
    final = ("R2", "Lipid", "2026-03-01T08:00:00", "Final", "LAB", [("LDL", "LDL", 150)])
    res = s.record_snapshot(3, "north", action("get_lab_results", lab_standard(first, final)))
    assert [(c["change"], c["notify"]) for c in res["changes"]] == [("changed", True)]


def test_unchanged_read_has_no_changes_and_stores_no_new_blob(tmp_path):
    s = st.Store(tmp_path / "s.db")
    std = lab_standard(("R1", "CMP", "2026-01-10T10:30:00", "Final", "LAB", [("GLU", "Glucose", 92)]))
    s.record_snapshot(1, "north", action("get_lab_results", std))
    blobs = s.db.execute("SELECT count(*) FROM blobs").fetchone()[0]
    res = s.record_snapshot(2, "north", action("get_lab_results", std, envelope={"requests": [{"body": "new token"}]}))
    assert res["changes"] == []
    assert s.db.execute("SELECT count(*) FROM blobs").fetchone()[0] == blobs


def test_fresh_tokens_alone_are_not_a_change(tmp_path):
    s = st.Store(tmp_path / "s.db")
    first = {"items": [{"Name": "Flu shot", "ContentLinkURL": "/x?t=aaa"}], "queryKey": "k1"}
    again = {"items": [{"Name": "Flu shot", "ContentLinkURL": "/x?t=bbb"}], "queryKey": "k2"}
    s.record_snapshot(1, "north", action("get_preventive_care", first))
    assert s.record_snapshot(2, "north", action("get_preventive_care", again))["changes"] == []
    moved = {"items": [{"Name": "Flu shot", "Status": "Due", "ContentLinkURL": "/x?t=ccc"}], "queryKey": "k3"}
    assert [c["change"] for c in s.record_snapshot(3, "north", action("get_preventive_care", moved))["changes"]] == ["changed"]


def test_failed_read_never_marks_items_gone(tmp_path):
    s = st.Store(tmp_path / "s.db")
    visits = {"visits": [{"Csn": "C1", "instantISO": "2026-11-01T15:00:00Z", "VisitTypeName": "Physical"}]}
    s.record_snapshot(1, "north", action("get_upcoming_visits", visits))
    s.record_snapshot(2, "north", action("get_upcoming_visits", None, ok=False))
    assert s.items("appointment", "north")[0]["gone_at"] is None
    res = s.record_snapshot(3, "north", action("get_upcoming_visits", {"visits": []}))
    assert [(c["change"], c["notify"]) for c in res["changes"]] == [("gone", True)]


def test_imaging_in_the_test_result_list_merges_with_the_imaging_list(tmp_path):
    s = st.Store(tmp_path / "s.db")
    xr = ("RES-X", "XR Chest", "2025-08-05T11:00:00", "Final", "IMAGING", [])
    s.record_snapshot(1, "north", action("get_lab_results", lab_standard(xr)))
    s.record_snapshot(1, "north", action("get_imaging_results", lab_standard(xr)))
    kinds = [r["kind"] for r in s.items(None, "north")]
    assert kinds == ["imaging_result"]
    assert s.db.execute("SELECT count(*) FROM lab_values").fetchone()[0] == 0


def test_engine_unloaded_visits_become_quiet_bill_items():
    std = {"totalDue": 0, "accounts": [{"visits": [], "statements": [], "unloadedVisits": [
        {"StartDateDisplay": "Feb 2, 2026", "BillingSystemDisplay": "Hospital Services", "reason": "returned_empty"},
        {"StartDateDisplay": "Sep 24, 2025", "BillingSystemDisplay": "Hospital Services", "reason": "not_loaded"},
    ]}]}
    items = {i.key: i for i in st.ex_billing(std) if i.key.startswith("unavailable|")}
    assert set(items) == {"unavailable|2026-02-02|1", "unavailable|2025-09-24|1"}
    assert "not available from MyChart" in items["unavailable|2026-02-02|1"].summary
    assert "did not load this sync" in items["unavailable|2025-09-24|1"].summary
    assert not any(i.notify or i.notify_on_change for i in items.values())


def test_the_engine_update_keeps_old_unavailable_items_unchanged():
    # Snapshots before openrecord#559 carry the old bridge's top-level field.
    legacy = next(st.ex_unavailable_bills({"unavailableVisits": [{"startDate": "2026-02-02"}]}))
    engine = next(st.ex_unavailable_bills({"accounts": [{"unloadedVisits": [
        {"StartDateDisplay": "Feb 2, 2026", "reason": "returned_empty"}]}]}))
    assert (legacy.key, legacy.fingerprint) == (engine.key, engine.fingerprint)


def test_messages_from_the_patient_do_not_notify():
    std = {"conversations": [{"hthId": "T1", "subject": "Refill", "messages": [
        {"wmgId": "M1", "deliveryInstantISO": "2026-01-01T00:00:00Z", "senderName": "Me", "isFromPatient": True},
        {"wmgId": "M2", "deliveryInstantISO": "2026-01-02T00:00:00Z", "senderName": "Dr. A", "isFromPatient": False},
    ]}]}
    items = {i.key: i for i in st.ex_messages(std)}
    assert items["M1"].notify is False
    assert items["M2"].notify is True


def test_lab_values_get_iso_collection_times_and_abnormal_flags(tmp_path):
    s = st.Store(tmp_path / "s.db")
    s.record_snapshot(1, "north", action("get_lab_results", lab_standard(
        ("R1", "Lipid", "2026-01-10T10:30:00", "Final", "LAB", [("LDL", "LDL", 150), ("HDL", "HDL", 50)]))))
    rows = {r["component"]: r for r in s.lab_trend("")}
    assert rows["LDL"]["collected"] == "2026-01-10T09:00"
    assert rows["LDL"]["abnormal"] == 1
    assert rows["HDL"]["abnormal"] == 0


def test_out_of_range_comes_from_the_reference_range_because_mychart_sends_no_verdict():
    def comp(value, flag="Unknown", **ref):
        return {"componentResultInfo": {"numericValue": value, "abnormalFlagCategoryValue": flag,
                                        "referenceRange": ref}}
    assert st.component_out_of_range(comp(150, low=0, high=100)) is True
    assert st.component_out_of_range(comp(100, low=0, high=100)) is False
    assert st.component_out_of_range(comp(100, low=0, high=100, upperBoundExclusive=True)) is True
    assert st.component_out_of_range(comp(50, flag="High", low=0, high=100)) is True
    assert st.component_out_of_range(comp(None, low=0, high=100)) is None


def test_strip_token_fetches_keeps_payload_requests():
    env = {"requests": [{"purpose": "token", "body": "<html>"}, {"path": "/api", "body": {"a": 1}}]}
    assert st.strip_token_fetches(env) == {"requests": [{"path": "/api", "body": {"a": 1}}]}


def test_parse_display_time_and_local_time():
    assert st.parse_display_time("Jan 10, 2026 9:00 AM, Jan 11, 2026 8:00 AM") == "2026-01-10T09:00"
    assert st.parse_display_time("Mar 3, 2025") == "2025-03-03"
    assert st.parse_display_time("") == ""
    assert st.local_time("2026-04-15T10:30:00") == "2026-04-15 10:30"


# ── digest ──────────────────────────────────────────────────────────────────


def test_digest_banner_carries_counts_only(tmp_path):
    s = st.Store(tmp_path / "s.db")
    s._change(1, "north", "lab_result", "k1", "new", "2026-10-19T08:00", "Lab result: sensitive test (Final)", notify=True)
    s._change(1, "north", "lab_result", "k2", "new", "2026-10-19T08:00", "Lab result: CMP (Final)", notify=True)
    s._change(1, "south", "message", "m1", "new", "2026-10-19T08:00", "Message from Dr. B: Results", notify=True)
    rows = s.changes_since(notify_only=True)
    banner, context = cli.digest_lines(rows, {"north": "North Clinic", "south": "South Hospital"})
    assert banner == "New in MyChart. North Clinic: 2 lab results. South Hospital: 1 message."
    assert "sensitive test" not in banner and "sensitive test" in context


# ── accounts, secrets, write guards ─────────────────────────────────────────


def test_account_names_and_hosts_are_normalized():
    acct = core.add_account("north", "https://mychart.example.org/MyChart/", label="Example")
    assert acct.host == "mychart.example.org"
    with pytest.raises(core.MyChartError):
        core.add_account("Bad Name", "x.org")
    with pytest.raises(core.MyChartError):
        core.add_account("north", "y.org")


def test_auth_prefers_the_passkey_over_a_session(isolated):
    acct = core.add_account("north", "mychart.example.org", username="patient")
    isolated["north:session"] = "S"
    assert core.auth_for(acct) == {"session": "S"}
    isolated["north:passkey"] = "P"
    isolated["north:password"] = "pw"
    assert core.auth_for(acct) == {"passkey": "P", "user": "patient", "pass": "pw"}


def test_long_keychain_values_are_split_under_the_security_line_limit(monkeypatch):
    # `security -i` cuts a command line at 4,096 bytes; a real MyChart session
    # is about 4,000 base64 characters, so long values go in as parts.
    raw: dict[str, str] = {}
    monkeypatch.setattr(core, "_raw_get", lambda key: raw.get(key))
    monkeypatch.setattr(core, "_raw_delete", lambda key: raw.pop(key, None) is not None)

    def raw_set(key, value):
        assert len(value) < 4000, "a line would pass the security -i limit"
        raw[key] = value
        return 0

    monkeypatch.setattr(core, "_raw_set", raw_set)
    monkeypatch.setattr(core, "keychain_get", REAL_KEYCHAIN_GET)
    monkeypatch.setattr(core, "keychain_set", REAL_KEYCHAIN_SET)
    long_value = "x" * 9000
    core.keychain_set("north:session", long_value)
    assert raw["north:session"].startswith(core.CHUNK_MARK)
    assert core.keychain_get("north:session") == long_value
    core.keychain_set("north:session", "short")
    assert core.keychain_get("north:session") == "short"
    assert not [k for k in raw if k.startswith("north:session#")]


def test_unattended_forces_read_only_and_no_prompts(monkeypatch, isolated):
    acct = core.add_account("north", "mychart.example.org")
    isolated["north:passkey"] = "P"
    seen = {}

    def fake_bridge(request, **_):
        seen.update(request)
        return core.BridgeResult(rc=0, events=[])

    monkeypatch.setattr(core, "call_bridge", fake_bridge)
    monkeypatch.setenv("MIST_UNATTENDED", "1")
    core.run_actions(acct, [{"id": "send_message"}], allow_write=True, interactive=True)
    assert seen["allow_write"] is False and seen["interactive"] is False


def test_secret_saver_persists_passkey_events_at_once(isolated):
    acct = core.add_account("north", "mychart.example.org")
    hook = core.make_secret_saver(acct)
    hook({"event": "passkey", "credential": '{"signCount": 7}'})
    assert isolated["north:passkey"] == '{"signCount": 7}'
    hook({"event": "session", "session": "cookies"})
    assert isolated["north:session"] == "cookies"


# ── the bridge, against a stub engine ───────────────────────────────────────

STUB_ENGINE = r"""
console.log('engine noise that must not reach stdout');
const SERVER_COUNT = Number(process.env.STUB_SERVER_COUNT || 0);
export function serializeCredential(c) { return JSON.stringify(c); }
export function deserializeCredential(s) { return JSON.parse(s); }
const caps = {
  get_allergies: { id: 'get_allergies', kind: 'read', params: [],
    processor: { standard: (env) => ({ n: env.requests.length }), concise: (s) => s },
    run: async () => ({ requests: [{ path: '/a', status: 200, body: {} }] }) },
  send_message: { id: 'send_message', kind: 'write', params: [] },
  get_broken: { id: 'get_broken', kind: 'read', params: [],
    processor: { standard: () => { const e = new Error('cannot process'); e.name = 'ProcessorError'; throw e; },
                 concise: (s) => s },
    run: async () => ({ requests: [{ path: '/x', status: 200, body: {} }] }) },
  get_big: { id: 'get_big', kind: 'read', params: [],
    processor: { standard: (env) => ({ size: env.requests[0].body.length }), concise: (s) => s },
    run: async () => ({ requests: [{ path: '/big', status: 200, body: 'x'.repeat(3000000) }] }) },
};
export const CAPABILITIES = Object.values(caps);
export function getCapability(id) { return caps[id]; }
class Client {
  constructor() { this.request = {}; }
  async assertProxyReadContext() {}
  async runCapability(id, args) { return { ran: id, args }; }
  async serialize() { return '{"session":1}'; }
  close() {}
}
export const MyChartClient = {
  async connectWithPasskey({ credential }) {
    credential.signCount += 1;
    return credential.signCount > SERVER_COUNT ? { state: 'connected', client: new Client() } : { state: 'invalid_login' };
  },
  async connect() { return { state: 'connected', client: new Client() }; },
  async fromSerialized() { return null; },
  async totpCode() { return '000000'; },
  async runPublicCapability(id) { return { id }; },
};
"""


@pytest.fixture
def stub_engine(tmp_path, monkeypatch):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    path = tmp_path / "stub-engine.mjs"
    path.write_text(STUB_ENGINE)
    monkeypatch.setenv("MYCHART_ENGINE", str(path))
    return path


def test_bridge_recovers_counter_drift_and_saves_the_accepted_count(stub_engine, monkeypatch, isolated):
    monkeypatch.setenv("STUB_SERVER_COUNT", "5")
    acct = core.add_account("north", "mychart.example.org")
    isolated["north:passkey"] = json.dumps({"signCount": 2})
    result = core.run_actions(acct, [{"id": "get_allergies", "envelope": True}])
    assert (result.login or {}).get("ok") is True
    assert json.loads(isolated["north:passkey"])["signCount"] == 6
    act = result.actions[0]
    assert act["ok"] and act["standard"] == {"n": 1} and act["envelope"]["requests"][0]["path"] == "/a"
    assert not result.of("fatal")


def test_bridge_flushes_every_event_after_a_large_payload(stub_engine, isolated):
    # Regression: process.exit() right after a big write dropped the last
    # events on the first real account (2026-10-19).
    acct = core.add_account("north", "mychart.example.org")
    isolated["north:passkey"] = json.dumps({"signCount": 0})
    result = core.run_actions(acct, [{"id": "get_big", "envelope": True}, {"id": "get_allergies", "envelope": True}])
    assert [a["id"] for a in result.actions] == ["get_big", "get_allergies"]
    assert result.actions[0]["standard"] == {"size": 3000000}
    assert result.of("done") and result.of("session")


def test_a_processor_error_reaches_the_caller_unchanged(stub_engine, isolated):
    acct = core.add_account("north", "mychart.example.org")
    isolated["north:passkey"] = json.dumps({"signCount": 0})
    action_result = core.run_actions(acct, [{"id": "get_broken", "envelope": True}]).actions[0]
    assert action_result["ok"] is False
    assert action_result["error"]["name"] == "ProcessorError"


def test_bridge_refuses_writes_unless_allowed(stub_engine, isolated):
    acct = core.add_account("north", "mychart.example.org")
    isolated["north:passkey"] = json.dumps({"signCount": 0})
    refused = core.run_actions(acct, [{"id": "send_message"}])
    assert refused.actions[0]["error"]["name"] == "WriteRefused"
    allowed = core.run_actions(acct, [{"id": "send_message"}], allow_write=True)
    assert allowed.actions[0]["ok"] is True


# ── FHIR ────────────────────────────────────────────────────────────────────


def test_pkce_challenge_is_s256_of_the_verifier():
    verifier, challenge = fhir.pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


def test_follow_without_browser_reads_the_code_from_the_redirect():
    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/callback?code=abc&state=xyz")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.handle_request, daemon=True).start()
    params = fhir.follow_without_browser(f"http://127.0.0.1:{server.server_port}/authorize",
                                         "http://127.0.0.1:9/callback")
    server.server_close()
    assert params == {"code": "abc", "state": "xyz"}


def test_login_refuses_a_state_mismatch(monkeypatch):
    acct = core.add_account("north", "mychart.example.org", fhir_base="https://fhir.example.org/R4")
    monkeypatch.setattr(fhir, "smart_config", lambda base: {"authorization_endpoint": "https://a", "token_endpoint": "https://t"})
    monkeypatch.setattr(fhir, "follow_without_browser", lambda url, redirect: {"code": "c", "state": "forged"})
    with pytest.raises(fhir.FhirError, match="state"):
        fhir.login(acct, {"name": "epic", "client_id": "id"}, follow=True)


def test_https_callback_listener_serves_tls_and_reads_the_code(tmp_path):
    import socket
    import ssl
    import time
    import urllib.request
    if not (shutil.which("openssl") or Path("/opt/homebrew/bin/openssl").exists()):
        pytest.skip("openssl is not installed")
    fhir.cmd_tls(type("A", (), {"force": False})())
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    found = {}
    worker = threading.Thread(
        target=lambda: found.update(fhir.wait_for_callback(f"https://localhost:{port}/callback", 10)), daemon=True)
    worker.start()
    insecure = ssl.create_default_context()
    insecure.check_hostname = False
    insecure.verify_mode = ssl.CERT_NONE
    for _ in range(50):
        try:
            urllib.request.urlopen(f"https://127.0.0.1:{port}/callback?code=abc&state=xyz", context=insecure,
                                   timeout=5).read()
            break
        except OSError:
            time.sleep(0.1)
    worker.join(12)
    assert found == {"code": "abc", "state": "xyz"}


def test_an_account_secret_wins_over_the_app_secret(isolated):
    acct = core.add_account("north", "mychart.example.org")
    fhir.core.write_json_atomic(fhir.apps_path(), {"epic": {"client_id": "id", "redirect_uri": "x", "scope": "s"}})
    isolated["app-epic:secret"] = "app-wide"
    assert fhir.get_app("epic", acct)["secret"] == "app-wide"
    isolated["north:fhirsecret"] = "per-system"
    assert fhir.get_app("epic", acct)["secret"] == "per-system"


def test_consent_warning_fires_two_weeks_before_the_end():
    import time
    assert fhir.consent_warning({"consent_until": None}) is None
    assert fhir.consent_warning({"consent_until": time.time() + 30 * 86400}) is None
    assert "ends in" in fhir.consent_warning({"consent_until": time.time() + 5 * 86400})
    assert "ended" in fhir.consent_warning({"consent_until": time.time() - 1})


# ── EHI ─────────────────────────────────────────────────────────────────────


def test_ehi_import_refuses_path_traversal(tmp_path):
    core.add_account("north", "mychart.example.org")
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../escape.tsv", "A\tB\n1\t2\n")
    with pytest.raises(core.MyChartError, match="outside"):
        ehi.import_export(bad, "north", "t1")


def test_ehi_import_loads_tsv_tables_and_verify_compares(tmp_path):
    core.add_account("north", "mychart.example.org")
    good = tmp_path / "export.zip"
    with zipfile.ZipFile(good, "w") as zf:
        zf.writestr("tables/ORDER_RESULTS.tsv", "ORDER_PROC_ID\tCOMPONENT_ID\tORD_VALUE\n1\t10\t92\n1\t11\t150\n")
        zf.writestr("tables/PAT_ENC.tsv", "PAT_ENC_CSN_ID\n100\n101\n102\n")
        zf.writestr("docs/note.rtf", "{\\rtf1}")
    manifest = ehi.import_export(good, "north", "t1")
    assert manifest["tables"] == 2 and manifest["rows"] == 5 and manifest["other_files"] == 1
    db = sqlite3.connect(manifest["db"])
    assert db.execute("SELECT ORD_VALUE FROM ORDER_RESULTS WHERE COMPONENT_ID='11'").fetchone()[0] == "150"
    s = st.Store(core.data_dir() / "mychart.db")
    s.record_snapshot(1, "north", action("get_lab_results", lab_standard(
        ("R1", "CMP", "2026-01-10T10:30:00", "Final", "LAB", [("GLU", "Glucose", 92)]))))
    s.commit()
    checks = {c["check"]: c for c in ehi.verify("north")}
    assert checks["lab component results"]["ehi"] == 2
    assert checks["portal lab values present in the export (random 25)"] == {
        "check": "portal lab values present in the export (random 25)", "matched": 1, "sampled": 1}
    assert checks["encounters"]["ehi"] == 3


def test_json_flag_works_before_or_after_the_subcommand():
    assert cli.hoist_global_flags(["new", "--days", "1", "--json"]) == ["--json", "new", "--days", "1"]
    assert cli.hoist_global_flags(["--json", "show", "labs"]) == ["--json", "show", "labs"]
    assert cli.hoist_global_flags(["search", "x"]) == ["search", "x"]
    assert cli.hoist_global_flags(["search", "--", "--json"]) == ["search", "--", "--json"]
    assert cli.build_parser().parse_args(cli.hoist_global_flags(["show", "labs", "--json"])).json
