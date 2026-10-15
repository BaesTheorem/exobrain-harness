"""Load the transcript archive into a DuckDB database and compute window metrics.

build() parses each archived transcript that changed since the last build
(trace_parse.py) and replaces that file's rows. baseline() turns one time
window into a dict of metrics. README.md documents the tables and every metric.

INVARIANTS
- The archive is the only input. The database can be deleted and rebuilt from
  it at any time (build --full), so it is a cache and holds no original data.
- Rows are keyed by file_id. A changed file has all of its rows replaced in
  one transaction, so a crash never leaves a file half loaded.
- Metrics deduplicate across files (a resumed session can repeat lines):
  api calls by (message_id, request_id), tool calls by tool_use_id, prompts
  by uuid. Change METRICS_VERSION when a metric definition changes.
"""

from __future__ import annotations

import io
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
from compression import zstd

import trace_archive
from trace_parse import parse_lines

METRICS_VERSION = 1
HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "data" / "traces.duckdb"
BATCH = 100

SCHEMA: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("file_id", "VARCHAR"), ("session_id", "VARCHAR"), ("project", "VARCHAR"), ("agent_id", "VARCHAR"),
        ("is_subagent", "BOOLEAN"), ("kind", "VARCHAR"), ("cwd", "VARCHAR"), ("entrypoint", "VARCHAR"),
        ("version", "VARCHAR"), ("git_branch", "VARCHAR"), ("first_ts", "TIMESTAMPTZ"), ("last_ts", "TIMESTAMPTZ"),
        ("title", "VARCHAR"), ("permission_mode", "VARCHAR"), ("models", "VARCHAR[]"), ("cost_usd", "DOUBLE"),
        ("api_duration_ms", "DOUBLE"), ("tool_duration_ms", "DOUBLE"), ("lines_added", "BIGINT"),
        ("lines_removed", "BIGINT"), ("lines", "BIGINT"), ("bad_lines", "BIGINT"), ("n_queued", "INTEGER"),
        ("n_api_calls", "INTEGER"), ("n_tool_calls", "INTEGER"), ("n_tool_errors", "INTEGER"),
        ("n_human_prompts", "INTEGER"), ("n_interrupts", "INTEGER"), ("n_status_polls", "INTEGER"),
        ("n_approvals", "INTEGER"), ("n_resumes", "INTEGER"), ("n_task_notifications", "INTEGER"),
        ("n_slash_commands", "INTEGER"), ("n_compactions", "INTEGER"), ("n_api_errors", "INTEGER"),
        ("first_context_tokens", "BIGINT"), ("input_tokens", "BIGINT"), ("cache_write_tokens", "BIGINT"),
        ("cache_read_tokens", "BIGINT"), ("output_tokens", "BIGINT"), ("first_prompt", "VARCHAR"),
    ],
    "api_calls": [
        ("file_id", "VARCHAR"), ("session_id", "VARCHAR"), ("message_id", "VARCHAR"), ("request_id", "VARCHAR"),
        ("ts", "TIMESTAMPTZ"), ("model", "VARCHAR"), ("requested_model", "VARCHAR"), ("effort", "VARCHAR"),
        ("skill", "VARCHAR"), ("stop_reason", "VARCHAR"), ("is_api_error", "BOOLEAN"),
        ("input_tokens", "BIGINT"), ("cache_write_tokens", "BIGINT"), ("cache_read_tokens", "BIGINT"),
        ("output_tokens", "BIGINT"), ("cache_write_5m", "BIGINT"), ("cache_write_1h", "BIGINT"),
    ],
    "tool_calls": [
        ("file_id", "VARCHAR"), ("session_id", "VARCHAR"), ("tool_use_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"),
        ("tool", "VARCHAR"), ("skill", "VARCHAR"), ("model", "VARCHAR"), ("input", "VARCHAR"),
        ("has_result", "BOOLEAN"), ("is_error", "BOOLEAN"), ("result_chars", "BIGINT"), ("latency_s", "DOUBLE"),
    ],
    "prompts": [
        ("file_id", "VARCHAR"), ("session_id", "VARCHAR"), ("uuid", "VARCHAR"), ("ts", "TIMESTAMPTZ"),
        ("category", "VARCHAR"), ("intent", "VARCHAR"), ("chars", "BIGINT"), ("has_image", "BOOLEAN"),
        ("text", "VARCHAR"),
    ],
    "events": [
        ("file_id", "VARCHAR"), ("session_id", "VARCHAR"), ("ts", "TIMESTAMPTZ"), ("subtype", "VARCHAR"),
        ("level", "VARCHAR"), ("duration_ms", "DOUBLE"), ("pre_tokens", "BIGINT"), ("post_tokens", "BIGINT"),
        ("compact_trigger", "VARCHAR"), ("retry_attempt", "INTEGER"), ("detail", "VARCHAR"),
    ],
}


def connect(db: Path = DEFAULT_DB, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    if read_only:
        return duckdb.connect(str(db), read_only=True)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    for table, cols in SCHEMA.items():
        con.execute(f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(f'{n} {t}' for n, t in cols)})")
    con.execute("CREATE TABLE IF NOT EXISTS files (file_id VARCHAR, archive_mtime_ns BIGINT, ingested_at TIMESTAMPTZ)")
    return con


def _changed(con: duckdb.DuckDBPyConnection, archive: Path, full: bool) -> list[tuple[str, Path, int]]:
    known = {} if full else dict(con.execute("SELECT file_id, archive_mtime_ns FROM files").fetchall())
    out = []
    for path in sorted(archive.rglob("*.jsonl.zst")):
        file_id = path.relative_to(archive).as_posix().removesuffix(".zst")
        mtime = path.stat().st_mtime_ns
        if known.get(file_id) != mtime:
            out.append((file_id, path, mtime))
    return out


def _load_batch(con: duckdb.DuckDBPyConnection, batch: list[tuple[str, Path, int]], tmp: Path) -> None:
    rows: dict[str, list[dict]] = {t: [] for t in SCHEMA}
    for file_id, path, _ in batch:
        with zstd.ZstdFile(path) as raw, io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as text:
            parsed = parse_lines(text, file_id)
        for table in SCHEMA:
            rows[table].extend(parsed[table])
    ids = [b[0] for b in batch]
    con.execute("BEGIN")
    try:
        for table, cols in SCHEMA.items():
            con.execute(f"DELETE FROM {table} WHERE file_id IN (SELECT unnest(?::VARCHAR[]))", [ids])
            if not rows[table]:
                continue
            spool = tmp / f"{table}.ndjson"
            with open(spool, "w") as fh:
                for row in rows[table]:
                    fh.write(json.dumps({n: row.get(n) for n, _ in cols}, ensure_ascii=False) + "\n")
            spec = "{" + ", ".join(f"'{n}': '{t}'" for n, t in cols) + "}"
            con.execute(f"INSERT INTO {table} SELECT * FROM read_json(?, format='newline_delimited', "
                        f"columns={spec}, maximum_object_size=268435456)", [str(spool)])
        con.execute("DELETE FROM files WHERE file_id IN (SELECT unnest(?::VARCHAR[]))", [ids])
        now = datetime.now(UTC)
        con.executemany("INSERT INTO files VALUES (?, ?, ?)", [(f, m, now) for f, _, m in batch])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def build(db: Path = DEFAULT_DB, archive: Path = trace_archive.DEFAULT_DEST, full: bool = False,
          show_progress: bool = False) -> dict:
    started = datetime.now(UTC)
    con = connect(db)
    todo = _changed(con, archive, full)
    if show_progress and todo:
        trace_archive.progress("start", label="Loading transcripts into the trace table", total=len(todo))
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(0, len(todo), BATCH):
            if show_progress:
                trace_archive.progress("set", current=i)
            _load_batch(con, todo[i:i + BATCH], Path(tmp))
    if show_progress and todo:
        trace_archive.progress("done")
    counts = {t: (con.execute(f"SELECT count(*) FROM {t}").fetchone() or [0])[0] for t in [*SCHEMA, "files"]}
    con.close()
    return {"ts": started.isoformat(timespec="seconds"), "files_loaded": len(todo), "rows": counts,
            "db_bytes": db.stat().st_size, "seconds": round((datetime.now(UTC) - started).total_seconds(), 1)}


def _one(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> dict:
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    row = cur.fetchone() or [None] * len(names)
    return dict(zip(names, row, strict=True))


def _all(con: duckdb.DuckDBPyConnection, sql: str, params: list) -> list[dict]:
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def baseline(con: duckdb.DuckDBPyConnection, start: datetime, end: datetime) -> dict:
    """Metrics for sessions that started, and activity that happened, in [start, end)."""
    w = [start, end]
    m: dict = {"window": {"start": start.isoformat(), "end": end.isoformat()}, "metrics_version": METRICS_VERSION}
    m["sessions"] = _one(con, """
        SELECT count(*) FILTER (WHERE NOT is_subagent) AS main,
               count(*) FILTER (WHERE kind = 'multi_turn') AS multi_turn,
               count(*) FILTER (WHERE kind = 'single_turn') AS single_turn,
               count(*) FILTER (WHERE is_subagent) AS subagent_files,
               round(quantile_cont(first_context_tokens, 0.1) FILTER (WHERE NOT is_subagent)) AS first_context_p10,
               round(median(first_context_tokens) FILTER (WHERE NOT is_subagent)) AS first_context_median,
               round(quantile_cont(first_context_tokens, 0.9) FILTER (WHERE NOT is_subagent)) AS first_context_p90,
               round(sum(cost_usd) FILTER (WHERE NOT is_subagent), 2) AS cost_usd_main,
               round(sum(cost_usd) FILTER (WHERE is_subagent), 2) AS cost_usd_subagent,
               sum(n_queued) AS queued_prompts
        FROM sessions WHERE first_ts >= ? AND first_ts < ?""", w)
    m["by_entrypoint"] = _all(con, """
        SELECT entrypoint, count(*) AS sessions FROM sessions
        WHERE NOT is_subagent AND first_ts >= ? AND first_ts < ? GROUP BY ALL ORDER BY sessions DESC""", w)
    m["tokens"] = _one(con, """
        WITH a AS (SELECT * FROM api_calls WHERE ts >= ? AND ts < ? AND message_id IS NOT NULL
                   QUALIFY row_number() OVER (PARTITION BY message_id, request_id ORDER BY ts, file_id) = 1)
        SELECT count(*) AS api_calls, sum(input_tokens) AS input, sum(cache_write_tokens) AS cache_write,
               sum(cache_read_tokens) AS cache_read, sum(output_tokens) AS output FROM a""", w)
    m["tokens_by_model"] = _all(con, """
        WITH a AS (SELECT * FROM api_calls WHERE ts >= ? AND ts < ? AND message_id IS NOT NULL
                   QUALIFY row_number() OVER (PARTITION BY message_id, request_id ORDER BY ts, file_id) = 1)
        SELECT model, count(*) AS api_calls, sum(cache_read_tokens) AS cache_read, sum(output_tokens) AS output
        FROM a GROUP BY ALL ORDER BY cache_read DESC""", w)
    m["tools"] = _one(con, """
        WITH t AS (SELECT * FROM tool_calls WHERE ts >= ? AND ts < ?
                   QUALIFY row_number() OVER (PARTITION BY tool_use_id ORDER BY ts, file_id) = 1)
        SELECT count(*) AS calls, count(*) FILTER (WHERE is_error) AS errors,
               round(100.0 * count(*) FILTER (WHERE is_error) / nullif(count(*), 0), 2) AS error_pct FROM t""", w)
    m["tool_errors_by_tool"] = _all(con, """
        WITH t AS (SELECT * FROM tool_calls WHERE ts >= ? AND ts < ?
                   QUALIFY row_number() OVER (PARTITION BY tool_use_id ORDER BY ts, file_id) = 1)
        SELECT tool, count(*) AS calls, count(*) FILTER (WHERE is_error) AS errors FROM t
        GROUP BY ALL ORDER BY errors DESC LIMIT 10""", w)
    m["prompts"] = _one(con, """
        WITH p AS (SELECT * FROM prompts WHERE ts >= ? AND ts < ?
                   QUALIFY row_number() OVER (PARTITION BY coalesce(uuid, file_id || ts::VARCHAR) ORDER BY file_id) = 1)
        SELECT count(*) FILTER (WHERE category = 'human') AS human,
               count(*) FILTER (WHERE intent = 'status_poll') AS status_polls,
               count(*) FILTER (WHERE intent = 'approval') AS approvals,
               count(*) FILTER (WHERE intent = 'resume') AS resumes,
               count(*) FILTER (WHERE category = 'interrupt') AS interrupts,
               count(*) FILTER (WHERE category = 'task_notification') AS task_notifications,
               count(*) FILTER (WHERE category = 'slash_command') AS slash_commands FROM p""", w)
    human = m["prompts"]["human"] or 0
    m["prompts_per_100_human"] = {k: round(100 * (m["prompts"][k] or 0) / human, 2) if human else None
                                  for k in ("status_polls", "approvals", "resumes", "interrupts")}
    m["events"] = _one(con, """
        SELECT count(*) FILTER (WHERE subtype = 'compact_boundary') AS compactions,
               count(*) FILTER (WHERE subtype = 'compact_boundary' AND compact_trigger = 'auto') AS auto_compactions,
               count(*) FILTER (WHERE subtype = 'api_error') AS api_errors,
               count(*) FILTER (WHERE subtype = 'model_refusal_fallback') AS refusal_fallbacks
        FROM events WHERE ts >= ? AND ts < ?""", w)
    m["projects"] = _all(con, """
        SELECT project, count(*) AS sessions FROM sessions
        WHERE NOT is_subagent AND first_ts >= ? AND first_ts < ? GROUP BY ALL ORDER BY sessions DESC LIMIT 8""", w)
    return m


def render(m: dict) -> str:
    """The baseline as a Markdown table (no prompt text, so safe to paste into a note)."""
    s, t, tl, p, e, r = m["sessions"], m["tokens"], m["tools"], m["prompts"], m["events"], m["prompts_per_100_human"]

    def n(x: object) -> str:
        if isinstance(x, float) and x.is_integer():
            x = int(x)
        return f"{x:,}" if isinstance(x, (int, float)) else ("n/a" if x is None else str(x))

    rows = [
        ("Main sessions", f"{n(s['main'])} ({n(s['multi_turn'])} multi-turn, {n(s['single_turn'])} single-turn)"),
        ("Subagent transcripts", n(s["subagent_files"])),
        ("First-turn context, tokens", f"p10 {n(s['first_context_p10'])}, median {n(s['first_context_median'])}, "
                                       f"p90 {n(s['first_context_p90'])}"),
        ("API calls", n(t["api_calls"])),
        ("Cache-read tokens", n(t["cache_read"])),
        ("Cache-write tokens", n(t["cache_write"])),
        ("Output tokens", n(t["output"])),
        ("Tool calls, errors", f"{n(tl['calls'])}, {n(tl['errors'])} ({tl['error_pct']}%)"),
        ("Human prompts", n(p["human"])),
        ("Status polls", f"{n(p['status_polls'])} ({r['status_polls']} per 100 prompts)"),
        ("Bare approvals", f"{n(p['approvals'])} ({r['approvals']} per 100 prompts)"),
        ("Resume prompts", f"{n(p['resumes'])} ({r['resumes']} per 100 prompts)"),
        ("Interrupts", f"{n(p['interrupts'])} ({r['interrupts']} per 100 prompts)"),
        ("Compactions (auto)", f"{n(e['compactions'])} ({n(e['auto_compactions'])})"),
        ("API errors (retries logged)", n(e["api_errors"])),
        ("Claude Code cost-state, USD (main sessions)", n(s["cost_usd_main"])),
    ]
    out = ["| Metric | Value |", "| --- | --- |"] + [f"| {a} | {b} |" for a, b in rows]
    return "\n".join(out)


def window(end: str | None, days: int) -> tuple[datetime, datetime]:
    """[end - days, end) in local time, end at local midnight of the given date (default today)."""
    tz = datetime.now().astimezone().tzinfo
    stop = datetime.fromisoformat(end) if end else datetime.now()
    stop = stop.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
    return stop - timedelta(days=days), stop
