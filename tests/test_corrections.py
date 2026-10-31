"""Approved corrections (corrections.py via ingest.py) and the Open Library lookup
(lookup_isbns.py, with a fake network). rules.md section 5.
Run: py -3.13 -m unittest discover tests"""
import csv
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ingest
import lookup_isbns
from test_import import HEADER, OTHER, book

NOW = datetime(2026, 10, 31, 2, 0, 0)
CORR_HEADER = ["goodreads_book_id", "title", "approved_isbn13", "approved_year", "approved_no_isbn_reason", "approved_by", "source", "notes"]
NO_ISBN = dict(isbn="", isbn13="")


def approved(gid="2767052", **kw):
    row = {"goodreads_book_id": gid, "title": "x", "approved_by": "Abigail", "source": "Open Library"}
    row.update(kw)
    return row


class CorrectionsTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db, self.log, self.corr = self.dir / "books.db", self.dir / "log.json", self.dir / "isbn-corrections.csv"
        self.n = 0

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_corrections(self, rows, header=CORR_HEADER, encoding="utf-8-sig"):
        with open(self.corr, "w", encoding=encoding, newline="") as fh:
            w = csv.DictWriter(fh, header, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)

    def run_rows(self, rows):
        self.n += 1
        path = self.dir / f"file{self.n}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, HEADER, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return ingest.ingest(path, self.db, self.log, now=lambda: NOW, corrections_path=self.corr)

    def book_row(self, gid=2767052):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute("SELECT * FROM books WHERE goodreads_book_id = ?", (gid,)).fetchone()
        finally:
            conn.close()

    @staticmethod
    def problems(e):
        return sorted(w["problem"] for w in e["warnings"])


class ApplyingCorrections(CorrectionsTestCase):
    def test_approved_isbn_fills_missing_isbn_and_clears_warning(self):
        self.write_corrections([approved(approved_isbn13="ISBN 9780439023481")])
        e = self.run_rows([book(**NO_ISBN)])
        self.assertEqual((e["status"], e["warnings"], e["counts"]["corrected"]), ("SUCCESS", [], 1))
        b = self.book_row()
        self.assertEqual((b["isbn13"], b["isbn13_source"]), ("9780439023481", "Open Library; approved by Abigail"))
        conn = sqlite3.connect(self.db)
        audit = conn.execute("SELECT new_value, reason FROM audit_log WHERE field = 'isbn13'").fetchone()
        conn.close()
        self.assertEqual(audit[0], "9780439023481")
        self.assertIn("approved correction", audit[1])

    def test_approved_isbn10_is_converted(self):
        self.write_corrections([approved(approved_isbn13="0-439-02348-3")])
        self.run_rows([book(**NO_ISBN)])
        self.assertEqual((self.book_row()["isbn13"], self.book_row()["isbn10"]), ("9780439023481", "0439023483"))

    def test_correction_fixes_bad_check_digit_and_conflict(self):
        self.write_corrections([approved(approved_isbn13="ISBN 9780439023481"),
                                approved(gid="3", approved_isbn13="ISBN 9780439554930")])
        e = self.run_rows([book(isbn="1847386823", isbn13=""), book(**{**OTHER, "isbn": "446612707", "isbn13": "9.78055381395e+12"})])
        self.assertEqual(e["warnings"], [])
        self.assertEqual(e["counts"]["corrected"], 2)

    def test_approved_year_fills_missing_year(self):
        self.write_corrections([approved(approved_year="2008")])
        e = self.run_rows([book(original_publication_year="")])
        self.assertEqual(e["warnings"], [])
        self.assertEqual((self.book_row()["publication_year"], self.book_row()["publication_year_source"]),
                         (2008, "Open Library; approved by Abigail"))

    def test_ebook_needs_no_isbn_and_is_a_note_not_a_warning(self):
        self.write_corrections([approved(approved_no_isbn_reason="ebook"), approved(gid="3", approved_no_isbn_reason="Self Published")])
        e = self.run_rows([book(**NO_ISBN), book(**{**OTHER, **NO_ISBN})])
        self.assertEqual((e["status"], e["warnings"]), ("SUCCESS", []))
        self.assertEqual(e["counts"]["accepted_without_isbn"], 2)
        self.assertEqual([n["detail"] for n in e["notes"]],
                         ["accepted without ISBN: ebook (approved by Abigail)", "accepted without ISBN: self-published (approved by Abigail)"])
        self.assertEqual(self.book_row()["no_isbn_reason"], "ebook; approved by Abigail")

    def test_ebook_reason_ignored_when_book_has_a_valid_isbn(self):
        self.write_corrections([approved(approved_no_isbn_reason="ebook")])
        e = self.run_rows([book()])
        self.assertEqual((e["notes"], e["counts"]["corrected"]), ([], 0))

    def test_correction_never_replaces_a_valid_value(self):
        self.write_corrections([approved(approved_isbn13="ISBN 9780439655484", approved_year="1999")])
        e = self.run_rows([book()])
        self.assertEqual(self.problems(e), ["correction_not_applied", "correction_not_applied"])
        self.assertEqual((self.book_row()["isbn13"], self.book_row()["publication_year"]), ("9780439023481", 2008))

    def test_approved_isbn_belonging_to_another_book_is_rejected(self):
        self.run_rows([book()])
        self.write_corrections([approved(gid="3", approved_isbn13="ISBN 9780439023481")])
        e = self.run_rows([book(**{**OTHER, **NO_ISBN})])
        self.assertEqual([r["problem"] for r in e["not_loaded"]], ["isbn_in_use"])

    def test_rerun_with_correction_updates_once_then_skips(self):
        self.run_rows([book(**NO_ISBN)])
        self.write_corrections([approved(approved_isbn13="ISBN 9780439023481")])
        second, third = self.run_rows([book(**NO_ISBN)]), self.run_rows([book(**NO_ISBN)])
        self.assertEqual((second["counts"]["updated"], third["counts"]["skipped_existing"]), (1, 1))
        self.assertEqual(self.book_row()["isbn13"], "9780439023481")


class UnusableCorrections(CorrectionsTestCase):
    def test_excel_mangled_isbn_is_not_used_and_explained(self):
        self.write_corrections([approved(approved_isbn13="9.78044E+12")])
        e = self.run_rows([book(**NO_ISBN)])
        self.assertEqual(self.problems(e), ["correction_invalid", "no_usable_isbn"])
        self.assertIn("Excel", e["corrections"]["unusable"][0]["problem"])
        self.assertIsNone(self.book_row()["isbn13"])

    def test_not_approved_is_ignored(self):
        self.write_corrections([approved(approved_isbn13="ISBN 9780439023481", approved_by="")])
        e = self.run_rows([book(**NO_ISBN)])
        self.assertEqual(self.problems(e), ["no_usable_isbn"])
        self.assertEqual((e["corrections"]["approved"], e["corrections"]["unusable"]), (0, []))

    def test_two_corrections_for_one_book_are_not_used(self):
        self.write_corrections([approved(approved_isbn13="ISBN 9780439023481"), approved(approved_isbn13="ISBN 9780439655484")])
        e = self.run_rows([book(**NO_ISBN)])
        self.assertEqual(self.problems(e), ["correction_invalid", "no_usable_isbn"])

    def test_bad_reason_and_year(self):
        self.write_corrections([approved(approved_no_isbn_reason="audiobook", approved_year="20o8")])
        e = self.run_rows([book(**NO_ISBN)])
        self.assertIn("correction_invalid", self.problems(e))
        problem = e["corrections"]["unusable"][0]["problem"]
        self.assertIn("ebook", problem)
        self.assertIn("year", problem)

    def test_missing_column_fails_the_run(self):
        self.write_corrections([approved()], header=[h for h in CORR_HEADER if h != "approved_by"])
        e = self.run_rows([book()])
        self.assertEqual(e["status"], "FAILED")
        self.assertIn("approved_by", e["error"])
        self.assertIsNone(self.book_row())

    def test_excel_plain_csv_encoding_is_read(self):
        self.write_corrections([approved(approved_isbn13="ISBN 9780439023481", approved_by="Zoë")], encoding="cp1252")
        self.run_rows([book(**NO_ISBN)])
        self.assertEqual(self.book_row()["isbn13_source"], "Open Library; approved by Zoë")

    def test_no_corrections_file_is_fine(self):
        e = self.run_rows([book()])
        self.assertEqual((e["status"], e["corrections"]["file"]), ("SUCCESS", None))


class Lookup(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.csv, self.out, self.cache = self.dir / "books.csv", self.dir / "s.csv", self.dir / "cache.json"
        with open(self.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, HEADER, extrasaction="ignore")
            w.writeheader()
            w.writerows([
                book(),                                                                     # fine: not looked up
                book(goodreads_book_id="10", title="Found Book (Series, #1)", original_title="", **NO_ISBN),
                book(goodreads_book_id="11", title="Missing Book", original_title="", authors="Nobody, Else", **NO_ISBN),
                book(goodreads_book_id="12", title="Ebook Only", original_title="", isbn="", isbn13="2.94001623192e+12"),
                book(goodreads_book_id="13", title="No Year", original_title="", original_publication_year=""),
            ])
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def fake(self, url):
        self.calls.append(url)
        if "Missing" in url:
            return {"numFound": 0, "docs": []}
        if "Ebook" in url:
            return {"numFound": 1, "docs": [{"key": "/works/OL2W", "title": "Ebook Only", "format": ["ebook", "E-book"],
                                             "publisher": ["CreateSpace Independent Publishing Platform", "Independently published"]}]}
        return {"numFound": 2, "docs": [{"key": "/works/OL1W", "title": "Found Book", "author_name": ["Suzanne Collins"],
                                         "first_publish_year": 2008, "publisher": ["Scholastic", "CreateSpace"], "format": ["ebook", "Paperback"],
                                         "isbn": ["9788576845898", "9780439023481", "0439023483", "9781405512220", "junk"]}]}

    def run_lookup(self, fetch=None):
        return lookup_isbns.run(self.csv, self.out, self.cache, self.dir / "none.db", delay=0, fetch=fetch or self.fake,
                                today=date(2026, 10, 31), progress=lambda _: None)

    def rows(self):
        with open(self.out, encoding="utf-8-sig", newline="") as fh:
            return {r["goodreads_book_id"]: r for r in csv.DictReader(fh)}

    def test_only_books_with_isbn_or_year_warnings_are_looked_up(self):
        s = self.run_lookup()
        self.assertEqual((s["books"], s["found"], s["not_found"], s["errors"]), (4, 3, 1, 0))
        self.assertEqual(set(self.rows()), {"10", "11", "12", "13"})

    def test_suggestions_are_text_isbns_english_first_and_need_approval(self):
        self.run_lookup()
        r = self.rows()["10"]
        self.assertEqual(r["suggested_isbn13s"], "ISBN 9780439023481; ISBN 9781405512220; ISBN 9788576845898")
        self.assertEqual((r["suggested_year"], r["source"], r["approved_isbn13"], r["approved_by"]), ("2008", "Open Library", "", ""))
        self.assertIn("title=Found+Book&", self.calls[0])                 # series suffix removed
        self.assertEqual(r["format_hint"], "")                            # mixed formats/publishers: no hint

    def test_hints_and_not_found(self):
        self.run_lookup()
        rows = self.rows()
        self.assertEqual(rows["11"]["lookup_result"], "not found on Open Library")
        self.assertIn("author=Nobody&", [c for c in self.calls if "Missing" in c][0])   # first author only
        hint = rows["12"]["format_hint"]
        for part in ("Nook ebook code", "only ebook formats", "every publisher looks self-published"):
            self.assertIn(part, hint)

    def test_answers_are_cached_and_errors_are_not(self):
        self.run_lookup()
        first = len(self.calls)
        self.run_lookup()
        self.assertEqual(len(self.calls), first)                          # all from cache the second time

        self.cache.unlink()
        def failing(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        s = self.run_lookup(fetch=failing)
        self.assertEqual(s["errors"], 4)
        self.assertEqual(json.loads(self.cache.read_text(encoding="utf-8")), {})

    def test_isbn_already_used_by_another_book_is_marked(self):
        db = self.dir / "books.db"
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE books (goodreads_book_id INTEGER, isbn13 TEXT)")
        conn.execute("INSERT INTO books VALUES (2767052, '9780439023481')")
        conn.commit()
        conn.close()
        lookup_isbns.run(self.csv, self.out, self.cache, db, delay=0, fetch=self.fake, today=date(2026, 10, 31), progress=lambda _: None)
        self.assertIn("ISBN 9780439023481 (already used by goodreads_book_id 2767052)", self.rows()["10"]["suggested_isbn13s"])


if __name__ == "__main__":
    unittest.main()
