"""Approved corrections: read isbn-corrections.csv and apply it to rows.

A person fills the approval columns of isbn-suggestions.csv (written by
lookup_isbns.py) and saves it as isbn-corrections.csv. No internet is used
here, so the same corrections always give the same result.
Rules: rules.md section 5.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import isbn as isbnlib
from validate import ISBN_WARNINGS, YEAR_WARNINGS, FieldRepair, Issue, RowResult

CORRECTIONS_PATH = "isbn-corrections.csv"
APPROVAL_COLUMNS = ("approved_isbn13", "approved_year", "approved_no_isbn_reason", "approved_by", "source")
REQUIRED_COLUMNS = ("goodreads_book_id",) + APPROVAL_COLUMNS
NO_ISBN_REASONS = {"ebook": "ebook", "selfpublished": "self-published"}


class CorrectionsError(Exception):
    """The corrections file can't be used at all (the run is FAILED)."""


@dataclass
class Correction:
    goodreads_book_id: int
    row_number: int                  # row in isbn-corrections.csv (header = row 1)
    isbn13: str | None = None
    isbn10: str | None = None
    year: int | None = None
    no_isbn_reason: str | None = None
    approved_by: str = ""
    source: str = ""
    problems: list = field(default_factory=list)   # why it can't be used; empty = usable

    @property
    def provenance(self):
        return f"{self.source or 'source not given'}; approved by {self.approved_by}"


@dataclass
class Corrections:
    usable: dict = field(default_factory=dict)      # goodreads_book_id -> Correction
    unusable: dict = field(default_factory=dict)    # goodreads_book_id -> Correction (with problems)
    unusable_no_id: list = field(default_factory=list)
    sha256: str | None = None
    file: str | None = None

    def summary(self):
        bad = list(self.unusable.values()) + self.unusable_no_id
        return {
            "file": self.file, "file_sha256": self.sha256, "approved": len(self.usable),
            "unusable": [{"row_number": c.row_number, "goodreads_book_id": c.goodreads_book_id or None,
                          "problem": "; ".join(c.problems)} for c in sorted(bad, key=lambda c: c.row_number)],
        }


def _parse_isbn(text):
    r13 = isbnlib.parse_isbn13(text)
    if r13.status == "valid":
        return r13.value, None, None
    r10 = isbnlib.parse_isbn10(text)
    if r10.status == "valid":
        return isbnlib.isbn10_to_isbn13(r10.value), r10.value, None
    hint = " (Excel probably turned it into a number; type it as 'ISBN 978...')" if "e+" in text.lower() else ""
    return None, None, f"approved_isbn13 '{text}' is not a valid ISBN: {r13.problem}{hint}"


def _parse_row(raw, row_number):
    get = lambda name: (raw.get(name) or "").strip()  # noqa: E731
    isbn_text, year_text, reason_text = get("approved_isbn13"), get("approved_year"), get("approved_no_isbn_reason")
    if not (isbn_text or year_text or reason_text) or not get("approved_by"):
        return None                                   # nothing approved: ignored (rules.md section 5, rule 3)
    gid = get("goodreads_book_id")
    c = Correction(int(gid) if re.fullmatch(r"\d+", gid) else 0, row_number,
                   approved_by=get("approved_by"), source=get("source"))
    if not c.goodreads_book_id:
        c.problems.append(f"goodreads_book_id '{gid}' is not a positive whole number")
    if isbn_text:
        c.isbn13, c.isbn10, problem = _parse_isbn(isbn_text)
        if problem:
            c.problems.append(problem)
    if year_text:
        m = re.fullmatch(r"(-?\d+)(\.0+)?", year_text)
        if m and int(m.group(1)) != 0:
            c.year = int(m.group(1))
        else:
            c.problems.append(f"approved_year '{year_text}' is not a valid year")
    if reason_text:
        key = re.sub(r"[\s\-_]", "", reason_text).casefold()
        if key in NO_ISBN_REASONS:
            c.no_isbn_reason = NO_ISBN_REASONS[key]
        else:
            c.problems.append(f"approved_no_isbn_reason '{reason_text}' must be 'ebook' or 'self-published'")
    return c


def _decode(data, name):
    for encoding in ("utf-8-sig", "cp1252"):          # Excel's plain "CSV" save uses cp1252
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CorrectionsError(f"{name} could not be read as text")


def load(path) -> Corrections:
    """A missing file means no corrections; an unreadable one raises CorrectionsError."""
    path = Path(path)
    if not path.exists():
        return Corrections()
    data = path.read_bytes()
    try:
        reader = csv.DictReader(_decode(data, path.name).splitlines())
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CorrectionsError(f"{path.name} is missing required column(s): {', '.join(missing)}")
        parsed = [c for i, raw in enumerate(reader) if (c := _parse_row(raw, i + 2))]
    except csv.Error as e:
        raise CorrectionsError(f"{path.name} could not be read as a CSV: {e}")

    out = Corrections(sha256=hashlib.sha256(data).hexdigest(), file=path.name)
    by_id = {}
    for c in parsed:
        if not c.goodreads_book_id:
            out.unusable_no_id.append(c)
        elif c.goodreads_book_id in by_id:
            first = by_id[c.goodreads_book_id]
            note = f"book has more than one approved correction (rows {first.row_number} and {c.row_number})"
            first.problems.append(note)
        else:
            by_id[c.goodreads_book_id] = c
    for gid, c in by_id.items():
        (out.unusable if c.problems else out.usable)[gid] = c
    return out


def apply(res: RowResult, corrections: Corrections) -> bool:
    """Apply an approved correction to a validated row. Returns True if anything was changed."""
    if res.rejected:
        return False
    rec = res.record
    gid = rec["goodreads_book_id"]
    if gid in corrections.unusable:
        c = corrections.unusable[gid]
        res.warnings.append(Issue("correction_invalid", "isbn-corrections.csv", f"row {c.row_number}: {'; '.join(c.problems)}"))
        return False
    c = corrections.usable.get(gid)
    if c is None:
        return False
    changed = False

    if c.isbn13:
        if rec["isbn13"] is None:
            rec["isbn13"], rec["isbn13_source"] = c.isbn13, c.provenance
            if c.isbn10:
                rec["isbn10"] = c.isbn10
            res.repairs.append(FieldRepair("isbn13", res.raw.get("isbn13") or "", c.isbn13, f"approved correction ({c.provenance})"))
            res.warnings = [w for w in res.warnings if w.code not in ISBN_WARNINGS]
            changed = True
        elif rec["isbn13"] != c.isbn13:
            res.warnings.append(Issue("correction_not_applied", "isbn13",
                                      f"the file's valid ISBN {rec['isbn13']} was kept; correction {c.isbn13} not used"))

    if c.year is not None:
        if rec["publication_year"] is None:
            rec["publication_year"], rec["publication_year_source"] = c.year, c.provenance
            res.repairs.append(FieldRepair("original_publication_year", res.raw.get("original_publication_year") or "",
                                           str(c.year), f"approved correction ({c.provenance})"))
            res.warnings = [w for w in res.warnings if w.code not in YEAR_WARNINGS]
            changed = True
        elif rec["publication_year"] != c.year:
            res.warnings.append(Issue("correction_not_applied", "original_publication_year",
                                      f"the file's year {rec['publication_year']} was kept; correction {c.year} not used"))

    if c.no_isbn_reason and rec["isbn13"] is None:
        rec["no_isbn_reason"] = f"{c.no_isbn_reason}; approved by {c.approved_by}"
        res.warnings = [w for w in res.warnings if w.code not in ISBN_WARNINGS]
        res.notes.append(Issue("accepted_without_isbn", "isbn13", f"accepted without ISBN: {c.no_isbn_reason} (approved by {c.approved_by})"))
        changed = True
    return changed
