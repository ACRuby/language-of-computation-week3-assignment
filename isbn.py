"""ISBN checks and repairs, following rules.md section 1 (the group's agreed rules).

Pure functions only: nothing here reads files or touches the database, so
every rule can be tested on its own.

Sources:
  * ISBN-13 rules: International ISBN Agency, ISBN Users' Manual, 7th edition
    (13 digits, prefix 978/979, Mod-10 check digit with weights 1 and 3).
  * ISBN-10 rules and ISBN-10 <-> ISBN-13 conversion: ISO 2108 (Mod-11 check
    character, weights 10..1, X = 10; ISBN-13 = 978 + first 9 digits + new
    check digit).

The governing principle (Decision 2): a repair is only allowed when it is
deterministic and checksum-verifiable. Digits are never changed to make a
check digit pass. A bad ISBN only nulls that one field and adds a warning.

Reason codes are listed in rules.md section 5.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Formatting the ISBN manual says has "no lexical significance".
_LABEL = re.compile(r"^ISBN(?:-1[03])?:?", re.IGNORECASE)
_SEPARATORS = re.compile(r"[\s\-]")
# A value written as a decimal or scientific-notation number (it went through a float upstream).
_NUMBER = re.compile(r"\d+(?:\.\d*)?(?:[eE][+]?\d+)?")

# Warnings
NO_USABLE_ISBN = "no-usable-isbn"
BAD_CHECKSUM = "bad-checksum"
BAD_PREFIX = "bad-prefix"
BAD_LENGTH = "bad-length"
BAD_CHARACTERS = "bad-characters"
UNPARSEABLE = "unparseable"
LOST_PRECISION = "lost-precision"
ISBN_MISMATCH = "isbn-mismatch"

# Repairs
FORMATTING_REMOVED = "formatting-removed"
FLOAT_FORMAT_REMOVED = "float-format-removed"
LEADING_ZEROS_RESTORED = "leading-zeros-restored"
STRIPPED_978_RESTORED = "stripped-978-restored"
ISBN13_MOVED_FROM_ISBN = "isbn13-moved-from-isbn"
ISBN13_DERIVED_FROM_ISBN = "isbn13-derived-from-isbn"
ISBN_DERIVED_FROM_ISBN13 = "isbn-derived-from-isbn13"

WARNING_CODES = (NO_USABLE_ISBN, BAD_CHECKSUM, BAD_PREFIX, BAD_LENGTH, BAD_CHARACTERS,
                 UNPARSEABLE, LOST_PRECISION, ISBN_MISMATCH)
REPAIR_CODES = (FORMATTING_REMOVED, FLOAT_FORMAT_REMOVED, LEADING_ZEROS_RESTORED, STRIPPED_978_RESTORED,
                ISBN13_MOVED_FROM_ISBN, ISBN13_DERIVED_FROM_ISBN, ISBN_DERIVED_FROM_ISBN13)


@dataclass
class Repair:
    field: str        # "isbn" or "isbn13"
    code: str
    original: str
    new: str


@dataclass
class Resolved:
    """The ISBNs to store for one row, plus what was repaired and what is warned."""
    isbn: str | None = None
    isbn13: str | None = None
    warnings: dict = field(default_factory=dict)   # field -> list of reason codes
    repairs: list = field(default_factory=list)    # list of Repair


# --- check digits and conversion ---------------------------------------------
def clean(raw: str) -> str:
    """Strip whitespace, a leading 'ISBN' label, spaces and hyphens; uppercase a final x."""
    s = _SEPARATORS.sub("", _LABEL.sub("", raw.strip()))
    return s[:-1] + "X" if s.endswith("x") else s


def isbn10_check_char(first9: str) -> str:
    total = sum((10 - i) * int(d) for i, d in enumerate(first9))
    c = (11 - total % 11) % 11
    return "X" if c == 10 else str(c)


def isbn13_check_digit(first12: str) -> str:
    total = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def is_valid_isbn10(s: str) -> bool:
    return bool(re.fullmatch(r"\d{9}[\dX]", s)) and isbn10_check_char(s[:9]) == s[9]


def has_valid_mod10(s: str) -> bool:
    return bool(re.fullmatch(r"\d{13}", s)) and isbn13_check_digit(s[:12]) == s[12]


def is_valid_isbn13(s: str) -> bool:
    return has_valid_mod10(s) and s.startswith(("978", "979"))


def isbn10_to_isbn13(isbn10: str) -> str:
    first12 = "978" + isbn10[:9]
    return first12 + isbn13_check_digit(first12)


def isbn13_to_isbn10(isbn13: str) -> str:
    """Only 978 ISBN-13s have an ISBN-10 form."""
    first9 = isbn13[3:12]
    return first9 + isbn10_check_char(first9)


# --- one column at a time ----------------------------------------------------
def _reasons(s: str, expected_length: int) -> list[str]:
    """Why a cleaned value isn't a usable ISBN (may be more than one reason)."""
    if not re.search(r"\d", s):
        return [UNPARSEABLE]
    allowed = r"\d+X?" if expected_length == 10 else r"\d+"
    out = []
    if not re.fullmatch(allowed, s):
        out.append(BAD_CHARACTERS)
    if len(s) != expected_length:
        out.append(BAD_LENGTH)
    if expected_length == 13 and len(s) == 13 and s.isdigit():
        if not has_valid_mod10(s):
            out.append(BAD_CHECKSUM)
        if not s.startswith(("978", "979")):
            out.append(BAD_PREFIX)
    if expected_length == 10 and not out:
        out.append(BAD_CHECKSUM)
    return out


def check_isbn_column(raw: str | None):
    """The `isbn` (ISBN-10) column.

    Returns (isbn10, moved_isbn13, reasons, repairs). Repairs are only kept
    when the value ends up usable.
    """
    if raw is None or not raw.strip():
        return None, None, [], []
    s = clean(raw)
    repairs = [Repair("isbn", FORMATTING_REMOVED, raw, s)] if s != raw.strip() else []

    if is_valid_isbn13(s):                                   # an ISBN-13 sitting in the ISBN-10 column
        return None, s, [], repairs
    if len(s) == 10 and is_valid_isbn10(s):
        return s, None, [], repairs
    if len(s) == 10 and s.isdigit() and is_valid_isbn13("978" + s):
        fixed = s[:9] + isbn10_check_char(s[:9])           # the ISBN-13 proves the one right check digit
        return fixed, None, [], repairs + [Repair("isbn", STRIPPED_978_RESTORED, s, fixed)]
    if 7 <= len(s) <= 9 and re.fullmatch(r"\d+X?", s):
        padded = "0" * (10 - len(s)) + s
        if is_valid_isbn10(padded):
            return padded, None, [], repairs + [Repair("isbn", LEADING_ZEROS_RESTORED, s, padded)]
        return None, None, [BAD_CHECKSUM], []                # a leading-zero case whose checksum still fails
    return None, None, _reasons(s, 10), []


def _digits_shown(number_text: str) -> int:
    """Significant digits actually written in a number like '9.78043902348e+12'."""
    return len(re.split(r"[eE]", number_text)[0].replace(".", "").lstrip("0"))


def check_isbn13_column(raw: str | None):
    """The `isbn13` column. Returns (isbn13, reasons, repairs)."""
    if raw is None or not raw.strip():
        return None, [], []
    s = clean(raw)
    repairs = [Repair("isbn13", FORMATTING_REMOVED, raw, s)] if s != raw.strip() else []

    if not s.isdigit() and _NUMBER.fullmatch(s):
        try:
            n = Decimal(s)
        except InvalidOperation:
            return None, [BAD_CHARACTERS], []
        if n != n.to_integral_value():
            return None, [BAD_CHARACTERS], []
        digits = str(int(n))
        if _digits_shown(s) < len(digits):
            reasons = [LOST_PRECISION]                       # digits are permanently gone
            if len(digits) != 13:
                reasons.append(BAD_LENGTH)
            elif not digits.startswith(("978", "979")):
                reasons.append(BAD_PREFIX)
            return None, reasons, []
        repairs.append(Repair("isbn13", FLOAT_FORMAT_REMOVED, s, digits))
        s = digits

    if is_valid_isbn13(s):
        return s, [], repairs
    return None, _reasons(s, 13), []


# --- both columns together -----------------------------------------------------
def _add(warnings: dict, fld: str, code: str):
    warnings.setdefault(fld, [])
    if code not in warnings[fld]:
        warnings[fld].append(code)


def resolve(raw_isbn: str | None, raw_isbn13: str | None) -> Resolved:
    """Decide which ISBN-10 and ISBN-13 a row gets (rules.md sections 1 and 5)."""
    v10, moved, r10, rep10 = check_isbn_column(raw_isbn)
    v13, r13, rep13 = check_isbn13_column(raw_isbn13)
    out = Resolved(repairs=rep10 + rep13)
    if r10:
        out.warnings["isbn"] = list(r10)
    if r13:
        out.warnings["isbn13"] = list(r13)

    mismatch = False
    if moved:
        if v13 and v13 != moved:
            mismatch = True
        else:
            if not v13:
                out.repairs.append(Repair("isbn13", ISBN13_MOVED_FROM_ISBN, raw_isbn, moved))
                _drop(out.warnings, "isbn13", LOST_PRECISION)
            v13 = moved
    elif v10 and v13 and isbn10_to_isbn13(v10) != v13:
        mismatch = True

    if mismatch:
        _add(out.warnings, "isbn", ISBN_MISMATCH)
        _add(out.warnings, "isbn13", ISBN_MISMATCH)
        out.repairs = []
        v10 = v13 = None
    else:
        if v10 and not v13:
            v13 = isbn10_to_isbn13(v10)
            out.repairs.append(Repair("isbn13", ISBN13_DERIVED_FROM_ISBN, raw_isbn13 or "", v13))
            _drop(out.warnings, "isbn13", LOST_PRECISION)    # section 1: lost precision + valid isbn is a repair
        if v13 and not v10 and v13.startswith("978"):
            v10 = isbn13_to_isbn10(v13)
            out.repairs.append(Repair("isbn", ISBN_DERIVED_FROM_ISBN13, raw_isbn or "", v10))

    if not v10 and not v13:
        _add(out.warnings, "isbn13", NO_USABLE_ISBN)
    out.isbn, out.isbn13 = v10, v13
    return out


def _drop(warnings: dict, fld: str, code: str):
    codes = warnings.get(fld, [])
    if code in codes:
        codes.remove(code)
        if not codes:
            del warnings[fld]
