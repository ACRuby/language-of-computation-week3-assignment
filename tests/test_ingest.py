"""ingest.py: the agreed rules end to end (rules.md sections 1-4, erd.md schema).
Run: py -3.13 -m unittest discover tests"""
import csv
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest
from validate import COLUMNS

NOW = datetime(2026, 11, 7, 2, 0, 0)
HG10, HG13 = "0439023483", "9780439023481"
HP10, HP13 = "043965548X", "9780439655484"


def book(gid="1", **values):
    row = {c: "" for c in COLUMNS}
    row.update(goodreads_book_id=gid, book_id=gid, title=f"Book {gid}", authors="An Author",
               original_publication_year="2008.0", language_code="eng", average_rating="4.1", ratings_count="100")
    row.update(values)
    return row


class IngestTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db, self.log = self.dir / "books.db", self.dir / "ingestion-log.json"
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rows, header=COLUMNS):
        self.n += 1
        path = self.dir / f"file{self.n}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, header, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return path

    def run_file(self, path):
        return ingest.run(path, self.db, self.log, now=lambda: NOW)

    def query(self, sql, *args):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, args)]
        finally:
            conn.close()


class Schema(IngestTestCase):
    def test_two_tables_as_in_the_erd(self):
        self.run_file(self.write([book("1", isbn=HG10)]))
        tables = [r["name"] for r in self.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        self.assertEqual(tables, ["books", "warnings"])
        cols = [r["name"] for r in self.query("PRAGMA table_info(books)")]
        self.assertEqual(cols, ["id"] + list(COLUMNS) + ["identity_key", "fallback_key", "source_file",
                                                          "first_loaded_at", "last_updated_at"])
        self.assertEqual([r["name"] for r in self.query("PRAGMA table_info(warnings)")],
                         ["id", "book_row_id", "field", "raw_value", "reason", "recorded_at"])
        b = self.query("SELECT * FROM books")[0]
        self.assertEqual((b["identity_key"], b["fallback_key"], b["isbn"], b["isbn13"]), ("1", None, HG10, HG13))
        indexes = {r["name"] for r in self.query("SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertTrue({"books_goodreads_book_id", "books_identity_key"} <= indexes)


class Loading(IngestTestCase):
    def test_counts_status_and_summary_line(self):
        e = self.run_file(self.write([book("1", isbn=HG10), book("2"), book("3", isbn="439023483")]))
        self.assertEqual(e["status"], "COMPLETED WITH ISSUES")
        c = e["counts"]
        self.assertEqual((c["rows_read"], c["loaded"], c["loaded_clean"], c["loaded_with_warning"]), (3, 2, 1, 1))
        self.assertEqual(c["rejected"], 1)                  # row 3 has the same ISBN as row 1: collision
        self.assertTrue(e["counts_add_up"])
        self.assertEqual(ingest.summary_line(e), "status=COMPLETED WITH ISSUES rows_read=3 loaded=2 updated=0 "
                                                 "skipped=0 rejected=1 rows_with_warning=1")

    def test_success_when_no_warnings(self):
        e = self.run_file(self.write([book("1", isbn=HG10), book("2", isbn13=HP13)]))
        self.assertEqual(e["status"], "SUCCESS")
        self.assertIsNone(e["status_note"])

    def test_bad_isbn_never_rejects_row_and_is_recorded_with_raw_value(self):
        e = self.run_file(self.write([book("1", isbn13="9.78043902348e+12")]))
        self.assertEqual(e["counts"]["loaded_with_warning"], 1)
        w = self.query("SELECT * FROM warnings")
        self.assertEqual([(x["field"], x["raw_value"], x["reason"]) for x in w],
                         [("isbn13", "9.78043902348e+12", "lost-precision,no-usable-isbn")])
        self.assertEqual(w[0]["book_row_id"], self.query("SELECT id FROM books")[0]["id"])
        self.assertIsNone(self.query("SELECT isbn13 FROM books")[0]["isbn13"])
        self.assertEqual(e["problem_counts"], {"no-usable-isbn": 1, "lost-precision": 1})

    def test_other_fields_passed_through_without_validation(self):
        e = self.run_file(self.write([book("1", isbn=HG10, title="", authors="", original_publication_year="-500.0",
                                           language_code="zz")]))
        self.assertEqual(e["status"], "SUCCESS")
        b = self.query("SELECT title, authors, original_publication_year FROM books")[0]
        self.assertEqual(b, {"title": None, "authors": None, "original_publication_year": "-500.0"})

    def test_repairs_are_listed(self):
        e = self.run_file(self.write([book("1", isbn="439023483", isbn13="9.78043902348e+12")]))
        self.assertEqual([r["reason"] for r in e["repairs"]], ["leading-zeros-restored", "isbn13-derived-from-isbn"])
        self.assertEqual(e["counts"]["rows_repaired"], 1)


class Rejections(IngestTestCase):
    def test_structural_parse_error_wrong_field_count(self):
        path = self.write([book("1", isbn=HG10)])
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write("2,3,only three fields\r\n")
        e = self.run_file(path)
        self.assertEqual(e["counts"]["rejected"], 1)
        self.assertEqual(e["needs_attention"][0]["reason"], "structural-parse-error")
        self.assertEqual(e["needs_attention"][0]["row_number"], 3)
        self.assertEqual(e["counts"]["loaded"], 1)

    def test_structural_parse_error_broken_quoting(self):
        path = self.write([book("1", isbn=HG10)])
        with open(path, "a", encoding="utf-8", newline="") as fh:
            fh.write('2,"broken"quote' + ",x" * 21 + "\r\n")
        e = self.run_file(path)
        self.assertEqual([r["reason"] for r in e["needs_attention"]], ["structural-parse-error"])

    def test_isbn_collision_with_different_goodreads_id(self):
        self.run_file(self.write([book("1", isbn=HG10)]))
        e = self.run_file(self.write([book("2", isbn13=HG13)]))
        self.assertEqual(e["needs_attention"][0]["reason"], "isbn-collision")
        self.assertEqual(len(self.query("SELECT * FROM books")), 1)

    def test_missing_or_invalid_goodreads_id(self):
        e = self.run_file(self.write([book(""), book("abc")]))
        self.assertEqual([r["reason"] for r in e["needs_attention"]], ["missing-goodreads-id", "invalid-goodreads-id"])


class Updates(IngestTestCase):
    def test_same_file_twice_skips_everything_and_keeps_one_copy(self):
        path = self.write([book("1", isbn=HG10), book("2")])
        self.run_file(path)
        e = self.run_file(path)
        self.assertEqual((e["counts"]["skipped"], e["counts"]["loaded"]), (2, 0))
        self.assertEqual(e["counts"]["rows_with_warning"], 1)   # book 2 still has no ISBN
        self.assertEqual(len(self.query("SELECT * FROM books")), 2)
        self.assertEqual(len(self.query("SELECT * FROM warnings")), 1)   # warnings don't pile up

    def test_volatile_metadata_updates_with_diff(self):
        self.run_file(self.write([book("1", isbn=HG10)]))
        e = self.run_file(self.write([book("1", isbn=HG10, average_rating="4.5", original_title="New")]))
        self.assertEqual(e["counts"]["updated"], 1)
        self.assertEqual({(u["field"], u["old"], u["new"]) for u in e["updates"]},
                         {("average_rating", "4.1", "4.5"), ("original_title", None, "New")})
        self.assertEqual(self.query("SELECT last_updated_at FROM books")[0]["last_updated_at"], NOW.isoformat())

    def test_identity_field_gap_is_filled(self):
        self.run_file(self.write([book("1")]))
        e = self.run_file(self.write([book("1", isbn=HG10)]))
        self.assertEqual(e["counts"]["updated"], 1)
        self.assertEqual(self.query("SELECT isbn13 FROM books")[0]["isbn13"], HG13)
        self.assertEqual(self.query("SELECT * FROM warnings"), [])      # replaced: the book has an ISBN now

    def test_identity_field_conflict_rejected_and_record_untouched(self):
        self.run_file(self.write([book("1", isbn=HG10)]))
        e = self.run_file(self.write([book("1", isbn=HP10, average_rating="1.0")]))
        self.assertEqual(e["needs_attention"][0]["reason"], "identity-field-conflict")
        b = self.query("SELECT isbn, average_rating FROM books")[0]
        self.assertEqual(b, {"isbn": HG10, "average_rating": "4.1"})

    def test_title_compared_case_insensitively(self):
        self.run_file(self.write([book("1", isbn=HG10, title="The Hunger Games")]))
        e = self.run_file(self.write([book("1", isbn=HG10, title="the hunger games!")]))
        self.assertEqual(e["counts"]["skipped"], 1)
        self.assertEqual(self.query("SELECT title FROM books")[0]["title"], "The Hunger Games")
        e = self.run_file(self.write([book("1", isbn=HG10, title="Catching Fire")]))
        self.assertEqual(e["needs_attention"][0]["reason"], "identity-field-conflict")

    def test_blank_never_erases_identity_field(self):
        self.run_file(self.write([book("1", isbn=HG10, authors="Suzanne Collins")]))
        e = self.run_file(self.write([book("1", isbn=HG10, authors="")]))
        self.assertEqual(e["counts"]["skipped"], 1)


class Failures(IngestTestCase):
    def test_missing_file_is_failed_with_note(self):
        e = ingest.run(self.dir / "nope.csv", self.db, self.log, now=lambda: NOW)
        self.assertEqual(e["status"], "FAILED")
        self.assertIn("atomicity", e["status_note"])

    def test_missing_column_is_failed(self):
        e = self.run_file(self.write([book("1")], header=[c for c in COLUMNS if c != "isbn13"]))
        self.assertEqual(e["status"], "FAILED")
        self.assertIn("isbn13", e["error"])

    def test_failure_partway_keeps_earlier_rows(self):
        path = self.write([book("1", isbn=HG10), book("2", isbn=HP10)])
        real = ingest.Run.create
        def boom(self, res):
            if res.record["goodreads_book_id"] == "2":
                raise RuntimeError("disk on fire")
            return real(self, res)
        with mock.patch.object(ingest.Run, "create", boom):
            e = self.run_file(path)
        self.assertEqual(e["status"], "FAILED")
        self.assertIn("may already be saved", e["status_note"])
        self.assertEqual([b["goodreads_book_id"] for b in self.query("SELECT * FROM books")], ["1"])

    def test_log_is_appended_never_overwritten(self):
        self.run_file(self.write([book("1", isbn=HG10)]))
        self.run_file(self.write([book("2", isbn=HP10)]))
        entries = json.loads(self.log.read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 2)

    def test_damaged_log_stops_before_anything_changes(self):
        self.log.write_text("{ broken", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_file(self.write([book("1")]))
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
