"""ISBN cleaning, validation and conversion.

Pure functions only: nothing here reads files or touches the database, so
every rule can be tested on its own.

Sources (see implementation.md):
  * ISBN-13 rules: International ISBN Agency, "What is an ISBN?" and the
    ISBN Users' Manual, 7th edition (Appendix 1 check digit).
  * ISBN-10 rules and ISBN-10 -> ISBN-13 conversion: ISO 2108 (the
    International ISBN Agency's current manual covers ISBN-13 only).

The one rule that matters most: digits are never changed to make a check
digit pass. The only repairs are ones with exactly one possible answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# Formatting the ISBN manual says has "no lexical significance".
_LABEL = re.compile(r"^ISBN(?:-1[03])?:?", re.IGNORECASE)
_SEPARATORS = re.compile(r"[\s\-]")
_NUMBER = re.compile(r"\d+(?:\.\d*)?(?:[eE][+]?\d+)?")

# Dropped leading zeros are restored only when at most this many are missing.
# goodbooks-10k shows 1-3; restoring more would turn very short junk such as
# "0" into a "valid" ISBN (0000000000 passes the checksum).
MAX_RESTORED_ZEROS = 3


@dataclass
class Repair:
    original: str
    new: str
    reason: str


@dataclass
class IsbnResult:
    """Outcome of checking one ISBN cell.

    status is one of:
      valid           -- value is a usable ISBN (possibly after repairs)
      empty           -- cell was blank
      lost_precision  -- (ISBN-13 only) a 978/979 number written in
                         scientific notation, so digits are missing; the
                         text is kept in `approx` for cross-checking only
      not_isbn        -- (ISBN-13 only) a number that is not an ISBN at all
      invalid         -- fails ISBN rules; `problem` says which one
    """
    status: str
    value: str | None = None
    problem: str | None = None
    approx: str | None = None
    repairs: list[Repair] = field(default_factory=list)


def clean(raw: str) -> str:
    """Strip whitespace, a leading 'ISBN' label, spaces and hyphens; uppercase a final x."""
    s = _SEPARATORS.sub("", _LABEL.sub("", raw.strip()))
    if s.endswith("x"):
        s = s[:-1] + "X"
    return s


def isbn10_check_char(first9: str) -> str:
    total = sum((10 - i) * int(d) for i, d in enumerate(first9))
    check = (11 - total % 11) % 11
    return "X" if check == 10 else str(check)


def isbn13_check_digit(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def is_valid_isbn10(s: str) -> bool:
    return bool(re.fullmatch(r"\d{9}[\dX]", s)) and isbn10_check_char(s[:9]) == s[9]


def is_valid_isbn13(s: str) -> bool:
    return bool(re.fullmatch(r"97[89]\d{10}", s)) and isbn13_check_digit(s[:12]) == s[12]


def isbn10_to_isbn13(isbn10: str) -> str:
    """Convert a valid ISBN-10: prefix 978 and recalculate the check digit."""
    body = "978" + isbn10[:9]
    return body + isbn13_check_digit(body)


def _formatting_repair(raw: str, cleaned: str) -> list[Repair]:
    if cleaned == raw.strip():
        return []
    return [Repair(raw, cleaned, "removed formatting with no meaning (ISBN label, spaces, hyphens, lowercase x)")]


def parse_isbn10(raw: str | None) -> IsbnResult:
    if raw is None or not raw.strip():
        return IsbnResult("empty")
    s = clean(raw)
    repairs = _formatting_repair(raw, s)
    if not s or re.search(r"[^\dX]", s) or "X" in s[:-1]:
        return IsbnResult("invalid", problem="invalid characters", repairs=repairs)
    if len(s) > 10:
        return IsbnResult("invalid", problem=f"wrong length ({len(s)} characters, expected 10)", repairs=repairs)
    if len(s) == 10:
        if is_valid_isbn10(s):
            return IsbnResult("valid", value=s, repairs=repairs)
        return IsbnResult("invalid", problem=f"check digit is wrong (expected {isbn10_check_char(s[:9])})", repairs=repairs)
    missing = 10 - len(s)
    padded = "0" * missing + s
    if missing <= MAX_RESTORED_ZEROS:
        if is_valid_isbn10(padded):
            repairs.append(Repair(s, padded, f"restored {missing} dropped leading zero(s); only one answer is possible and the check digit confirms it"))
            return IsbnResult("valid", value=padded, repairs=repairs)
        return IsbnResult("invalid", problem=f"check digit is wrong even after restoring {missing} leading zero(s) (expected {isbn10_check_char(padded[:9])})", repairs=repairs)
    return IsbnResult("invalid", problem=f"wrong length ({len(s)} characters, expected 10)", repairs=repairs)


def _digits_shown(number_text: str) -> int:
    """Significant digits actually written in a number like '9.78043902348e+12'."""
    mantissa = re.split(r"[eE]", number_text)[0].replace(".", "").lstrip("0")
    return len(mantissa)


def parse_isbn13(raw: str | None) -> IsbnResult:
    if raw is None or not raw.strip():
        return IsbnResult("empty")
    s = clean(raw)
    repairs = _formatting_repair(raw, s)

    if not re.fullmatch(r"\d+", s) and _NUMBER.fullmatch(s):
        # Written as a decimal / scientific-notation number (the CSV went
        # through a float somewhere upstream).
        try:
            n = Decimal(s)
        except InvalidOperation:
            return IsbnResult("invalid", problem="invalid characters", repairs=repairs)
        if n != n.to_integral_value():
            return IsbnResult("not_isbn", problem="not a whole number", repairs=repairs)
        digits = str(int(n))
        if _digits_shown(s) < len(digits):
            # Some digits were rounded away; nothing can be recovered from here.
            if len(digits) == 13 and digits.startswith(("978", "979")):
                return IsbnResult("lost_precision", approx=s,
                                  problem="written in scientific notation; the last digit(s) were lost",
                                  repairs=repairs)
            return IsbnResult("not_isbn", problem=f"not an ISBN ({digits[:4]}... is not a 978/979 ISBN-13)", repairs=repairs)
        # Every digit is still present (e.g. '9780439023481.0'): rewriting it
        # as plain digits changes nothing.
        repairs.append(Repair(s, digits, "rewrote number format as plain digits; no digits changed"))
        s = digits

    if re.search(r"\D", s):
        return IsbnResult("invalid", problem="invalid characters", repairs=repairs)
    if len(s) != 13:
        return IsbnResult("invalid", problem=f"wrong length ({len(s)} digits, expected 13)", repairs=repairs)
    if not s.startswith(("978", "979")):
        return IsbnResult("invalid", problem=f"prefix {s[:3]} is not 978 or 979", repairs=repairs)
    if not is_valid_isbn13(s):
        return IsbnResult("invalid", problem=f"check digit is wrong (expected {isbn13_check_digit(s[:12])})", repairs=repairs)
    return IsbnResult("valid", value=s, repairs=repairs)


def matches_lost_precision(approx: str, isbn13: str) -> bool:
    """True if `approx` (e.g. '9.78043902348e+12') is what `isbn13` looks
    like after being rounded to the digits shown. Used only as a cross-check,
    never as a source of digits."""
    shown = _digits_shown(approx)
    return float(approx) == float(f"{int(isbn13):.{shown}g}")
