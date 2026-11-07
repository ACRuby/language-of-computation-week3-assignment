"""Load a books CSV into books.db following rules.md (the group's agreed
rules), and append one entry per run to ingestion-log.json (read it with
report.html).

There are no command-line parameters: the three file names below are the
only settings, so a run is always reproducible from this file alone. To load
a different file, change CSV_FILENAME, save, and run again:

    py -3.13 ingest.py

Other code can call run(csv_path, db_path, log_path) directly.

No AI and no network: the same file against the same database always gives
the same result. Every row is checked on every run, and books are matched by
goodreads_book_id, so running the same file twice never creates duplicates.

Each row is saved as soon as it is processed. There is no "a failed run saves
nothing" guarantee (rules.md, Resolved conflict): a FAILED run may already
have saved the rows before the failure, and the log says so.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import isbn as isbnlib
from validate import (COLUMNS, IDENTITY_FIELD_CONFLICT, IDENTITY_FIELDS, ISBN_COLLISION, REJECT_CODES,
                      STRUCTURAL_PARSE_ERROR, VOLATILE_FIELDS, Rejection, RowResult, same_value,
                      validate_row)

# --- settings (rules: run-instructions.md, "Parameters") -----------------------
CSV_FILENAME = "books.csv"
DB_FILENAME = "books.db"
LOG_FILENAME = "ingestion-log.json"

HERE = Path(__file__).resolve().parent

SUCCESS, WITH_ISSUES, FAILED = "SUCCESS", "COMPLETED WITH ISSUES", "FAILED"
FAILED_NOTE = ("Status: FAILED - the group did not implement an atomicity guarantee for this pipeline; "
               "rows from before the failure may already be saved.")

LOADED, UPDATED, SKIPPED, REJECTED = "loaded", "updated", "skipped", "rejected"
WARNING_ACTION = {
    LOADED: "loaded; field stored as empty (raw value kept in the warnings table)",
    UPDATED: "updated; field stored as empty (raw value kept in the warnings table)",
    SKIPPED: "skipped (duplicate, no changes); the warning still applies",
}

# erd.md: the agreed two-table schema. Every book column is text.
BOOK_COLUMNS = COLUMNS + ("identity_key", "fallback_key", "source_file", "first_loaded_at", "last_updated_at")
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    {", ".join(f"{c} TEXT" for c in BOOK_COLUMNS)}
);
CREATE UNIQUE INDEX IF NOT EXISTS books_goodreads_book_id ON books(goodreads_book_id);
CREATE INDEX IF NOT EXISTS books_identity_key ON books(identity_key);
CREATE INDEX IF NOT EXISTS books_isbn ON books(isbn);
CREATE INDEX IF NOT EXISTS books_isbn13 ON books(isbn13);
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY,
    book_row_id INTEGER NOT NULL REFERENCES books(id),
    field TEXT, raw_value TEXT, reason TEXT, recorded_at TEXT
);
CREATE INDEX IF NOT EXISTS warnings_book_row_id ON warnings(book_row_id);
"""


class IngestError(Exception):
    """A problem that makes the run FAILED."""


# --- reading the CSV -------------------------------------------------------------
def read_rows(path: Path):
    """Returns the data rows as (row_number, dict-or-None, problem). Row 1 is the header."""
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        raise IngestError(f"file not found: {path}")
    except UnicodeDecodeError as e:
        raise IngestError(f"file could not be read as UTF-8 text: {e}")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    try:
        header = next(reader)
    except (StopIteration, csv.Error):
        raise IngestError("the file has no readable header row")
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        raise IngestError(f"required column(s) missing: {', '.join(missing)}")

    rows, number = [], 1
    while True:
        try:
            fields = next(reader)
        except StopIteration:
            break
        except csv.Error as e:
            number += 1
            rows.append((number, None, f"broken quoting: {e}"))
            continue
        if not fields:
            continue                                   # a completely blank line is not a row
        number += 1
        if len(fields) != len(header):
            rows.append((number, dict(zip(header, fields)),
                         f"wrong number of fields ({len(fields)}, expected {len(header)})"))
        else:
            rows.append((number, dict(zip(header, fields)), None))
    return rows


# --- one run ---------------------------------------------------------------------
def line(source_file, res: RowResult, **extra):
    return {"source_file": source_file, "row_number": res.row_number,
            "goodreads_book_id": res.raw.get("goodreads_book_id"), "title": res.raw.get("title"), **extra}


class Run:
    def __init__(self, conn, source_file, stamp):
        self.conn, self.source_file, self.stamp = conn, source_file, stamp
        self.outcomes = []            # (outcome, had_warning) per row
        self.rejections, self.warnings, self.repairs, self.updates = [], [], [], []
        self.problem_counts = {}

    def count(self, code):
        self.problem_counts[code] = self.problem_counts.get(code, 0) + 1

    def reject(self, res, rejection: Rejection):
        self.count(rejection.reason)
        self.rejections.append(line(self.source_file, res, reason=rejection.reason, detail=rejection.detail,
                                    action="rejected: not loaded; flagged for manual review"))
        self.outcomes.append((REJECTED, False))

    def save_warnings(self, book_row_id, res):
        self.conn.execute("DELETE FROM warnings WHERE book_row_id = ?", (book_row_id,))
        self.conn.executemany(
            "INSERT INTO warnings (book_row_id, field, raw_value, reason, recorded_at) VALUES (?,?,?,?,?)",
            [(book_row_id, w.field, w.raw_value, w.reason, self.stamp) for w in res.warnings])

    def process(self, res: RowResult):
        if res.rejected:
            return self.reject(res, res.rejection)
        rec = res.record
        gid = rec["goodreads_book_id"]
        for fld in ("isbn13", "isbn"):
            if rec[fld] and (other := self.conn.execute(
                    f"SELECT goodreads_book_id, title FROM books WHERE {fld} = ? AND goodreads_book_id != ?",
                    (rec[fld], gid)).fetchone()):
                return self.reject(res, Rejection(ISBN_COLLISION,
                                                  f"{fld} {rec[fld]} already belongs to goodreads_book_id "
                                                  f"{other['goodreads_book_id']} ('{other['title']}')"))
        old = self.conn.execute("SELECT * FROM books WHERE goodreads_book_id = ?", (gid,)).fetchone()
        outcome = self.create(res) if old is None else self.compare(res, dict(old))
        if outcome == REJECTED:
            return
        for w in res.warnings:
            for code in w.reasons:
                self.count(code)
            self.warnings.append(line(self.source_file, res, field=w.field, raw_value=w.raw_value,
                                      reason=w.reason, action=WARNING_ACTION[outcome]))
        if outcome != SKIPPED:                       # repairs are only listed when they were saved
            for r in res.repairs:
                self.count(r.code)
                self.repairs.append(line(self.source_file, res, field=r.field, original=r.original,
                                         new=r.new, reason=r.code))
        self.outcomes.append((outcome, bool(res.warnings)))

    def create(self, res):
        rec = dict(res.record, identity_key=res.record["goodreads_book_id"], fallback_key=None,
                   source_file=self.source_file, first_loaded_at=self.stamp, last_updated_at=None)
        cur = self.conn.execute(f"INSERT INTO books ({', '.join(BOOK_COLUMNS)}) VALUES ({', '.join('?' * len(BOOK_COLUMNS))})",
                                [rec[c] for c in BOOK_COLUMNS])
        self.save_warnings(cur.lastrowid, res)
        return LOADED

    def compare(self, res, old):
        rec = res.record
        changes, conflicts = [], []
        for f in IDENTITY_FIELDS:
            new, cur = rec[f], old[f]
            if new is None or same_value(f, cur, new):
                continue                             # a blank never erases a stored value (rules.md section 5, note 12)
            if cur is None:
                changes.append((f, cur, new))        # fill the gap
            else:
                conflicts.append(f"{f}: on file '{cur}', incoming '{new}'")
        if conflicts:
            self.reject(res, Rejection(IDENTITY_FIELD_CONFLICT, "; ".join(conflicts)))
            return REJECTED
        changes += [(f, old[f], rec[f]) for f in VOLATILE_FIELDS if rec[f] != old[f]]
        if not changes:
            return SKIPPED
        for f, cur, new in changes:
            self.conn.execute(f"UPDATE books SET {f} = ? WHERE id = ?", (new, old["id"]))
            self.updates.append(line(self.source_file, res, field=f, old=cur, new=new))
        self.conn.execute("UPDATE books SET last_updated_at = ? WHERE id = ?", (self.stamp, old["id"]))
        self.save_warnings(old["id"], res)
        return UPDATED


# --- log file ----------------------------------------------------------------------
def read_log(log_path: Path) -> list:
    """Earlier runs. A log that exists but can't be read stops everything (it is never overwritten)."""
    if not log_path.exists():
        return []
    try:
        entries = json.loads(log_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SystemExit(f"{log_path} exists but is not a readable JSON list ({e}); fix or move it, then run again. Nothing was changed.")
    if not isinstance(entries, list):
        raise SystemExit(f"{log_path} is not a JSON list; fix or move it, then run again. Nothing was changed.")
    return entries


def append_log(log_path: Path, entries: list, entry: dict):
    """Append one run; written to a temp file and swapped in, so the log is never left half-written."""
    fd, tmp = tempfile.mkstemp(dir=log_path.parent, prefix=".ingestion-log-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(entries + [entry], fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, log_path)


def run(csv_path, db_path=None, log_path=None, now=datetime.now) -> dict:
    csv_path = Path(csv_path)
    db_path = Path(db_path) if db_path else HERE / DB_FILENAME
    log_path = Path(log_path) if log_path else HERE / LOG_FILENAME
    earlier_runs = read_log(log_path)                # checked before anything is changed
    started = now()
    stamp = started.isoformat(timespec="seconds")
    run_id = f"{started:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest() if csv_path.is_file() else None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    r = Run(conn, csv_path.name, stamp)
    rows_read, status, error = 0, FAILED, None
    try:
        conn.executescript(SCHEMA)
        rows = read_rows(csv_path)
        rows_read = len(rows)
        for number, raw, problem in rows:
            if problem:
                res = RowResult(number, raw or {}, rejection=Rejection(STRUCTURAL_PARSE_ERROR, problem))
            else:
                res = validate_row(raw, number)
            r.process(res)
            conn.commit()                            # each row is saved as it is processed
        if len(r.outcomes) != rows_read:
            raise IngestError(f"counts don't add up: read {rows_read} rows but processed {len(r.outcomes)}")
        status = SUCCESS if not r.rejections and not r.warnings else WITH_ISSUES
    except Exception as e:
        conn.rollback()                              # undoes only the row in progress; earlier rows stay saved
        error = str(e) if isinstance(e, IngestError) else f"unexpected error: {e!r}"
    finally:
        conn.close()
    finished = now()

    n = {o: sum(1 for out, _ in r.outcomes if out == o) for o in (LOADED, UPDATED, SKIPPED, REJECTED)}
    loaded_warned = sum(1 for out, warned in r.outcomes if out == LOADED and warned)
    entry = {
        "run_id": run_id,
        "started_at": stamp,
        "finished_at": finished.isoformat(timespec="seconds"),
        "file": csv_path.name,
        "file_sha256": sha,
        "rules": "rules.md (group agreed rules, 2026-11-06)",
        "status": status,
        "status_note": FAILED_NOTE if status == FAILED else None,
        "error": error,
        "counts": {
            "rows_read": rows_read,
            "loaded": n[LOADED],
            "loaded_clean": n[LOADED] - loaded_warned,
            "loaded_with_warning": loaded_warned,
            "updated": n[UPDATED],
            "skipped": n[SKIPPED],
            "rejected": n[REJECTED],
            "rows_with_warning": sum(1 for out, warned in r.outcomes if warned),
            "rows_repaired": len({x["row_number"] for x in r.repairs}),
        },
        "counts_add_up": rows_read == sum(n.values()),
        "problem_counts": dict(sorted(r.problem_counts.items(), key=_problem_order)),
        "needs_attention": r.rejections,
        "warnings": r.warnings,
        "updates": r.updates,
        "repairs": r.repairs,
    }
    append_log(log_path, earlier_runs, entry)
    return entry


def _problem_order(item):
    code, count = item
    kind = 0 if code in REJECT_CODES else 1 if code in isbnlib.WARNING_CODES else 2
    return kind, -count, code


def summary_line(entry) -> str:
    c = entry["counts"]
    return (f"status={entry['status']} rows_read={c['rows_read']} loaded={c['loaded']} updated={c['updated']} "
            f"skipped={c['skipped']} rejected={c['rejected']} rows_with_warning={c['rows_with_warning']}")


def main() -> int:
    entry = run(HERE / CSV_FILENAME, HERE / DB_FILENAME, HERE / LOG_FILENAME)
    print(summary_line(entry))
    if entry["error"]:
        print("error:", entry["error"])
        print(entry["status_note"])
    return 2 if entry["status"] == FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
