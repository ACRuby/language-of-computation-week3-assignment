"""ingest.py: counts, duplicates, the append-only log, failures and reprocessing.
The row rules themselves are tested in test_isbn.py / test_import.py (shared validate.py).
Run: py -3.13 -m unittest discover tests"""
import contextlib
import csv
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest
from test_import import HEADER, OTHER, book

NOW = datetime(2026, 10, 31, 2, 0, 0)


class IngestTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db, self.log = self.dir / "books.db", self.dir / "ingestion-log.json"
        self.corrections = self.dir / "isbn-corrections.csv"     # never the real one in the project folder
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rows, header=HEADER):
        self.n += 1
        path = self.dir / f"file{self.n}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, header, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return path

    def run_file(self, path, **kw):
        kw.setdefault("corrections_path", self.corrections)
        return ingest.ingest(path, self.db, self.log, now=lambda: NOW, **kw)

    def log_entries(self):
        return json.loads(self.log.read_text(encoding="utf-8"))

    def books(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT count(*) FROM books").fetchone()[0]
        finally:
            conn.close()


class Counts(IngestTestCase):
    def test_counts_map_to_outcomes_and_add_up(self):
        self.run_file(self.write([book()]))
        e = self.run_file(self.write([
            book(),                                         # already exists, nothing new -> skipped
            book(ratings_count="5000000"),                  # same book again, ratings changed -> updated
            book(**OTHER),                                  # new -> loaded
            book(goodreads_book_id="70", title=""),         # rejected
            book(goodreads_book_id="71", isbn="", isbn13="", title="No ISBN"),   # loaded with warning
        ]))
        self.assertEqual(e["counts"], {"read": 5, "loaded": 2, "updated": 1, "skipped_existing": 1, "rejected": 1,
                                       "repaired": 4, "rows_with_warnings": 1, "corrected": 0, "accepted_without_isbn": 0})
        self.assertTrue(e["counts_add_up"])
        self.assertEqual(e["status"], "COMPLETED WITH ISSUES")

    def test_not_loaded_rows_have_reason_and_what_to_do(self):
        e = self.run_file(self.write([book(title="   "), book(**OTHER)]))
        [row] = e["not_loaded"]
        self.assertEqual((row["row_number"], row["problem"], row["original_isbn"]), (2, "missing_title", "439023483"))
        self.assertTrue(row["why"] and row["what_to_do"] and row["action"].startswith("REJECTED"))
        self.assertEqual(e["warnings"], [])

    def test_clean_file_is_success(self):
        e = self.run_file(self.write([book(), book(**OTHER)]))
        self.assertEqual((e["status"], e["actions_required"]), ("SUCCESS", []))


class Duplicates(IngestTestCase):
    def test_same_file_twice_creates_no_duplicates(self):
        path = self.write([book(), book(**OTHER), book(goodreads_book_id="50", isbn="", isbn13="", title="No ISBN")])
        first, second = self.run_file(path), self.run_file(path)
        self.assertEqual(first["counts"]["loaded"], 3)
        self.assertEqual((second["counts"]["loaded"], second["counts"]["skipped_existing"]), (0, 3))
        self.assertEqual(second["already_imported_as"], first["run_id"])
        self.assertEqual(self.books(), 3)

    def test_possible_duplicate_ignores_capitals_and_extra_spaces(self):
        e = self.run_file(self.write([
            book(goodreads_book_id="80", isbn="", isbn13="", title="The Stranger", authors="Albert Camus"),
            book(goodreads_book_id="81", isbn="", isbn13="", title="the  STRANGER", authors=" albert camus"),
        ]))
        self.assertEqual(e["counts"]["loaded"], 2)                     # flagged, never merged
        self.assertIn("possible_duplicate", [w["problem"] for w in e["warnings"] if w["row_number"] == 3])

    def test_scientific_isbn13_mismatch_is_a_conflict(self):
        e = self.run_file(self.write([book(isbn="446612707", isbn13="9.78055381395e+12")]))   # book 622
        self.assertEqual([w["problem"] for w in e["warnings"]], ["isbn_conflict"])

    def test_original_title_change_is_rejected(self):
        self.run_file(self.write([book()]))
        e = self.run_file(self.write([book(original_title="Hunger Games")]))
        self.assertEqual([r["problem"] for r in e["not_loaded"]], ["conflicts_existing"])

    def test_goodreads_id_must_be_positive_whole_number(self):
        e = self.run_file(self.write([book(goodreads_book_id="123.0"), book(goodreads_book_id="-5"), book(goodreads_book_id="0")]))
        self.assertEqual(e["counts"]["rejected"], 3)


class Log(IngestTestCase):
    def test_log_is_created_then_appended_never_overwritten(self):
        self.assertFalse(self.log.exists())
        a = self.run_file(self.write([book()]))
        b = self.run_file(self.write([book(**OTHER)]))
        entries = self.log_entries()
        self.assertEqual([x["run_id"] for x in entries], [a["run_id"], b["run_id"]])
        self.assertEqual(entries[0], a)                               # earlier run unchanged

    def test_failed_run_is_logged_and_saves_nothing(self):
        e = self.run_file(self.write([book()], header=[h for h in HEADER if h != "isbn13"]))
        self.assertEqual(e["status"], "FAILED")
        self.assertIn("isbn13", e["error"])
        self.assertEqual(self.books(), 0)
        self.assertEqual(self.log_entries()[-1]["status"], "FAILED")

    def test_damaged_log_stops_the_run_and_is_left_untouched(self):
        self.log.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(SystemExit):
            self.run_file(self.write([book()]))
        self.assertEqual(self.log.read_text(encoding="utf-8"), "{ not json")
        self.assertFalse(self.db.exists())                           # nothing imported

    def test_same_file_gives_same_result(self):
        path = self.write([book(), book(title=""), book(isbn="1847386823", **{k: v for k, v in OTHER.items() if k != "isbn"})])
        other_db = self.dir / "other.db"
        a = ingest.ingest(path, self.db, self.log, now=lambda: NOW, corrections_path=self.corrections)
        b = ingest.ingest(path, other_db, self.dir / "other-log.json", now=lambda: NOW, corrections_path=self.corrections)
        strip = lambda e: {k: v for k, v in e.items() if k not in ("run_id",)}   # noqa: E731
        self.assertEqual(strip(a), strip(b))

    def test_command_line_exit_codes(self):
        with contextlib.redirect_stdout(io.StringIO()):     # keep the expected "FAILED" message out of test output
            args = ["--db", str(self.db), "--log", str(self.log), "--corrections", str(self.corrections)]
            ok = ingest.main([str(self.write([book()]))] + args)
            failed = ingest.main([str(self.dir / "nope.csv")] + args)
        self.assertEqual((ok, failed), (0, 2))


class Reprocess(IngestTestCase):
    def test_corrected_rows_linked_to_earlier_run(self):
        first = self.run_file(self.write([book(title=""), book(**OTHER)]))
        fixed = self.run_file(self.write([book()]), reprocess_of=first["run_id"])
        self.assertEqual((fixed["counts"]["loaded"], fixed["reprocess_of"]), (1, first["run_id"]))
        conn = sqlite3.connect(self.db)
        resolved = conn.execute("SELECT resolved_by_run FROM rejected_rows WHERE run_id = ?", (first["run_id"],)).fetchone()[0]
        conn.close()
        self.assertEqual(resolved, fixed["run_id"])

    def test_unknown_reprocess_run_fails(self):
        e = self.run_file(self.write([book()]), reprocess_of="no-such-run")
        self.assertEqual(e["status"], "FAILED")
        self.assertEqual(self.books(), 0)


@unittest.skipUnless((ROOT / "books.csv").exists() and (ROOT / "books-batch2.csv").exists(), "data files not present")
class RealData(IngestTestCase):
    def test_books_then_batch2(self):
        first = ingest.ingest(ROOT / "books.csv", self.db, self.log, now=lambda: NOW, corrections_path=self.corrections)
        self.assertEqual((first["counts"]["read"], first["counts"]["loaded"], first["counts"]["rejected"]), (10000, 10000, 0))
        batch2 = ingest.ingest(ROOT / "books-batch2.csv", self.db, self.log, now=lambda: NOW, corrections_path=self.corrections)
        self.assertEqual((batch2["counts"]["loaded"], batch2["counts"]["skipped_existing"]), (0, 200))
        self.assertEqual(self.books(), 10000)
        self.assertEqual(len(self.log_entries()), 2)


if __name__ == "__main__":
    unittest.main()
