"""isbn.py: every row of rules.md section 1 that is about an ISBN value.
Run: py -3.13 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import isbn
from isbn import resolve

HG10, HG13 = "0439023483", "9780439023481"        # The Hunger Games
HP10, HP13 = "043965548X", "9780439655484"        # ends in X


def full13(first12):
    return first12 + isbn.isbn13_check_digit(first12)


def codes(res):
    return [r.code for r in res.repairs]


class CheckDigits(unittest.TestCase):
    def test_known_isbns(self):
        self.assertTrue(isbn.is_valid_isbn10(HG10))
        self.assertTrue(isbn.is_valid_isbn10(HP10))
        self.assertTrue(isbn.is_valid_isbn13(HG13))
        self.assertFalse(isbn.is_valid_isbn10("0439023484"))
        self.assertEqual(isbn.isbn10_to_isbn13(HG10), HG13)
        self.assertEqual(isbn.isbn13_to_isbn10(HP13), HP10)


class Section1(unittest.TestCase):
    def test_already_valid_no_warning(self):
        res = resolve(HG10, HG13)
        self.assertEqual((res.isbn, res.isbn13, res.warnings, res.repairs), (HG10, HG13, {}, []))

    def test_hyphens_spaces_and_label_removed(self):
        res = resolve("ISBN 0-439-02348-3", "978 0 439 02348 1")
        self.assertEqual((res.isbn, res.isbn13), (HG10, HG13))
        self.assertEqual(codes(res), ["formatting-removed", "formatting-removed"])

    def test_leading_zeros_restored_only_if_checksum_passes(self):
        res = resolve("439023483", HG13)
        self.assertEqual(res.isbn, HG10)
        self.assertIn("leading-zeros-restored", codes(res))
        res = resolve("439023484", "")                   # padding still fails the checksum
        self.assertIsNone(res.isbn)
        self.assertEqual(res.warnings["isbn"], ["bad-checksum"])

    def test_too_many_missing_zeros_is_bad_length(self):
        self.assertEqual(resolve("123456", "").warnings["isbn"], ["bad-length"])

    def test_stripped_978_repair(self):
        # 9380658797: fails as an ISBN-10, but 978 + it is a valid ISBN-13 (row from books.csv)
        res = resolve("9380658797", "")
        self.assertEqual(res.isbn, "9380658796")
        self.assertEqual(res.isbn13, "9789380658797")
        self.assertIn("stripped-978-restored", codes(res))
        self.assertNotIn("isbn", res.warnings)

    def test_scientific_isbn13_rederived_from_valid_isbn(self):
        res = resolve(HG10, "9.78043902348e+12")
        self.assertEqual(res.isbn13, HG13)
        self.assertEqual(res.warnings, {})
        self.assertIn("isbn13-derived-from-isbn", codes(res))

    def test_scientific_isbn13_rederived_even_if_rounded_value_differs(self):
        # rules.md section 5, note 2: no cross-check against the rounded value
        res = resolve(HG10, "9.78111111111e+12")
        self.assertEqual(res.isbn13, HG13)

    def test_missing_counterpart_isbn_from_978_isbn13(self):
        res = resolve("", HP13)
        self.assertEqual(res.isbn, HP10)
        self.assertIn("isbn-derived-from-isbn13", codes(res))
        res = resolve("", "9780439655484.0")             # full precision written as a float
        self.assertEqual((res.isbn, res.isbn13), (HP10, HP13))
        self.assertIn("float-format-removed", codes(res))

    def test_979_isbn13_has_no_isbn10(self):
        v = full13("979103230569")
        res = resolve("", v)
        self.assertEqual((res.isbn, res.isbn13, res.warnings), (None, v, {}))

    def test_lost_digits_with_no_isbn(self):
        res = resolve("", "9.78043902348e+12")
        self.assertEqual((res.isbn, res.isbn13), (None, None))
        self.assertEqual(res.warnings["isbn13"], ["lost-precision", "no-usable-isbn"])

    def test_nook_code_lists_every_reason(self):
        res = resolve("", "2.94000000063e+12")
        self.assertEqual(res.warnings["isbn13"], ["lost-precision", "bad-prefix", "no-usable-isbn"])

    def test_wrong_check_digit(self):
        res = resolve("0439023484", "")
        self.assertEqual(res.warnings["isbn"], ["bad-checksum"])
        self.assertEqual(resolve("", "9780439023482").warnings["isbn13"], ["bad-checksum", "no-usable-isbn"])

    def test_invalid_characters(self):
        self.assertEqual(resolve("04390A3483", "").warnings["isbn"], ["bad-characters"])

    def test_wrong_length(self):
        res = resolve(HG10, "97893806587.0")
        self.assertEqual(res.warnings["isbn13"], ["bad-length"])
        self.assertEqual(res.isbn13, HG13)                # still filled from the valid isbn (note 11)

    def test_prefix_check(self):
        bad = full13("123456789012")                      # valid Mod-10, wrong prefix
        self.assertEqual(resolve("", bad).warnings["isbn13"], ["bad-prefix", "no-usable-isbn"])
        both = "1234567890123"
        self.assertEqual(resolve("", both).warnings["isbn13"][:2], ["bad-checksum", "bad-prefix"])

    def test_isbn13_in_isbn_column_is_moved(self):
        res = resolve(HG13, "")
        self.assertEqual((res.isbn, res.isbn13), (HG10, HG13))
        self.assertEqual(codes(res), ["isbn13-moved-from-isbn", "isbn-derived-from-isbn13"])

    def test_both_empty(self):
        self.assertEqual(resolve("", "").warnings, {"isbn13": ["no-usable-isbn"]})
        self.assertEqual(resolve(None, None).warnings, {"isbn13": ["no-usable-isbn"]})

    def test_unparseable(self):
        self.assertEqual(resolve("n/a", "???").warnings, {"isbn": ["unparseable"], "isbn13": ["unparseable", "no-usable-isbn"]})

    def test_columns_disagree(self):
        res = resolve(HG10, HP13)
        self.assertEqual((res.isbn, res.isbn13), (None, None))
        self.assertEqual(res.warnings, {"isbn": ["isbn-mismatch"], "isbn13": ["isbn-mismatch", "no-usable-isbn"]})


if __name__ == "__main__":
    unittest.main()
