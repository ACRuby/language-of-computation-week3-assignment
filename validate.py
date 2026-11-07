"""Row-level rules: turn one CSV row into the record to store, plus the
repairs made, the warnings raised, or the reason it is rejected.

Pure functions only (no database). The rules are in rules.md (the group's
agreed rules); ISBN rules are in isbn.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import isbn as isbnlib

# Every column of books.csv, in file order. All of them must be in the header
# (a missing one makes the run FAILED, rules.md section 4).
COLUMNS = (
    "book_id", "goodreads_book_id", "best_book_id", "work_id", "books_count", "isbn", "isbn13",
    "authors", "original_publication_year", "original_title", "title", "language_code",
    "average_rating", "ratings_count", "work_ratings_count", "work_text_reviews_count",
    "ratings_1", "ratings_2", "ratings_3", "ratings_4", "ratings_5", "image_url", "small_image_url",
)

# rules.md section 3 (Decision 4).
VOLATILE_FIELDS = (
    "average_rating", "ratings_count", "work_ratings_count", "work_text_reviews_count",
    "ratings_1", "ratings_2", "ratings_3", "ratings_4", "ratings_5", "books_count",
    "image_url", "small_image_url", "best_book_id", "book_id",
    "original_title",                     # in neither list; treated as volatile (rules.md section 5, note 7)
)
IDENTITY_FIELDS = ("title", "authors", "original_publication_year", "work_id", "language_code", "isbn", "isbn13")

# Rejection reasons (rules.md sections 1, 3 and 5).
STRUCTURAL_PARSE_ERROR = "structural-parse-error"
ISBN_COLLISION = "isbn-collision"
IDENTITY_FIELD_CONFLICT = "identity-field-conflict"
MISSING_GOODREADS_ID = "missing-goodreads-id"
INVALID_GOODREADS_ID = "invalid-goodreads-id"
REJECT_CODES = (STRUCTURAL_PARSE_ERROR, ISBN_COLLISION, IDENTITY_FIELD_CONFLICT, MISSING_GOODREADS_ID, INVALID_GOODREADS_ID)


@dataclass
class Warning:
    field: str
    raw_value: str
    reasons: list            # reason codes; stored comma-separated

    @property
    def reason(self) -> str:
        return ",".join(self.reasons)


@dataclass
class Rejection:
    reason: str
    detail: str


@dataclass
class RowResult:
    row_number: int
    raw: dict
    record: dict | None = None            # values to store; None when rejected
    rejection: Rejection | None = None
    warnings: list = field(default_factory=list)   # list of Warning
    repairs: list = field(default_factory=list)    # list of isbn.Repair

    @property
    def rejected(self) -> bool:
        return self.rejection is not None


def blank(value) -> bool:
    return value is None or not str(value).strip()


def normalize_title(title) -> str:
    """Decision 6: lowercase, strip punctuation and extra whitespace."""
    text = re.sub(r"[^\w\s]", "", (title or "").casefold())
    return " ".join(text.split())


def same_value(fld: str, old, new) -> bool:
    if fld == "title":
        return normalize_title(old) == normalize_title(new)
    return old == new


def validate_row(raw: dict, row_number: int) -> RowResult:
    """Apply rules.md to one parsed CSV row (keys = column names)."""
    result = RowResult(row_number, raw)

    gid = (raw.get("goodreads_book_id") or "").strip()
    if not gid:
        result.rejection = Rejection(MISSING_GOODREADS_ID, "goodreads_book_id is blank")
        return result
    if not re.fullmatch(r"\d+", gid) or int(gid) == 0:
        result.rejection = Rejection(INVALID_GOODREADS_ID, f"goodreads_book_id '{gid}' is not a positive whole number")
        return result

    # Every other field is passed through as given (no new validation, rules.md section 1).
    record = {c: (None if blank(raw.get(c)) else raw[c]) for c in COLUMNS}
    record["goodreads_book_id"] = gid

    res = isbnlib.resolve(raw.get("isbn"), raw.get("isbn13"))
    record["isbn"], record["isbn13"] = res.isbn, res.isbn13
    result.repairs = res.repairs
    for fld in ("isbn", "isbn13"):
        if fld in res.warnings:
            result.warnings.append(Warning(fld, raw.get(fld) or "", res.warnings[fld]))
    result.record = record
    return result
