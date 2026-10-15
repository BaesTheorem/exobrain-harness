"""traces/trace_parse.py: transcript lines in, flat rows out, never a crash."""

import json

from conftest import load_script

tp = load_script("traces/trace_parse.py")

MAIN = "-Users-x-proj/11111111-2222-3333-4444-555555555555.jsonl"
SUB = "-Users-x-proj/11111111-2222-3333-4444-555555555555/subagents/agent-abc.jsonl"


def line(**o) -> str:
    return json.dumps(o)


def user(text, ts, **extra) -> str:
    return line(type="user", timestamp=ts, uuid=f"u-{ts}", message={"role": "user", "content": text}, **extra)


def assistant(mid, ts, usage, content=None, model="claude-x") -> str:
    return line(type="assistant", timestamp=ts, requestId="r-" + mid,
                message={"id": mid, "model": model, "usage": usage, "content": content or []})


USAGE = {"input_tokens": 3, "cache_creation_input_tokens": 40_000, "cache_read_input_tokens": 10_000}


def parse(lines, file_id=MAIN):
    return tp.parse_lines(lines, file_id)


def test_split_assistant_message_is_one_call_with_the_final_usage():
    rows = parse([
        user("Fix the build", "2026-10-01T10:00:00Z"),
        assistant("m1", "2026-10-01T10:00:01Z", {**USAGE, "output_tokens": 5}, [{"type": "thinking"}]),
        assistant("m1", "2026-10-01T10:00:02Z", {**USAGE, "output_tokens": 50}, [{"type": "text", "text": "ok"}]),
    ])
    (call,) = rows["api_calls"]
    assert call["output_tokens"] == 50 and call["cache_write_tokens"] == 40_000
    assert rows["sessions"][0]["first_context_tokens"] == 50_003


def test_tool_error_joins_its_use_and_measures_latency():
    use = {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "false"}}
    result = {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "exit 1"}
    rows = parse([
        assistant("m1", "2026-10-01T10:00:00Z", {**USAGE, "output_tokens": 9}, [use]),
        line(type="user", timestamp="2026-10-01T10:00:02.500Z", message={"role": "user", "content": [result]}),
    ])
    (call,) = rows["tool_calls"]
    assert call["tool"] == "Bash" and call["is_error"] and call["latency_s"] == 2.5
    assert rows["sessions"][0]["n_tool_errors"] == 1
    assert rows["prompts"] == []  # a tool result is not a prompt


def test_prompt_categories_and_intents():
    texts = ["Status?", "yes plz", "Yes, but rename the file and drop the second section entirely",
             "[Request interrupted by user]", "<task-notification><task-id>x</task-id>",
             "<command-name>/model</command-name>", "Resume"]
    rows = parse([user(t, f"2026-10-01T10:00:0{i}Z") for i, t in enumerate(texts)]
                 + [user("skill body", "2026-10-01T10:00:09Z", isMeta=True)])
    got = [(p["category"], p["intent"]) for p in rows["prompts"]]
    assert got == [("human", "status_poll"), ("human", "approval"), ("human", None), ("interrupt", None),
                   ("task_notification", None), ("slash_command", None), ("human", "resume"), ("meta", None)]
    s = rows["sessions"][0]
    assert s["n_human_prompts"] == 4 and s["kind"] == "multi_turn" and s["n_interrupts"] == 1


def test_subagent_file_identity_and_prompts():
    rows = parse([user("Search the repo", "2026-10-01T10:00:00Z", isSidechain=True)], SUB)
    s = rows["sessions"][0]
    assert (s["session_id"], s["agent_id"], s["kind"]) == ("11111111-2222-3333-4444-555555555555", "agent-abc",
                                                            "subagent")
    assert rows["prompts"][0]["category"] == "agent_prompt"


def test_bad_lines_are_counted_not_raised_and_events_are_kept():
    rows = parse([
        "{not json", "[1, 2]",
        line(type="system", subtype="compact_boundary", timestamp="2026-10-01T10:00:00Z",
             compactMetadata={"trigger": "auto", "preTokens": 900_000, "postTokens": 30_000}),
        line(type="system", subtype="api_error", timestamp="2026-10-01T10:00:01Z", retryAttempt=2,
             error={"message": "Connection error.", "formatted": "Connection dropped (ECONNRESET)"}),
        line(type="cost-state", totalCostUSD=1.5),
        line(type="cost-state", totalCostUSD=2.25),
    ])
    s = rows["sessions"][0]
    assert s["bad_lines"] == 2 and s["cost_usd"] == 2.25
    assert s["n_compactions"] == 1 and s["n_api_errors"] == 1
    compact, err = rows["events"]
    assert compact["compact_trigger"] == "auto" and compact["pre_tokens"] == 900_000
    assert err["detail"] == "Connection dropped (ECONNRESET)" and err["retry_attempt"] == 2
