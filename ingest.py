"""Load a books CSV into books.db following rules.md, and append one entry per
run to ingestion-log.json (read it with report.html).

    python ingest.py books.csv
    python ingest.py fixed-rows.csv --reprocess-of 20261031T140501-3f2a1c

If isbn-corrections.csv exists (approved by a person; see lookup_isbns.py and
rules.md section 5), its corrections are applied too -- read from the file,
never from the internet.

No AI and no network: the same file against the same database on the same
day always gives the same result. Every row is checked on every run, and the
whole run is one database transaction, so a failed run saves nothing.

Row rules (ISBNs, whitespace, years, required fields) live in validate.py and
isbn.py; this file does matching, saving, the log and the counts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import corrections as corrlib
from validate import (IDENTIFYING_FIELDS, ISSUE_TYPES, REFRESHABLE_FIELDS,
                      REQUIRED_COLUMNS, REVIEW_CODES, Issue, RowResult,
                      validate_row)

DB_PATH = "books.db"
LOG_PATH = "ingestion-log.json"

LOADED, UPDATED, SKIPPED, REJECTED = "loaded", "updated", "skipped_existing", "rejected"
SUCCESS, WITH_ISSUES, FAILED = "SUCCESS", "COMPLETED WITH ISSUES", "FAILED"

WARNING_ACTION = {
    LOADED: "LOADED with this warning",
    UPDATED: "UPDATED with this warning",
    SKIPPED: "SKIPPED (already in the database); the warning still applies",
}

NOTE_ACTION = {
    LOADED: "LOADED (note only, not a warning)",
    UPDATED: "UPDATED (note only, not a warning)",
    SKIPPED: "SKIPPED (already in the database; note only)",
}

# Where an approved correction came from, and why a book needs no ISBN. Updated (and audited)
# whenever a new value arrives; a blank never erases them.
PROVENANCE_FIELDS = ("isbn13_source", "publication_year_source", "no_isbn_reason")

BOOK_FIELDS = ("goodreads_book_id",) + IDENTIFYING_FIELDS + ("source_isbn", "source_isbn13") + REFRESHABLE_FIELDS + PROVENANCE_FIELDS

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS books (
    goodreads_book_id INTEGER PRIMARY KEY,
    {", ".join(f for f in BOOK_FIELDS if f != "goodreads_book_id")},
    match_key TEXT,
    created_by_run TEXT, last_changed_by_run TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS books_isbn13 ON books(isbn13) WHERE isbn13 IS NOT NULL;
CREATE INDEX IF NOT EXISTS books_match_key ON books(match_key);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, file TEXT, file_sha256 TEXT, started_at TEXT,
    finished_at TEXT, status TEXT, reprocess_of TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY, run_id TEXT, source_file TEXT, row_number INTEGER,
    goodreads_book_id INTEGER, field TEXT, old_value TEXT, new_value TEXT,
    reason TEXT, changed_at TEXT, actor TEXT
);
CREATE TABLE IF NOT EXISTS review_items (
    id INTEGER PRIMARY KEY, run_id TEXT, row_number INTEGER,
    goodreads_book_id INTEGER, problem TEXT, detail TEXT, status TEXT DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS rejected_rows (
    run_id TEXT, row_number INTEGER, goodreads_book_id TEXT, problem TEXT,
    detail TEXT, original_row TEXT, resolved_by_run TEXT,
    PRIMARY KEY (run_id, row_number)
);
"""


class IngestError(Exception):
    """A problem that makes the whole run FAILED (nothing is saved)."""


def match_key(title, authors):
    """Same title and author, ignoring capitals and extra spaces (possible-duplicate check)."""
    return " ".join((title or "").split()).casefold() + "\x1f" + " ".join((authors or "").split()).casefold()


def issue_line(source_file, res: RowResult, issue: Issue, action):
    t = ISSUE_TYPES[issue.code]
    return {
        "source_file": source_file,
        "row_number": res.row_number,
        "goodreads_book_id": res.raw.get("goodreads_book_id"),
        "title": res.raw.get("title"),
        "original_isbn": res.raw.get("isbn"),
        "original_isbn13": res.raw.get("isbn13"),
        "field": issue.field,
        "problem": issue.code,
        "detail": issue.detail,
        "action": action,
        "why": t.reason,
        "what_to_do": t.recommended,
    }


class Run:
    def __init__(self, conn, run_id, source_file, now):
        self.conn, self.run_id, self.source_file, self.now = conn, run_id, source_file, now
        self.outcomes = []          # one per row: loaded / updated / skipped_existing / rejected
        self.repaired = 0
        self.not_loaded = []        # issue lines for rejected rows
        self.warnings = []          # issue lines for rows that were loaded with a warning
        self.notes = []             # issue lines for notes (e.g. accepted without ISBN)
        self.corrected = 0          # rows where an approved correction was applied
        self.accepted_ids = set()   # goodreads_book_ids of rows that weren't rejected

    # --- database helpers -------------------------------------------------
    def audit(self, res, gid, field, old, new, reason):
        self.conn.execute(
            "INSERT INTO audit_log (run_id, source_file, row_number, goodreads_book_id, field, old_value, new_value, reason, changed_at, actor) "
            "VALUES (?,?,?,?,?,?,?,?,?, 'automatic')",
            (self.run_id, self.source_file, res.row_number, gid, field,
             None if old is None else str(old), None if new is None else str(new),
             reason, self.now().isoformat(timespec="seconds")))

    def review(self, res, gid, issue):
        self.conn.execute("INSERT INTO review_items (run_id, row_number, goodreads_book_id, problem, detail) VALUES (?,?,?,?,?)",
                          (self.run_id, res.row_number, gid, issue.code, issue.detail))

    def isbn_owner(self, isbn13, gid):
        return self.conn.execute("SELECT goodreads_book_id, title FROM books WHERE isbn13 = ? AND goodreads_book_id != ?",
                                 (isbn13, gid)).fetchone()

    # --- outcomes ---------------------------------------------------------
    def reject(self, res, issue):
        gid = res.record["goodreads_book_id"] if res.record else res.raw.get("goodreads_book_id")
        self.conn.execute("INSERT INTO rejected_rows (run_id, row_number, goodreads_book_id, problem, detail, original_row) VALUES (?,?,?,?,?,?)",
                          (self.run_id, res.row_number, None if gid is None else str(gid), issue.code, issue.detail,
                           json.dumps(res.raw, ensure_ascii=False)))
        if issue.code in REVIEW_CODES:
            self.review(res, gid, issue)
        self.not_loaded.append(issue_line(self.source_file, res, issue, "REJECTED: not loaded"))
        return REJECTED

    def process(self, res: RowResult, corrected=False):
        if res.rejected:
            outcome = self.reject(res, res.rejection)
        else:
            gid = res.record["goodreads_book_id"]
            existing = self.conn.execute("SELECT * FROM books WHERE goodreads_book_id = ?", (gid,)).fetchone()
            warnings = list(res.warnings)
            outcome = self.create(res, warnings) if existing is None else self.compare(res, dict(existing))
            if outcome != REJECTED:
                for rep in res.repairs:
                    self.audit(res, gid, rep.field, rep.original, rep.new, "repair: " + rep.reason)
                if res.repairs:
                    self.repaired += 1
                for issue in warnings:
                    if issue.code in REVIEW_CODES:
                        self.review(res, gid, issue)
                    self.warnings.append(issue_line(self.source_file, res, issue, WARNING_ACTION[outcome]))
                for issue in res.notes:
                    self.notes.append(issue_line(self.source_file, res, issue, NOTE_ACTION[outcome]))
                self.corrected += corrected
        if outcome != REJECTED:
            self.accepted_ids.add(str(res.record["goodreads_book_id"]))
        self.outcomes.append(outcome)

    def create(self, res, warnings):
        rec, gid = res.record, res.record["goodreads_book_id"]
        if rec["isbn13"] and (owner := self.isbn_owner(rec["isbn13"], gid)):
            return self.reject(res, Issue("isbn_in_use", "isbn13",
                                          f"ISBN {rec['isbn13']} already belongs to goodreads_book_id {owner['goodreads_book_id']} ('{owner['title']}')"))
        key = match_key(rec["title"], rec["authors"])
        if not rec["isbn13"]:
            twin = self.conn.execute("SELECT goodreads_book_id FROM books WHERE match_key = ? LIMIT 1", (key,)).fetchone()
            if twin:
                warnings.append(Issue("possible_duplicate", "title",
                                      f"same title and author as goodreads_book_id {twin['goodreads_book_id']}"))
        cols = BOOK_FIELDS + ("match_key", "created_by_run", "last_changed_by_run")
        self.conn.execute(f"INSERT INTO books ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [rec[c] for c in BOOK_FIELDS] + [key, self.run_id, self.run_id])
        self.audit(res, gid, "*", None, rec["title"], "created new book")
        return LOADED

    def compare(self, res, old):
        rec, gid = res.record, res.record["goodreads_book_id"]
        changes, conflicts = [], []
        for f in IDENTIFYING_FIELDS:
            new, cur = rec[f], old[f]
            if new is None or new == cur:
                continue                       # missing information never erases existing information
            if cur is None:
                if f == "isbn13" and (owner := self.isbn_owner(new, gid)):
                    conflicts.append((f, f"{new} already belongs to goodreads_book_id {owner['goodreads_book_id']}"))
                else:
                    changes.append((f, cur, new, "filled a blank field"))
            else:
                conflicts.append((f, f"database has '{cur}', file has '{new}'"))
        if conflicts:
            return self.reject(res, Issue("conflicts_existing", ", ".join(f for f, _ in conflicts),
                                          "; ".join(f"{f}: {text}" for f, text in conflicts)))
        for f in REFRESHABLE_FIELDS + ("source_isbn", "source_isbn13"):
            if rec[f] != old[f]:
                changes.append((f, old[f], rec[f], "refreshed value that doesn't identify the book"))
        for f in PROVENANCE_FIELDS:
            if rec[f] is not None and rec[f] != old[f]:
                changes.append((f, old[f], rec[f], "approved correction"))
        if not changes:
            return SKIPPED
        for f, cur, new, reason in changes:
            self.conn.execute(f"UPDATE books SET {f} = ?, last_changed_by_run = ? WHERE goodreads_book_id = ?",
                              (new, self.run_id, gid))
            self.audit(res, gid, f, cur, new, reason)
        if any(f in ("title", "authors") for f, *_ in changes):
            self.conn.execute("UPDATE books SET match_key = ? WHERE goodreads_book_id = ?",
                              (match_key(rec["title"] or old["title"], rec["authors"] or old["authors"]), gid))
        return UPDATED


# --- log file ---------------------------------------------------------------
def read_log(log_path: Path) -> list:
    """Earlier runs. A log that exists but can't be read stops everything (it is never overwritten)."""
    if not log_path.exists():
        return []
    try:
        entries = json.loads(log_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SystemExit(f"ERROR: {log_path} is not valid JSON ({e}). Nothing was imported and the log was not changed. "
                         f"Fix or move the file, then run again.")
    if not isinstance(entries, list):
        raise SystemExit(f"ERROR: {log_path} should contain a JSON list of runs. Nothing was imported and the log was not changed.")
    return entries


def append_log(log_path: Path, entries: list, entry: dict):
    """Add one run. Written to a temporary file first, so a crash can't damage earlier runs."""
    fd, tmp = tempfile.mkstemp(dir=log_path.resolve().parent, prefix=".ingestion-log-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(entries + [entry], fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, log_path)


def ensure_columns(conn):
    """Add columns introduced after a database was first created (keeps old books.db files working)."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(books)")}
    for f in BOOK_FIELDS:
        if f not in have:
            conn.execute(f"ALTER TABLE books ADD COLUMN {f}")


def read_csv(path: Path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in columns]
            if missing:
                raise IngestError(f"required column(s) missing: {', '.join(missing)}")
            return list(reader)
    except FileNotFoundError:
        raise IngestError(f"file not found: {path}")
    except (UnicodeDecodeError, csv.Error) as e:
        raise IngestError(f"file could not be read as a UTF-8 CSV: {e}")


def actions_required(not_loaded, warnings):
    counts = {}
    for line in not_loaded + warnings:
        counts[line["problem"]] = counts.get(line["problem"], 0) + 1
    order = sorted(counts, key=lambda c: (ISSUE_TYPES[c].action != "REJECT", -counts[c], c))
    out = []
    for code in order:
        verb = "rejected" if ISSUE_TYPES[code].action == "REJECT" else "loaded with a warning"
        out.append(f"{counts[code]} row(s) {verb} ({code}): {ISSUE_TYPES[code].recommended}")
    return counts, out


# --- one run ----------------------------------------------------------------
def ingest(csv_path, db_path=DB_PATH, log_path=LOG_PATH, now=datetime.now, reprocess_of=None,
           corrections_path=corrlib.CORRECTIONS_PATH) -> dict:
    csv_path, log_path = Path(csv_path), Path(log_path)
    earlier_runs = read_log(log_path)                     # checked before anything is changed
    started = now()
    run_id = f"{started:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest() if csv_path.is_file() else None

    conn = sqlite3.connect(db_path, isolation_level=None)  # transaction managed below
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    ensure_columns(conn)
    prev = conn.execute("SELECT run_id FROM runs WHERE file_sha256 = ? AND status != ? ORDER BY started_at DESC LIMIT 1",
                        (sha, FAILED)).fetchone()
    run = Run(conn, run_id, csv_path.name, now)
    rows_read, status, error = 0, FAILED, None
    corr = corrlib.Corrections()
    try:
        if reprocess_of and not conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (reprocess_of,)).fetchone():
            raise IngestError(f"--reprocess-of {reprocess_of}: no earlier run with that ID in {db_path}")
        rows = read_csv(csv_path)
        rows_read = len(rows)
        try:
            corr = corrlib.load(corrections_path)
        except corrlib.CorrectionsError as e:
            raise IngestError(str(e))
        conn.execute("BEGIN")
        for i, raw in enumerate(rows):
            res = validate_row(raw, i + 2, started.date())          # row 1 is the header, as in a spreadsheet
            if res.record is not None:
                for f in PROVENANCE_FIELDS:
                    res.record.setdefault(f, None)
            run.process(res, corrected=corrlib.apply(res, corr))
        if len(run.outcomes) != rows_read:
            raise IngestError(f"counts don't add up: read {rows_read} rows but processed {len(run.outcomes)}")
        if reprocess_of:
            # Earlier rejections of books that loaded this time are marked as fixed by this run.
            conn.executemany("UPDATE rejected_rows SET resolved_by_run = ? WHERE run_id = ? AND resolved_by_run IS NULL AND goodreads_book_id = ?",
                             [(run_id, reprocess_of, gid) for gid in sorted(run.accepted_ids)])
        status = SUCCESS if not run.not_loaded and not run.warnings else WITH_ISSUES
    except Exception as e:   # any failure: nothing from this run is kept
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        error = str(e) if isinstance(e, IngestError) else f"unexpected error: {e!r}"
        run = Run(conn, run_id, csv_path.name, now)
    finished = now()
    conn.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",
                 (run_id, csv_path.name, sha, started.isoformat(timespec="seconds"),
                  finished.isoformat(timespec="seconds"), status, reprocess_of))
    if conn.in_transaction:
        conn.execute("COMMIT")
    conn.close()

    c = {o: run.outcomes.count(o) for o in (LOADED, UPDATED, SKIPPED, REJECTED)}
    rows_with_warnings = len({w["row_number"] for w in run.warnings})
    problem_counts, actions = actions_required(run.not_loaded, run.warnings)
    if status == FAILED:
        actions = ["Fix the problem in 'error' and run the import again. Nothing from this run was saved."]
    entry = {
        "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "file": csv_path.name,
        "file_sha256": sha,
        "already_imported_as": prev["run_id"] if prev else None,
        "reprocess_of": reprocess_of,
        "status": status,
        "error": error,
        "counts": {
            "read": rows_read,
            "loaded": c[LOADED], "updated": c[UPDATED], "skipped_existing": c[SKIPPED], "rejected": c[REJECTED],
            "repaired": run.repaired, "rows_with_warnings": rows_with_warnings,
            "corrected": run.corrected, "accepted_without_isbn": len({n["row_number"] for n in run.notes}),
        },
        "counts_add_up": None if status == FAILED else rows_read == sum(c.values()),
        "problem_counts": problem_counts,
        "actions_required": actions,
        "not_loaded": run.not_loaded,
        "warnings": run.warnings,
        "notes": run.notes,
        "corrections": corr.summary(),
    }
    append_log(log_path, earlier_runs, entry)
    return entry


def main(argv=None):
    p = argparse.ArgumentParser(description="Load a books CSV into books.db and log the run to ingestion-log.json.")
    p.add_argument("csv_file", help="the books CSV to load")
    p.add_argument("--reprocess-of", metavar="RUN_ID", help="run ID whose rejected rows this file corrects")
    p.add_argument("--db", default=DB_PATH, help=f"SQLite database (default: {DB_PATH})")
    p.add_argument("--log", default=LOG_PATH, help=f"run log (default: {LOG_PATH})")
    p.add_argument("--corrections", default=corrlib.CORRECTIONS_PATH,
                   help=f"approved corrections, used if the file exists (default: {corrlib.CORRECTIONS_PATH})")
    a = p.parse_args(argv)
    e = ingest(a.csv_file, a.db, a.log, reprocess_of=a.reprocess_of, corrections_path=a.corrections)
    n = e["counts"]
    print(f"{e['status']}: read {n['read']}, loaded {n['loaded']}, updated {n['updated']}, "
          f"skipped (already exist) {n['skipped_existing']}, rejected {n['rejected']} "
          f"| repaired {n['repaired']}, with warnings {n['rows_with_warnings']}")
    if e["corrections"]["file"]:
        print(f"Corrections from {e['corrections']['file']}: {n['corrected']} applied, "
              f"{n['accepted_without_isbn']} accepted without ISBN, {len(e['corrections']['unusable'])} unusable")
    if e["error"]:
        print("Error:", e["error"])
    print(f"Run {e['run_id']} added to {a.log}. Open report.html to read it.")
    return 2 if e["status"] == FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
