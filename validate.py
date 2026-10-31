"""Row-level rules: turn one raw CSV row into a cleaned record, plus the
repairs made, the warnings raised, or the reason it is rejected.

Pure functions only (no database); the rules are documented in rules.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import isbn as isbnlib
from isbn import Repair

REQUIRED_COLUMNS = ("goodreads_book_id", "title", "authors", "original_publication_year", "isbn", "isbn13")

# Fields that describe *which* book this is. Filling a blank one is an
# update; changing a filled one needs a person (see rules.md section 3).
IDENTIFYING_FIELDS = ("title", "original_title", "authors", "publication_year", "work_id", "language_code", "isbn13", "isbn10")

# Fields that change night to night and don't identify the book: overwritten,
# with every change written to the audit log.
REFRESHABLE_FIELDS = (
    "book_id", "best_book_id", "books_count", "average_rating", "ratings_count",
    "work_ratings_count", "work_text_reviews_count", "ratings_1", "ratings_2",
    "ratings_3", "ratings_4", "ratings_5", "image_url", "small_image_url",
)

# Text fields where runs of whitespace are collapsed (others are only stripped).
_COLLAPSE_WHITESPACE = ("title", "original_title", "authors")


@dataclass(frozen=True)
class IssueType:
    action: str          # REJECT / LOAD WITH WARNING
    reason: str          # why this action was taken
    recommended: str     # what the librarian should do


ISSUE_TYPES = {
    "missing_id": IssueType("REJECT", "Without a goodreads_book_id the book can't be identified, so loading it could create a duplicate.", "Add the Goodreads book ID to the source row and re-import it."),
    "invalid_id": IssueType("REJECT", "goodreads_book_id must be a positive whole number; the book can't be identified otherwise.", "Correct the Goodreads book ID in the source row and re-import it."),
    "missing_title": IssueType("REJECT", "A book can't be cataloged without a title.", "Add the title to the source row and re-import it."),
    "isbn_in_use": IssueType("REJECT", "This ISBN already belongs to a different book in the catalog; one ISBN can't identify two publications.", "Check which book the ISBN really belongs to, then correct the source or the catalog."),
    "conflicts_existing": IssueType("REJECT", "Incoming values conflict with the existing catalog record; nothing was changed so trusted data isn't overwritten.", "Compare the old and new values and decide which is right; update the catalog or the source manually."),
    "missing_author": IssueType("LOAD WITH WARNING", "Author isn't needed to identify the book; it was left blank, not guessed.", "Add the author if known; the next import will fill it in."),
    "missing_year": IssueType("LOAD WITH WARNING", "Publication year was left blank, not guessed.", "Add the year if known; the next import will fill it in."),
    "invalid_year": IssueType("LOAD WITH WARNING", "The year isn't a whole-number year, so that field wasn't stored; the rest of the row was loaded.", "Correct the year in the source row."),
    "future_year": IssueType("LOAD WITH WARNING", "The year is later than the import date; it was kept as given.", "Check whether the year is a typo or the book is not yet published."),
    "invalid_work_id": IssueType("LOAD WITH WARNING", "work_id isn't a whole number, so that field wasn't stored.", "Correct the work_id in the source row."),
    "isbn10_invalid": IssueType("LOAD WITH WARNING", "The ISBN-10 fails the ISBN rules; digits are never changed to make it pass.", "Check the ISBN printed on the book and correct the source row."),
    "no_usable_isbn": IssueType("LOAD WITH WARNING", "The book was loaded and identified by its Goodreads ID, but it has no ISBN that passes validation.", "Look up the ISBN if the book has one (ebook-only titles may not)."),
    "isbn_conflict": IssueType("LOAD WITH WARNING", "The isbn and isbn13 columns point to different publications, so neither was stored as the book's ISBN.", "Decide which edition this record describes and correct the source row."),
    "possible_duplicate": IssueType("LOAD WITH WARNING", "No usable ISBN, and another book has the same title and author; they were not merged.", "Check whether the two records are the same publication."),
}

# Issue codes that also create a manual-review item.
REVIEW_CODES = {"isbn_in_use", "conflicts_existing", "isbn_conflict", "possible_duplicate"}


@dataclass
class Issue:
    code: str
    field: str
    detail: str


@dataclass
class FieldRepair:
    field: str
    original: str
    new: str
    reason: str


@dataclass
class RowResult:
    row_number: int
    raw: dict
    record: dict | None = None            # cleaned values; None when rejected
    rejection: Issue | None = None
    warnings: list[Issue] = field(default_factory=list)
    repairs: list[FieldRepair] = field(default_factory=list)

    @property
    def rejected(self) -> bool:
        return self.rejection is not None


def _clean_text(name: str, raw: str | None, result: RowResult) -> str | None:
    if raw is None:
        return None
    new = re.sub(r"\s+", " ", raw).strip() if name in _COLLAPSE_WHITESPACE else raw.strip()
    if new != raw:
        result.repairs.append(FieldRepair(name, raw, new, "removed extra whitespace"))
    return new or None


def _parse_year(text: str | None, today: date, result: RowResult) -> int | None:
    if text is None:
        result.warnings.append(Issue("missing_year", "original_publication_year", "publication year is blank"))
        return None
    m = re.fullmatch(r"(-?\d+)(\.0+)?", text)
    if not m or int(m.group(1)) == 0:
        result.warnings.append(Issue("invalid_year", "original_publication_year", f"'{text}' is not a valid year"))
        return None
    year = int(m.group(1))
    if m.group(2):
        result.repairs.append(FieldRepair("original_publication_year", text, str(year), "removed '.0' from a whole-number year"))
    if year > today.year:
        result.warnings.append(Issue("future_year", "original_publication_year", f"{year} is later than the import date ({today.isoformat()})"))
    return year


def _resolve_isbns(raw10: str | None, raw13: str | None, result: RowResult) -> tuple[str | None, str | None]:
    """Decide the book's ISBN-13 (and ISBN-10 alternate) from the two columns."""
    r10 = isbnlib.parse_isbn10(raw10)
    r13 = isbnlib.parse_isbn13(raw13)
    for col, r, raw in (("isbn", r10, raw10), ("isbn13", r13, raw13)):
        for rep in r.repairs:
            result.repairs.append(FieldRepair(col, rep.original, rep.new, rep.reason))

    isbn10 = r10.value
    from10 = isbnlib.isbn10_to_isbn13(isbn10) if isbn10 else None

    if r10.status == "invalid":
        result.warnings.append(Issue("isbn10_invalid", "isbn", f"'{raw10}': {r10.problem}"))

    if r13.status == "valid":
        if from10 and from10 != r13.value:
            result.warnings.append(Issue("isbn_conflict", "isbn13", f"isbn '{raw10}' is ISBN-13 {from10}, but isbn13 is {r13.value}"))
            return None, None
        return r13.value, isbn10

    if r13.status == "lost_precision" and from10:
        if isbnlib.matches_lost_precision(r13.approx, from10):
            result.repairs.append(FieldRepair("isbn13", raw13, from10, "isbn13 had lost its last digit(s); rebuilt from the row's valid ISBN-10, which matches the rounded value"))
            return from10, isbn10
        result.warnings.append(Issue("isbn_conflict", "isbn13", f"isbn '{raw10}' is ISBN-13 {from10}, which doesn't match isbn13 '{raw13}'"))
        return None, None

    if from10:
        # isbn13 is empty, not an ISBN, or unusable: the ISBN-10 converts exactly.
        return from10, isbn10

    reasons = []
    if r10.status != "empty":
        reasons.append(f"isbn '{raw10}': {r10.problem}")
    if r13.status != "empty":
        reasons.append(f"isbn13 '{raw13}': {r13.problem}")
    result.warnings.append(Issue("no_usable_isbn", "isbn13", "; ".join(reasons) or "both ISBN columns are empty"))
    return None, None


def validate_row(raw: dict, row_number: int, today: date) -> RowResult:
    """Apply the rules in rules.md to one CSV row (keys = column names)."""
    result = RowResult(row_number, raw)
    get = lambda name: _clean_text(name, raw.get(name), result)  # noqa: E731

    gid = get("goodreads_book_id")
    if gid is None:
        result.rejection = Issue("missing_id", "goodreads_book_id", "goodreads_book_id is blank")
        return result
    if not re.fullmatch(r"\d+", gid) or int(gid) == 0:
        result.rejection = Issue("invalid_id", "goodreads_book_id", f"'{gid}' is not a positive whole number")
        return result

    title = get("title")
    if title is None:
        result.rejection = Issue("missing_title", "title", "title is blank or only spaces")
        return result

    authors = get("authors")
    if authors is None:
        result.warnings.append(Issue("missing_author", "authors", "author is blank"))

    year = _parse_year(get("original_publication_year"), today, result)

    work_id = get("work_id")
    if work_id is not None and not re.fullmatch(r"\d+", work_id):
        result.warnings.append(Issue("invalid_work_id", "work_id", f"'{work_id}' is not a whole number"))
        work_id = None

    isbn13, isbn10 = _resolve_isbns(raw.get("isbn"), raw.get("isbn13"), result)

    result.record = {
        "goodreads_book_id": int(gid),
        "title": title,
        "original_title": get("original_title"),
        "authors": authors,
        "publication_year": year,
        "work_id": int(work_id) if work_id else None,
        "language_code": get("language_code"),
        "isbn13": isbn13,
        "isbn10": isbn10,
        "source_isbn": raw.get("isbn"),
        "source_isbn13": raw.get("isbn13"),
        **{name: get(name) for name in REFRESHABLE_FIELDS},
    }
    return result
