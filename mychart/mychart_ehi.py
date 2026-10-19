"""mychart EHI lane: import a Cures Act EHI export and check the sync against it.

An Epic "Electronic Health Information export" (ONC criterion b(10)) is the
most complete record a patient can get: Epic's tables as tab-separated files,
plus documents. Epic documents each table at https://open.epic.com/EHITables.
This module loads one export into its own SQLite file, one table per TSV,
every column as text, and compares it with what `mychart sync` stored.

    mychart ehi import ~/Downloads/export.zip --account clinic
    mychart ehi list
    mychart ehi tables clinic [--grep ORDER]
    mychart ehi verify clinic

INVARIANTS:
- The export is read-only input. Import never edits or deletes the source.
- Each import is a new database file; nothing is merged into the sync store.
- Extraction refuses any archive member whose path leaves the target folder.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import mychart_core as core
import mychart_store as st

csv.field_size_limit(sys.maxsize)


def ehi_root() -> Path:
    path = core.data_dir() / "ehi"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def safe_table(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_").upper()
    return cleaned or "TABLE"


def safe_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            dest = (target / member.filename).resolve()
            if root not in dest.parents and dest != root:
                raise core.MyChartError(f"refusing archive member outside the target: {member.filename}")
            if member.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)


def load_tsv(db: sqlite3.Connection, table: str, path: Path) -> tuple[int, list[str]]:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
        try:
            header = next(reader)
        except StopIteration:
            return 0, []
        columns = []
        seen: set[str] = set()
        for col in header:
            name = safe_table(col) or "COL"
            while name in seen:
                name += "_"
            seen.add(name)
            columns.append(name)
        db.execute(f'DROP TABLE IF EXISTS "{table}"')
        column_sql = ", ".join('"' + c + '" TEXT' for c in columns)
        db.execute(f'CREATE TABLE "{table}" ({column_sql})')
        placeholders = ", ".join("?" for _ in columns)
        rows = 0
        batch: list[list[str]] = []
        for record in reader:
            if len(record) < len(columns):
                record = record + [""] * (len(columns) - len(record))
            batch.append(record[: len(columns)])
            if len(batch) >= 5000:
                db.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', batch)
                rows += len(batch)
                batch.clear()
        if batch:
            db.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', batch)
            rows += len(batch)
    for col in columns:
        if col in ("PAT_ID", "PAT_ENC_CSN_ID", "ORDER_PROC_ID", "ORDER_MED_ID", "COMPONENT_ID"):
            db.execute(f'CREATE INDEX IF NOT EXISTS "{table}_{col}" ON "{table}"("{col}")')
    return rows, columns


def import_export(source: Path, account: str, label: str | None = None) -> dict[str, Any]:
    core.get_account(account)
    label = label or time.strftime("%Y-%m-%d")
    folder = ehi_root() / account / label
    if source.is_file() and zipfile.is_zipfile(source):
        safe_extract(source, folder / "files")
        files_root = folder / "files"
    elif source.is_dir():
        files_root = source
    else:
        raise core.MyChartError(f"{source} is neither a zip file nor a folder")
    db_path = ehi_root() / f"{account}-{label}.db"
    db = sqlite3.connect(str(db_path))
    db.execute("CREATE TABLE IF NOT EXISTS _manifest (tbl TEXT PRIMARY KEY, file TEXT, rows INTEGER, columns TEXT)")
    tables = 0
    total = 0
    other: list[str] = []
    for path in sorted(files_root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".tsv", ".txt") and path.stat().st_size > 0:
            table = safe_table(path.stem)
            rows, columns = load_tsv(db, table, path)
            if columns:
                db.execute("INSERT OR REPLACE INTO _manifest VALUES (?, ?, ?, ?)",
                           (table, str(path.relative_to(files_root)), rows, json.dumps(columns)))
                tables += 1
                total += rows
                continue
        other.append(str(path.relative_to(files_root)))
    db.commit()
    db.close()
    db_path.chmod(0o600)
    manifest = {"account": account, "label": label, "db": str(db_path), "tables": tables, "rows": total,
                "other_files": len(other), "source": str(source), "imported_at": st.now_iso()}
    core.write_json_atomic(folder / "import.json", {**manifest, "other_files_list": other[:2000]})
    return manifest


def exports(account: str | None = None) -> list[Path]:
    pattern = f"{account}-*.db" if account else "*.db"
    return sorted(ehi_root().glob(pattern))


def latest_db(account: str) -> Path:
    found = exports(account)
    if not found:
        raise core.MyChartError(f"no EHI export imported for {account}. Run: mychart ehi import <file> --account {account}")
    return found[-1]


def has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def columns_of(db: sqlite3.Connection, name: str) -> set[str]:
    return {row[1] for row in db.execute(f'PRAGMA table_info("{name}")')}


def verify(account: str) -> list[dict[str, Any]]:
    """Compare the export with the sync store. Each check names its tables, so
    a mismatch can be traced by hand in both places."""
    ehi = sqlite3.connect(f"file:{latest_db(account)}?mode=ro", uri=True)
    s = st.Store(core.data_dir() / "mychart.db")
    checks: list[dict[str, Any]] = []

    store_labs = s.db.execute("SELECT count(*) FROM lab_values WHERE account=?", (account,)).fetchone()[0]
    if has_table(ehi, "ORDER_RESULTS"):
        ehi_labs = ehi.execute("SELECT count(*) FROM ORDER_RESULTS").fetchone()[0]
        checks.append({"check": "lab component results", "ehi": ehi_labs, "ehi_table": "ORDER_RESULTS",
                       "portal": store_labs, "note": "The portal shows released results only, so the "
                                                     "export count is expected to be higher."})
        cols = columns_of(ehi, "ORDER_RESULTS")
        value_col = "ORD_VALUE" if "ORD_VALUE" in cols else None
        if value_col:
            sample = s.db.execute(
                "SELECT component, value, substr(coalesce(nullif(collected, ''), resulted), 1, 10) AS day "
                "FROM lab_values WHERE account=? AND value IS NOT NULL ORDER BY random() LIMIT 25",
                (account,),
            ).fetchall()
            found = sum(
                1 for r in sample
                if ehi.execute(f'SELECT 1 FROM ORDER_RESULTS WHERE "{value_col}" = ? LIMIT 1',
                               (str(r["value"]),)).fetchone()
            )
            checks.append({"check": "portal lab values present in the export (random 25)",
                           "matched": found, "sampled": len(sample)})
    else:
        checks.append({"check": "lab component results", "ehi": None, "portal": store_labs,
                       "note": "no ORDER_RESULTS table in this export; run: mychart ehi tables " + account})

    store_visits = s.db.execute("SELECT count(*) FROM items WHERE account=? AND kind='past_visit'",
                                (account,)).fetchone()[0]
    if has_table(ehi, "PAT_ENC"):
        checks.append({"check": "encounters", "ehi": ehi.execute("SELECT count(*) FROM PAT_ENC").fetchone()[0],
                       "ehi_table": "PAT_ENC", "portal": store_visits,
                       "note": "PAT_ENC holds every contact (calls, orders-only, messages), the portal "
                               "lists visits only."})
    store_meds = s.db.execute("SELECT count(*) FROM items WHERE account=? AND kind='medication'",
                              (account,)).fetchone()[0]
    if has_table(ehi, "ORDER_MED"):
        checks.append({"check": "medication orders", "ehi": ehi.execute("SELECT count(*) FROM ORDER_MED").fetchone()[0],
                       "ehi_table": "ORDER_MED", "portal": store_meds,
                       "note": "The portal lists current medications; ORDER_MED holds every order."})
    ehi.close()
    s.close()
    return checks


# ── commands ────────────────────────────────────────────────────────────────


def cmd_import(args: argparse.Namespace) -> int:
    manifest = import_export(Path(args.source).expanduser(), args.account, args.label)
    print(f"Imported {manifest['tables']} tables ({manifest['rows']} rows) into {manifest['db']}. "
          f"{manifest['other_files']} other files kept as-is.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    for path in exports(args.account):
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables, rows = db.execute("SELECT count(*), coalesce(sum(rows), 0) FROM _manifest").fetchone()
        db.close()
        print(f"{path.name}: {tables} tables, {rows} rows")
    return 0


def cmd_tables(args: argparse.Namespace) -> int:
    db = sqlite3.connect(f"file:{latest_db(args.account)}?mode=ro", uri=True)
    rows = db.execute("SELECT tbl, rows FROM _manifest ORDER BY rows DESC").fetchall()
    for table, count in rows:
        if args.grep and args.grep.upper() not in table:
            continue
        print(f"{count:>9}  {table}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    checks = verify(args.account)
    if args.json:
        print(json.dumps(checks, indent=2))
        return 0
    for c in checks:
        detail = {k: v for k, v in c.items() if k not in ("check", "note")}
        print(f"{c['check']}: {json.dumps(detail)}")
        if c.get("note"):
            print(f"    {c['note']}")
    return 0


def register(sub: Any) -> None:
    p = sub.add_parser("ehi", help="import and check a Cures Act EHI export")
    esub = p.add_subparsers(dest="ehi_command", required=True)
    a = esub.add_parser("import", help="load an export (zip or folder) into its own database")
    a.add_argument("source")
    a.add_argument("--account", required=True)
    a.add_argument("--label", help="name for this export (default: today's date)")
    a.set_defaults(func=cmd_import)
    a = esub.add_parser("list", help="imported exports")
    a.add_argument("--account")
    a.set_defaults(func=cmd_list)
    a = esub.add_parser("tables", help="tables in the newest export for an account")
    a.add_argument("account")
    a.add_argument("--grep")
    a.set_defaults(func=cmd_tables)
    a = esub.add_parser("verify", help="compare the export with the sync store")
    a.add_argument("account")
    a.set_defaults(func=cmd_verify)
