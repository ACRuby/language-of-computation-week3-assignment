"""ISBN rules (requirement tests 1-10). Run: py -3.13 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from isbn import (isbn10_to_isbn13, matches_lost_precision, parse_isbn10,
                  parse_isbn13)


class Isbn10(unittest.TestCase):
    def test_01_valid_isbn10(self):
        r = parse_isbn10("0439023483")
        self.assertEqual((r.status, r.value, r.repairs), ("valid", "0439023483", []))

    def test_03_valid_x_check_character(self):
        self.assertEqual(parse_isbn10("043965548X").value, "043965548X")

    def test_04_lowercase_x_is_repaired(self):
        r = parse_isbn10("043965548x")
        self.assertEqual(r.value, "043965548X")
        self.assertEqual(len(r.repairs), 1)

    def test_x_only_allowed_last(self):
        self.assertEqual(parse_isbn10("04396554X8").problem, "invalid characters")

    def test_05_06_spaces_hyphens_and_label_removed(self):
        for raw in ("0 439 02348 3", "0-439-02348-3", "ISBN 0-439-02348-3", " 0439023483 "):
            with self.subTest(raw=raw):
                self.assertEqual(parse_isbn10(raw).value, "0439023483")

    def test_07_wrong_length(self):
        self.assertIn("wrong length", parse_isbn10("04390234831").problem)
        self.assertIn("wrong length", parse_isbn10("12345").problem)  # too many zeros missing to restore

    def test_08_invalid_characters(self):
        self.assertEqual(parse_isbn10("ABC123").status, "invalid")
        self.assertEqual(parse_isbn10("04390.2348").problem, "invalid characters")

    def test_09_wrong_check_digit_is_not_changed(self):
        r = parse_isbn10("1847386823")
        self.assertEqual((r.status, r.value), ("invalid", None))
        self.assertIn("expected 2", r.problem)

    def test_leading_zeros_restored_when_checksum_confirms(self):
        self.assertEqual(parse_isbn10("439023483").value, "0439023483")
        self.assertEqual(parse_isbn10("61120081").value, "0061120081")
        self.assertEqual(parse_isbn10("7442912").value, "0007442912")

    def test_leading_zeros_not_restored_when_checksum_fails(self):
        r = parse_isbn10("385535144")      # book 1543: bad check digit after padding
        self.assertEqual((r.status, r.value), ("invalid", None))

    def test_too_short_is_never_padded(self):
        self.assertEqual(parse_isbn10("0").status, "invalid")   # 0000000000 would "pass"

    def test_11_missing(self):
        self.assertEqual(parse_isbn10("").status, "empty")
        self.assertEqual(parse_isbn10("   ").status, "empty")
        self.assertEqual(parse_isbn10(None).status, "empty")

    def test_conversion_to_isbn13(self):
        self.assertEqual(isbn10_to_isbn13("0439023483"), "9780439023481")
        self.assertEqual(isbn10_to_isbn13("043965548X"), "9780439655484")


class Isbn13(unittest.TestCase):
    def test_02_valid_isbn13(self):
        self.assertEqual(parse_isbn13("9780439023481").value, "9780439023481")
        self.assertEqual(parse_isbn13("9791032305690").value, "9791032305690")   # 979 prefix

    def test_05_06_formatting(self):
        self.assertEqual(parse_isbn13("978-0-439-02348-1").value, "9780439023481")
        self.assertEqual(parse_isbn13("ISBN 978 0 439 02348 1").value, "9780439023481")

    def test_07_wrong_length(self):
        self.assertIn("wrong length", parse_isbn13("978043902348").problem)
        self.assertIn("wrong length", parse_isbn13("97893806587.0").problem)   # book 1443, truncated

    def test_08_invalid_characters(self):
        self.assertEqual(parse_isbn13("978043902348X").problem, "invalid characters")

    def test_09_wrong_check_digit(self):
        r = parse_isbn13("9780439023482")
        self.assertEqual((r.status, r.value), ("invalid", None))

    def test_10_invalid_prefix(self):
        self.assertIn("prefix 977", parse_isbn13("9770439023481").problem)

    def test_scientific_notation_is_never_an_isbn(self):
        r = parse_isbn13("9.78043902348e+12")
        self.assertEqual((r.status, r.value), ("lost_precision", None))

    def test_nook_code_is_not_isbn(self):
        self.assertEqual(parse_isbn13("2.94001623192e+12").status, "not_isbn")

    def test_full_precision_decimal_is_rewritten_not_changed(self):
        r = parse_isbn13("9780439023481.0")
        self.assertEqual(r.value, "9780439023481")
        self.assertEqual(len(r.repairs), 1)

    def test_lost_precision_cross_check(self):
        self.assertTrue(matches_lost_precision("9.78043902348e+12", "9780439023481"))   # rounded down
        self.assertTrue(matches_lost_precision("9.78067978327e+12", "9780679783268"))   # rounded up (book 10)
        self.assertTrue(matches_lost_precision("9.7801401693e+12", "9780140169300"))    # trailing zeros trimmed
        self.assertFalse(matches_lost_precision("9.78055381395e+12", "9780446612708"))  # book 622: other edition


if __name__ == "__main__":
    unittest.main()
