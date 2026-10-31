"""Nightly book import: validate a CSV of books, load it into SQLite, and
write a report for the next morning.

    py -3.13 import_books.py books.csv
    py -3.13 import_books.py fixed-rows.csv --reprocess-of 20261031T140501-3f2a1c

Every row ends up with exactly one outcome: CREATED, UPDATED, UNCHANGED or
REJECTED. The whole import runs in one transaction, so a failure leaves the
database exactly as it was. Rules: rules.md. Design: implementation.md.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import report
from validate import (IDENTIFYING_FIELDS, REFRESHABLE_FIELDS, REQUIRED_COLUMNS,
                      REVIEW_CODES, Issue, RowResult, validate_row)

CREATED, UPDATED, UNCHANGED, REJECTED = "CREATED", "UPDATED", "UNCHANGED", "REJECTED"
SUCCESS, WITH_ISSUES, FAILED = "SUCCESS", "COMPLETED WITH ISSUES", "FAILED"

PUBLICATION_FIELDS = ("goodreads_book_id",) + IDENTIFYING_FIELDS + ("source_isbn", "source_isbn13") + REFRESHABLE_FIELDS

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS imports (
    import_id TEXT PRIMARY KEY, file_name TEXT, file_sha256 TEXT,
    started_at TEXT, ended_at TEXT, status TEXT, total_rows INTEGER,
    created INTEGER, updated INTEGER, unchanged INTEGER, rejected INTEGER,
    repaired INTEGER, warnings INTEGER, reprocess_of TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS publications (
    goodreads_book_id INTEGER PRIMARY KEY,
    {", ".join(f for f in PUBLICATION_FIELDS if f != "goodreads_book_id")},
    created_by_import TEXT, last_changed_by_import TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS publications_isbn13 ON publications(isbn13) WHERE isbn13 IS NOT NULL;
CREATE TABLE IF NOT EXISTS row_outcomes (
    import_id TEXT, row_number INTEGER, goodreads_book_id INTEGER, outcome TEXT,
    repairs TEXT, warnings TEXT, PRIMARY KEY (import_id, row_number)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY, import_id TEXT, source_file TEXT, row_number INTEGER,
    goodreads_book_id INTEGER, field TEXT, original_value TEXT, new_value TEXT,
    reason TEXT, changed_at TEXT, actor TEXT
);
CREATE TABLE IF NOT EXISTS rejected_rows (
    import_id TEXT, row_number INTEGER, goodreads_book_id TEXT, code TEXT,
    detail TEXT, original_row TEXT, resolved_by_import TEXT,
    PRIMARY KEY (import_id, row_number)
);
CREATE TABLE IF NOT EXISTS review_items (
    id INTEGER PRIMARY KEY, import_id TEXT, row_number INTEGER,
    goodreads_book_id INTEGER, code TEXT, detail TEXT, status TEXT DEFAULT 'open'
);
"""


@dataclass
class RowOutcome:
    result: RowResult
    outcome: str
    problems: list[Issue] = field(default_factory=list)   # rejection reason(s) + warnings


@dataclass
class ImportSummary:
    import_id: str
    file_name: str
    started_at: datetime
    ended_at: datetime | None = None
    status: str = FAILED
    rows: list[RowOutcome] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    note: str | None = None
    previous_import: str | None = None
    reprocess_of: str | None = None
    report_paths: dict = field(default_factory=dict)

    def count(self, outcome):
        return sum(1 for r in self.rows if r.outcome == outcome)

    @property
    def repaired(self):
        return sum(1 for r in self.rows if r.outcome != REJECTED and r.result.repairs)

    @property
    def warned(self):
        return sum(1 for r in self.rows if r.outcome != REJECTED and r.problems)

    def reconciles(self):
        return len(self.rows) == sum(self.count(o) for o in (CREATED, UPDATED, UNCHANGED, REJECTED))


class ImportFailed(Exception):
    pass


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)   # transactions managed explicitly
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class Importer:
    def __init__(self, conn, summary: ImportSummary, now):
        self.conn, self.s, self.now = conn, summary, now

    def audit(self, row_number, gid, field_name, old, new, reason):
        self.conn.execute(
            "INSERT INTO audit_log (import_id, source_file, row_number, goodreads_book_id, field, original_value, new_value, reason, changed_at, actor) "
            "VALUES (?,?,?,?,?,?,?,?,?, 'automatic')",
            (self.s.import_id, self.s.file_name, row_number, gid, field_name,
             None if old is None else str(old), None if new is None else str(new), reason, self.now().isoformat(timespec="seconds")))

    def review(self, row_number, gid, issue: Issue):
        self.conn.execute("INSERT INTO review_items (import_id, row_number, goodreads_book_id, code, detail) VALUES (?,?,?,?,?)",
                          (self.s.import_id, row_number, gid, issue.code, issue.detail))

    def reject(self, res: RowResult, issues: list[Issue]) -> RowOutcome:
        gid = res.record["goodreads_book_id"] if res.record else res.raw.get("goodreads_book_id")
        self.conn.execute("INSERT INTO rejected_rows (import_id, row_number, goodreads_book_id, code, detail, original_row) VALUES (?,?,?,?,?,?)",
                          (self.s.import_id, res.row_number, gid, issues[0].code, "; ".join(i.detail for i in issues),
                           json.dumps(res.raw, ensure_ascii=False)))
        for issue in issues:
            if issue.code in REVIEW_CODES:
                self.review(res.row_number, gid, issue)
        return RowOutcome(res, REJECTED, issues)

    def isbn_owner(self, isbn13, gid):
        return self.conn.execute("SELECT goodreads_book_id, title FROM publications WHERE isbn13 = ? AND goodreads_book_id != ?",
                                 (isbn13, gid)).fetchone()

    def process(self, res: RowResult) -> RowOutcome:
        if res.rejected:
            return self.reject(res, [res.rejection])
        rec, gid = res.record, res.record["goodreads_book_id"]
        existing = self.conn.execute("SELECT * FROM publications WHERE goodreads_book_id = ?", (gid,)).fetchone()
        warnings = list(res.warnings)
        if existing is None:
            outcome = self.create(res, warnings)
        else:
            outcome = self.compare(res, dict(existing), warnings)
        if outcome.outcome == REJECTED:
            return outcome
        for issue in warnings:
            if issue.code in REVIEW_CODES:
                self.review(res.row_number, gid, issue)
        for rep in res.repairs:
            self.audit(res.row_number, gid, rep.field, rep.original, rep.new, "repair: " + rep.reason)
        # A corrected row that now loads closes out earlier rejections of the same book.
        self.conn.execute("UPDATE rejected_rows SET resolved_by_import = ? WHERE goodreads_book_id = ? AND resolved_by_import IS NULL AND import_id != ?",
                          (self.s.import_id, str(gid), self.s.import_id))
        outcome.problems = warnings
        return outcome

    def create(self, res, warnings) -> RowOutcome:
        rec, gid = res.record, res.record["goodreads_book_id"]
        if rec["isbn13"] and (owner := self.isbn_owner(rec["isbn13"], gid)):
            return self.reject(res, [Issue("isbn_in_use", "isbn13", f"ISBN {rec['isbn13']} already belongs to goodreads_book_id {owner['goodreads_book_id']} ('{owner['title']}')")])
        if not rec["isbn13"]:
            twin = self.conn.execute(
                "SELECT goodreads_book_id FROM publications WHERE lower(title) = lower(?) AND lower(coalesce(authors,'')) = lower(coalesce(?,'')) LIMIT 1",
                (rec["title"], rec["authors"])).fetchone()
            if twin:
                warnings.append(Issue("possible_duplicate", "title", f"same title and author as goodreads_book_id {twin['goodreads_book_id']}"))
        cols = PUBLICATION_FIELDS + ("created_by_import", "last_changed_by_import")
        self.conn.execute(f"INSERT INTO publications ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                          [rec[c] for c in PUBLICATION_FIELDS] + [self.s.import_id, self.s.import_id])
        self.audit(res.row_number, gid, "*", None, rec["title"], "created new publication")
        return RowOutcome(res, CREATED)

    def compare(self, res, old, warnings) -> RowOutcome:
        rec, gid = res.record, res.record["goodreads_book_id"]
        changes, conflicts = [], []
        for f in IDENTIFYING_FIELDS:
            new, cur = rec[f], old[f]
            if new is None or new == cur:
                continue                       # missing info never erases existing info
            if cur is None:
                if f == "isbn13" and (owner := self.isbn_owner(new, gid)):
                    conflicts.append((f, f"{new} already belongs to goodreads_book_id {owner['goodreads_book_id']}"))
                else:
                    changes.append((f, cur, new, "filled a blank field"))
            else:
                conflicts.append((f, f"catalog has '{cur}', file has '{new}'"))
        if conflicts:
            return self.reject(res, [Issue("conflicts_existing", ", ".join(f for f, _ in conflicts),
                                           "; ".join(f"{f}: {text}" for f, text in conflicts))])
        for f in REFRESHABLE_FIELDS:
            if rec[f] != old[f]:
                changes.append((f, old[f], rec[f], "refreshed non-identifying value"))
        for f in ("source_isbn", "source_isbn13"):
            if rec[f] != old[f]:
                changes.append((f, old[f], rec[f], "new original ISBN text from source"))
        if not changes:
            return RowOutcome(res, UNCHANGED)
        for f, cur, new, reason in changes:
            self.conn.execute(f"UPDATE publications SET {f} = ?, last_changed_by_import = ? WHERE goodreads_book_id = ?", (new, self.s.import_id, gid))
            self.audit(res.row_number, gid, f, cur, new, reason)
        return RowOutcome(res, UPDATED)


def read_rows(path: Path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = reader.fieldnames or []
            missing = [c for c in REQUIRED_COLUMNS if c not in columns]
            if missing:
                raise ImportFailed(f"required column(s) missing: {', '.join(missing)}")
            rows = list(reader)
    except FileNotFoundError:
        raise ImportFailed(f"file not found: {path}")
    except (UnicodeDecodeError, csv.Error) as e:
        raise ImportFailed(f"file could not be read as UTF-8 CSV: {e}")
    return columns, rows


def run_import(csv_path, db_path="library.db", reports_dir="reports", now=datetime.now, reprocess_of=None) -> ImportSummary:
    csv_path, started = Path(csv_path), now()
    s = ImportSummary(f"{started:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}", csv_path.name, started, reprocess_of=reprocess_of)
    conn = connect(db_path)
    sha = hashlib.sha256(csv_path.read_bytes()).hexdigest() if csv_path.exists() else None
    prev = conn.execute("SELECT import_id FROM imports WHERE file_sha256 = ? AND status != ? ORDER BY started_at DESC LIMIT 1", (sha, FAILED)).fetchone()
    s.previous_import = prev["import_id"] if prev else None
    try:
        s.columns, rows = read_rows(csv_path)
        conn.execute("BEGIN")
        importer = Importer(conn, s, now)
        for i, raw in enumerate(rows):
            # Row numbers match a spreadsheet: the header is row 1.
            s.rows.append(importer.process(validate_row(raw, i + 2, started.date())))
        if len(s.rows) != len(rows) or not s.reconciles():
            raise ImportFailed(f"row counts don't reconcile: read {len(rows)}, accounted for {len(s.rows)}")
        for r in s.rows:
            conn.execute("INSERT INTO row_outcomes VALUES (?,?,?,?,?,?)",
                         (s.import_id, r.result.row_number, r.result.record["goodreads_book_id"] if r.result.record else None, r.outcome,
                          json.dumps([vars(x) for x in r.result.repairs], ensure_ascii=False),
                          json.dumps([vars(x) for x in r.problems], ensure_ascii=False)))
        clean = s.count(REJECTED) == 0 and s.warned == 0
        s.status = SUCCESS if clean else WITH_ISSUES
    except Exception as e:        # any failure: nothing from this run is kept
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        s.status, s.note = FAILED, str(e) if isinstance(e, ImportFailed) else f"unexpected error: {e!r}"
        s.rows = []
    s.ended_at = now()
    conn.execute("INSERT INTO imports VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (s.import_id, s.file_name, sha, s.started_at.isoformat(timespec="seconds"), s.ended_at.isoformat(timespec="seconds"),
                  s.status, len(s.rows), s.count(CREATED), s.count(UPDATED), s.count(UNCHANGED), s.count(REJECTED),
                  s.repaired, s.warned, reprocess_of, s.note))
    if conn.in_transaction:
        conn.execute("COMMIT")
    conn.close()
    s.report_paths = report.write_reports(s, Path(reports_dir))
    return s


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate and load a books CSV, then write a morning report.")
    p.add_argument("csv_file")
    p.add_argument("--db", default="library.db", help="SQLite database file (default: library.db)")
    p.add_argument("--reports", default="reports", help="folder for reports (default: reports/)")
    p.add_argument("--reprocess-of", help="import ID whose rejected rows this file corrects")
    a = p.parse_args(argv)
    s = run_import(a.csv_file, a.db, a.reports, reprocess_of=a.reprocess_of)
    print(f"{s.status}: {len(s.rows)} rows, {s.count(CREATED)} created, {s.count(UPDATED)} updated, "
          f"{s.count(UNCHANGED)} unchanged, {s.count(REJECTED)} rejected ({s.repaired} repaired, {s.warned} with warnings)")
    if s.note:
        print(s.note)
    print(f"Report: {s.report_paths['report']}")
    return 2 if s.status == FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
