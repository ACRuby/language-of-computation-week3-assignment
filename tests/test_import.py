"""Row rules, duplicate/update logic, reports and idempotency (requirement
tests 11-30, plus the real goodbooks-10k files).
Run: py -3.13 -m unittest discover tests"""
import contextlib
import csv
import io
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import import_books
from import_books import run_import

NOW = datetime(2026, 10, 31, 2, 0, 0)
HEADER = ["book_id", "goodreads_book_id", "best_book_id", "work_id", "books_count", "isbn", "isbn13",
          "authors", "original_publication_year", "original_title", "title", "language_code", "ratings_count"]


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def book(**overrides):
    """A clean row in goodbooks-10k format (book 1, The Hunger Games)."""
    row = {"book_id": "1", "goodreads_book_id": "2767052", "best_book_id": "2767052", "work_id": "2792775",
           "books_count": "272", "isbn": "439023483", "isbn13": "9.78043902348e+12", "authors": "Suzanne Collins",
           "original_publication_year": "2008.0", "original_title": "The Hunger Games",
           "title": "The Hunger Games (The Hunger Games, #1)", "language_code": "eng", "ratings_count": "4780653"}
    row.update(overrides)
    return row


OTHER = dict(goodreads_book_id="3", isbn="439554934", isbn13="9.78043955493e+12", authors="J.K. Rowling",
             title="Harry Potter and the Sorcerer's Stone", original_title="Harry Potter and the Philosopher's Stone", work_id="4640799")


class ImportTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "library.db"
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_rows(self, rows, header=HEADER, **kw):
        self.n += 1
        path = self.dir / f"batch{self.n}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, header, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return run_import(path, self.db, self.dir / "reports", now=lambda: NOW, **kw)

    def query(self, sql, *args):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def pub(self, gid):
        rows = self.query("SELECT * FROM publications WHERE goodreads_book_id = ?", gid)
        return rows[0] if rows else None

    def outcomes(self, s):
        return [r.outcome for r in s.rows]

    def codes(self, s, i=0):
        return [p.code for p in s.rows[i].problems]


class RowRules(ImportTestCase):
    def test_clean_row_is_created_with_repairs(self):
        s = self.run_rows([book()])
        self.assertEqual(self.outcomes(s), ["CREATED"])
        p = self.pub(2767052)
        self.assertEqual((p["isbn13"], p["isbn10"], p["publication_year"]), ("9780439023481", "0439023483", 2008))
        self.assertEqual((p["source_isbn"], p["source_isbn13"]), ("439023483", "9.78043902348e+12"))   # originals kept
        self.assertEqual(s.status, "SUCCESS")      # repairs alone are not warnings

    def test_11_missing_isbn_loads_with_warning(self):
        s = self.run_rows([book(isbn="", isbn13="")])
        self.assertEqual((self.outcomes(s), self.codes(s)), (["CREATED"], ["no_usable_isbn"]))
        self.assertIsNone(self.pub(2767052)["isbn13"])

    def test_scientific_isbn13_without_isbn10_is_not_used(self):
        s = self.run_rows([book(isbn="")])
        self.assertEqual(self.codes(s), ["no_usable_isbn"])
        self.assertIsNone(self.pub(2767052)["isbn13"])

    def test_bad_isbn10_digits_are_never_changed(self):
        s = self.run_rows([book(isbn="1847386823", isbn13="")])
        self.assertEqual(self.codes(s), ["isbn10_invalid", "no_usable_isbn"])
        self.assertIsNone(self.pub(2767052)["isbn10"])

    def test_isbn_columns_pointing_to_different_editions(self):
        s = self.run_rows([book(isbn="446612707", isbn13="9.78055381395e+12")])     # book 622
        self.assertEqual(self.codes(s), ["isbn_conflict"])
        self.assertIsNone(self.pub(2767052)["isbn13"])
        self.assertEqual(len(self.query("SELECT * FROM review_items WHERE code = 'isbn_conflict'")), 1)

    def test_rounded_up_isbn13_rebuilt_from_isbn10(self):
        self.run_rows([book(isbn="679783261", isbn13="9.78067978327e+12")])       # book 10
        self.assertEqual(self.pub(2767052)["isbn13"], "9780679783268")

    def test_12_missing_title_rejected(self):
        s = self.run_rows([book(title=""), book(title="   ", goodreads_book_id="9")])
        self.assertEqual(self.outcomes(s), ["REJECTED", "REJECTED"])
        self.assertEqual(self.codes(s), ["missing_title"])
        self.assertIsNone(self.pub(2767052))
        rejected = read_csv(s.report_paths["rejected"])
        self.assertEqual([r["row_number"] for r in rejected], ["2", "3"])
        self.assertEqual(rejected[0]["isbn"], "439023483")          # original data preserved

    def test_missing_or_bad_goodreads_id_rejected(self):
        s = self.run_rows([book(goodreads_book_id=""), book(goodreads_book_id="abc")])
        self.assertEqual([r.problems[0].code for r in s.rows], ["missing_id", "invalid_id"])

    def test_13_missing_author_loads_with_warning(self):
        s = self.run_rows([book(authors="")])
        self.assertEqual((self.outcomes(s), self.codes(s)), (["CREATED"], ["missing_author"]))
        self.assertIsNone(self.pub(2767052)["authors"])

    def test_14_missing_publisher(self):
        self.skipTest("Not applicable: goodbooks-10k has no publisher column (see implementation.md)")

    def test_15_missing_year_loads_with_warning(self):
        s = self.run_rows([book(original_publication_year="")])
        self.assertEqual(self.codes(s), ["missing_year"])
        self.assertIsNone(self.pub(2767052)["publication_year"])    # never filled with the current year

    def test_16_invalid_year_field_dropped_row_kept(self):
        s = self.run_rows([book(original_publication_year="20o8"), book(original_publication_year="0", **OTHER)])
        self.assertEqual(self.outcomes(s), ["CREATED", "CREATED"])
        self.assertEqual([self.codes(s, i) for i in (0, 1)], [["invalid_year"], ["invalid_year"]])
        self.assertIsNone(self.pub(2767052)["publication_year"])

    def test_17_future_year_kept_with_warning(self):
        s = self.run_rows([book(original_publication_year="2030")])
        self.assertEqual(self.codes(s), ["future_year"])
        self.assertEqual(self.pub(2767052)["publication_year"], 2030)

    def test_negative_year_is_bc_not_an_error(self):
        s = self.run_rows([book(original_publication_year="-750.0")])
        self.assertEqual(self.codes(s), [])
        self.assertEqual(self.pub(2767052)["publication_year"], -750)

    def test_whitespace_repaired_and_original_audited(self):
        self.run_rows([book(title="  The Hunger  Games ")])
        self.assertEqual(self.pub(2767052)["title"], "The Hunger Games")
        audit = self.query("SELECT original_value, new_value FROM audit_log WHERE field = 'title'")
        self.assertEqual(tuple(audit[0]), ("  The Hunger  Games ", "The Hunger Games"))

    def test_capitalization_and_special_characters_preserved(self):
        self.run_rows([book(title="the HUNGER games & Café — حكاية")])
        self.assertEqual(self.pub(2767052)["title"], "the HUNGER games & Café — حكاية")


class Duplicates(ImportTestCase):
    def test_18_exact_duplicate_rows_in_one_file(self):
        s = self.run_rows([book(), book()])
        self.assertEqual(self.outcomes(s), ["CREATED", "UNCHANGED"])
        self.assertEqual(len(self.query("SELECT * FROM publications")), 1)

    def test_19_same_isbn_matching_metadata(self):
        self.run_rows([book()])
        s = self.run_rows([book(isbn="0-439-02348-3")])     # same book, ISBN formatted differently
        self.assertEqual(self.outcomes(s), ["UPDATED"])         # only the source text changed
        self.assertEqual(self.pub(2767052)["isbn13"], "9780439023481")
        self.assertEqual(len(self.query("SELECT * FROM publications")), 1)

    def test_20_same_isbn_different_book_rejected_for_review(self):
        self.run_rows([book()])
        s = self.run_rows([book(goodreads_book_id="999", title="Something Else")])
        self.assertEqual((self.outcomes(s), self.codes(s)), (["REJECTED"], ["isbn_in_use"]))
        self.assertIsNone(self.pub(999))
        self.assertEqual(len(self.query("SELECT * FROM review_items WHERE code = 'isbn_in_use'")), 1)

    def test_21_same_title_different_isbns_not_merged(self):
        s = self.run_rows([book(), book(goodreads_book_id="5", isbn="043965548X", isbn13="")])
        self.assertEqual(self.outcomes(s), ["CREATED", "CREATED"])
        self.assertEqual(self.codes(s, 1), [])          # valid different ISBN: not even flagged

    def test_22_different_editions_of_one_work_stay_separate(self):
        self.run_rows([book(), book(goodreads_book_id="5", isbn="043965548X", isbn13="", title="The Hunger Games (Paperback)")])
        rows = self.query("SELECT goodreads_book_id, work_id FROM publications ORDER BY goodreads_book_id")
        self.assertEqual([tuple(r) for r in rows], [(5, 2792775), (2767052, 2792775)])

    def test_23_records_without_isbn(self):
        s = self.run_rows([book(isbn="", isbn13=""),
                           book(goodreads_book_id="77", isbn="", isbn13=""),                  # same title + author
                           book(goodreads_book_id="78", isbn="", isbn13="", title="Mockingjay")])
        self.assertEqual(self.outcomes(s), ["CREATED"] * 3)                   # never merged automatically
        self.assertIn("possible_duplicate", self.codes(s, 1))
        self.assertNotIn("possible_duplicate", self.codes(s, 2))
        self.assertEqual(len(self.query("SELECT * FROM review_items WHERE code = 'possible_duplicate'")), 1)


class ExistingRecords(ImportTestCase):
    def test_24_new_information_fills_blank_field(self):
        self.run_rows([book(authors="")])
        s = self.run_rows([book()])
        self.assertEqual(self.outcomes(s), ["UPDATED"])
        self.assertEqual(self.pub(2767052)["authors"], "Suzanne Collins")
        audit = self.query("SELECT original_value, new_value, reason FROM audit_log WHERE field = 'authors'")
        self.assertEqual(tuple(audit[0]), (None, "Suzanne Collins", "filled a blank field"))

    def test_25_conflicting_information_is_not_overwritten(self):
        self.run_rows([book()])
        for change in ({"authors": "Someone Else"}, {"original_publication_year": "2010"},
                       {"title": "The Hunger Games!"}, {"isbn": "043965548X", "isbn13": ""}):
            with self.subTest(change=change):
                s = self.run_rows([book(**change)])
                self.assertEqual((self.outcomes(s), self.codes(s)), (["REJECTED"], ["conflicts_existing"]))
        p = self.pub(2767052)
        self.assertEqual((p["authors"], p["publication_year"], p["isbn13"]), ("Suzanne Collins", 2008, "9780439023481"))
        self.assertEqual(len(self.query("SELECT * FROM review_items WHERE code = 'conflicts_existing'")), 4)

    def test_missing_value_never_erases_existing(self):
        self.run_rows([book()])
        s = self.run_rows([book(authors="", isbn="", isbn13="")])
        self.assertEqual(self.outcomes(s), ["UPDATED"])         # only source ISBN text changed
        p = self.pub(2767052)
        self.assertEqual((p["authors"], p["isbn13"]), ("Suzanne Collins", "9780439023481"))

    def test_whitespace_only_title_change_is_unchanged(self):
        self.run_rows([book()])
        s = self.run_rows([book(title=" The Hunger  Games (The Hunger Games, #1) ")])
        self.assertEqual(self.outcomes(s), ["UNCHANGED"])

    def test_ratings_refresh_is_an_audited_update(self):
        self.run_rows([book()])
        s = self.run_rows([book(ratings_count="4800000")])
        self.assertEqual(self.outcomes(s), ["UPDATED"])
        audit = self.query("SELECT original_value, new_value FROM audit_log WHERE field = 'ratings_count'")
        self.assertEqual(tuple(audit[0]), ("4780653", "4800000"))

    def test_26_repeated_import_changes_nothing(self):
        rows = [book(), book(**OTHER), book(goodreads_book_id="50", isbn="", isbn13="", title="No ISBN Book")]
        first = self.run_rows(rows)
        second = self.run_rows(rows)
        self.assertEqual(self.outcomes(first), ["CREATED"] * 3)
        self.assertEqual(self.outcomes(second), ["UNCHANGED"] * 3)
        self.assertEqual(second.previous_import, first.import_id)
        self.assertEqual(len(self.query("SELECT * FROM publications")), 3)

    def test_27_corrected_rejected_rows_can_be_reprocessed(self):
        first = self.run_rows([book(title=""), book(**OTHER)])
        self.assertEqual(self.outcomes(first), ["REJECTED", "CREATED"])
        fixed = self.run_rows([book(), book(goodreads_book_id="12", isbn="439554934", isbn13="", title="Copy")],
                              reprocess_of=first.import_id)
        self.assertEqual(self.outcomes(fixed), ["CREATED", "REJECTED"])   # still goes through duplicate detection
        self.assertEqual(self.codes(fixed, 1), ["isbn_in_use"])
        resolved = self.query("SELECT resolved_by_import FROM rejected_rows WHERE import_id = ?", first.import_id)
        self.assertEqual(resolved[0][0], fixed.import_id)
        self.assertEqual(self.query("SELECT reprocess_of FROM imports WHERE import_id = ?", fixed.import_id)[0][0], first.import_id)

    def test_28_inventory_protection(self):
        self.skipTest("Not applicable: goodbooks-10k has no physical-copy data, so no inventory is created at all")


class Reporting(ImportTestCase):
    def test_29_report_reconciles_and_status(self):
        s = self.run_rows([book(), book(**OTHER), book(goodreads_book_id="60", title=""), book(goodreads_book_id="61", isbn="", isbn13="", title="X")])
        self.assertEqual(len(s.rows), sum(s.count(o) for o in ("CREATED", "UPDATED", "UNCHANGED", "REJECTED")))
        self.assertEqual((s.count("CREATED"), s.count("REJECTED"), s.warned), (3, 1, 1))
        self.assertEqual(s.status, "COMPLETED WITH ISSUES")
        md = s.report_paths["report"].read_text(encoding="utf-8")
        self.assertIn("4 rows = 3 created + 0 updated + 0 unchanged + 1 rejected — adds up", md)
        self.assertIn("missing_title", md)
        issues = read_csv(s.report_paths["issues"])
        self.assertEqual({i["problem"] for i in issues}, {"missing_title", "no_usable_isbn"})
        self.assertTrue(all(i["recommended_action"] and i["reason"] and i["row_number"] for i in issues))

    def test_missing_column_fails_and_saves_nothing(self):
        s = self.run_rows([book()], header=[h for h in HEADER if h != "isbn13"])
        self.assertEqual(s.status, "FAILED")
        self.assertIn("isbn13", s.note)
        self.assertEqual(self.query("SELECT count(*) FROM publications")[0][0], 0)
        self.assertEqual(self.query("SELECT status FROM imports")[0][0], "FAILED")
        self.assertIn("Nothing from this file was saved", s.report_paths["report"].read_text(encoding="utf-8"))

    def test_failed_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):     # keep the expected "FAILED" message out of test output
            code = import_books.main([str(self.dir / "nope.csv"), "--db", str(self.db), "--reports", str(self.dir / "r")])
        self.assertEqual(code, 2)

    def test_30_audit_log_records_repairs_and_creation(self):
        s = self.run_rows([book()])
        rows = self.query("SELECT field, original_value, new_value, actor, import_id, source_file FROM audit_log ORDER BY id")
        fields = {r["field"]: (r["original_value"], r["new_value"]) for r in rows}
        self.assertEqual(fields["isbn"], ("439023483", "0439023483"))
        self.assertEqual(fields["isbn13"], ("9.78043902348e+12", "9780439023481"))
        self.assertEqual(fields["original_publication_year"], ("2008.0", "2008"))
        self.assertIn("*", fields)                                   # creation itself
        self.assertTrue(all(r["actor"] == "automatic" and r["import_id"] == s.import_id and r["source_file"] for r in rows))


@unittest.skipUnless((ROOT / "books.csv").exists() and (ROOT / "books-batch2.csv").exists(), "data files not present")
class RealData(ImportTestCase):
    def test_batch2_after_books_creates_nothing_and_rerun_is_idempotent(self):
        first = run_import(ROOT / "books.csv", self.db, self.dir / "r", now=lambda: NOW)
        self.assertEqual((first.count("CREATED"), first.count("REJECTED"), first.status), (10000, 0, "COMPLETED WITH ISSUES"))
        batch2 = run_import(ROOT / "books-batch2.csv", self.db, self.dir / "r", now=lambda: NOW)
        self.assertEqual((batch2.count("UNCHANGED"), batch2.count("CREATED")), (200, 0))
        again = run_import(ROOT / "books.csv", self.db, self.dir / "r", now=lambda: NOW)
        self.assertEqual(again.count("UNCHANGED"), 10000)
        self.assertEqual(self.query("SELECT count(*) FROM publications")[0][0], 10000)
        # Spot checks against data-validation.md
        rows = {r["goodreads_book_id"]: r for r in self.query("SELECT goodreads_book_id, isbn13, isbn10 FROM publications")}
        self.assertEqual(rows[2767052]["isbn13"], "9780439023481")    # book 1: zero restored, ISBN-13 rebuilt
        self.assertIsNone(rows[15926]["isbn13"])                       # book 622: columns disagree


if __name__ == "__main__":
    unittest.main()
