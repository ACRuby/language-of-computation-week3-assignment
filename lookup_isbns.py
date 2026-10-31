"""Suggest ISBNs and years for books with warnings, using Open Library.

    python lookup_isbns.py                     (looks up books.csv)
    python lookup_isbns.py books-batch2.csv

Run by hand only -- never part of the nightly load. It uses the internet,
so it is kept apart from ingest.py, which must not. Nothing here changes
the database: it writes isbn-suggestions.csv for a person to review. They
fill in the approval columns and save the file as isbn-corrections.csv,
which ingest.py then reads (rules.md section 5).

Open Library's API rules are followed: at most 1 search per second, a
User-Agent naming this project, and every answer is saved in
open-library-cache.json so the same search is never sent twice.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import isbn as isbnlib
from validate import ISBN_WARNINGS, YEAR_WARNINGS, validate_row

SEARCH_URL = "https://openlibrary.org/search.json"
USER_AGENT = "language-of-computation-week3-assignment/1.0 (+https://github.com/ACRuby/language-of-computation-week3-assignment)"
FIELDS = "key,title,author_name,first_publish_year,isbn,publisher,format,edition_count"
MAX_SHOWN = 10
SELF_PUBLISHED = re.compile(r"createspace|independently published|smashwords|lulu|kindle direct|amazon digital|"
                            r"self[- ]?published|author ?house|xlibris|iuniverse|draft2digital|booktango", re.I)

COLUMNS = [
    "goodreads_book_id", "title", "authors", "problem", "needs", "lookup_result",
    "suggested_isbn13s", "more_isbns_on_open_library", "suggested_year", "format_hint",
    "open_library_link", "open_library_title", "open_library_author",
    "approved_isbn13", "approved_year", "approved_no_isbn_reason", "approved_by", "source", "notes",
    "isbn_in_file", "isbn13_in_file", "year_in_file", "row_in_file",
]


def search_terms(raw):
    """Title (series suffix like '(The Hunger Games, #1)' removed) and first author."""
    title = (raw.get("original_title") or "").strip() or re.sub(r"\s*\([^()]*#[^()]*\)\s*$", "", raw.get("title") or "").strip()
    author = (raw.get("authors") or "").split(",")[0].strip()
    return title, author


class OpenLibrary:
    def __init__(self, cache_path: Path, delay=1.0, fetch=None):
        self.cache_path, self.delay = cache_path, delay
        self.cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        self.fetch = fetch or self._fetch
        self.last_request = 0.0
        self.requests = 0

    def _fetch(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def search(self, title, author):
        url = SEARCH_URL + "?" + urllib.parse.urlencode({"title": title, "author": author, "limit": 3, "fields": FIELDS})
        if url in self.cache:
            return self.cache[url]
        for attempt in range(3):
            wait = self.delay - (time.monotonic() - self.last_request)
            if wait > 0:
                time.sleep(wait)
            self.last_request = time.monotonic()
            self.requests += 1
            try:
                result = self.fetch(url)
                self.cache[url] = result                     # only successful answers are cached
                if self.requests % 25 == 0:
                    self.save()
                return result
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(10 * (attempt + 1))           # Open Library asked us to slow down
                    continue
                return {"error": f"HTTP {e.code}"}
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                if attempt < 2:
                    time.sleep(5)
                    continue
                return {"error": str(getattr(e, "reason", e))}
        return {"error": "gave up"}

    def save(self):
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def isbns_in_use(db_path):
    if not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    try:
        return dict(conn.execute("SELECT isbn13, goodreads_book_id FROM books WHERE isbn13 IS NOT NULL").fetchall())
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def suggestion_row(raw, res, answer, in_use):
    codes = [w.code for w in res.warnings if w.code in ISBN_WARNINGS | YEAR_WARNINGS]
    needs = [n for n, group in (("ISBN", ISBN_WARNINGS), ("year", YEAR_WARNINGS)) if set(codes) & group]
    gid = res.record["goodreads_book_id"]
    row = {
        "goodreads_book_id": gid, "title": raw.get("title"), "authors": raw.get("authors"),
        "problem": "; ".join(f"{w.code}: {w.detail}" for w in res.warnings if w.code in codes),
        "needs": " and ".join(needs), "isbn_in_file": raw.get("isbn"), "isbn13_in_file": raw.get("isbn13"),
        "year_in_file": raw.get("original_publication_year"), "row_in_file": res.row_number,
    }
    hints = []
    if (raw.get("isbn13") or "").startswith("2.940"):
        hints.append("file holds a Barnes & Noble Nook ebook code")
    docs = answer.get("docs") or []
    if "error" in answer:
        row["lookup_result"] = f"error: {answer['error']} (run again later to retry)"
    elif not docs:
        row["lookup_result"] = "not found on Open Library"
    else:
        doc = docs[0]
        row["lookup_result"] = "found" + (f" (best of {answer.get('numFound')} matches)" if answer.get("numFound", 0) > 1 else "")
        candidates = []
        for value in doc.get("isbn") or []:
            r13 = isbnlib.parse_isbn13(value)
            r10 = isbnlib.parse_isbn10(value) if r13.status != "valid" else None
            isbn13 = r13.value if r13.status == "valid" else isbnlib.isbn10_to_isbn13(r10.value) if r10 and r10.status == "valid" else None
            if isbn13 and isbn13 not in candidates:
                candidates.append(isbn13)
        # English-language editions (978-0, 978-1) first; otherwise Open Library's order.
        candidates.sort(key=lambda c: not c.startswith(("9780", "9781")))
        shown = []
        for c in candidates[:MAX_SHOWN]:
            owner = in_use.get(c)
            shown.append(f"ISBN {c}" + (f" (already used by goodreads_book_id {owner})" if owner and owner != gid else ""))
        row["suggested_isbn13s"] = "; ".join(shown)
        row["more_isbns_on_open_library"] = max(0, len(candidates) - MAX_SHOWN) or ""
        row["suggested_year"] = doc.get("first_publish_year") or ""
        row["open_library_link"] = "https://openlibrary.org" + doc["key"] if doc.get("key") else ""
        row["open_library_title"] = doc.get("title")
        row["open_library_author"] = ", ".join(doc.get("author_name") or [])
        row["source"] = "Open Library"
        # Hints only when every listed edition points the same way: one cheap reprint of a classic
        # doesn't make the book self-published. A person decides either way.
        formats = doc.get("format") or []
        if formats and all(re.search(r"e-?book|electronic", f, re.I) for f in formats):
            hints.append("Open Library lists only ebook formats")
        publishers = sorted(set(doc.get("publisher") or []))
        if publishers and all(SELF_PUBLISHED.search(p) for p in publishers):
            hints.append("every publisher looks self-published: " + ", ".join(publishers[:3]))
    row["format_hint"] = "; ".join(hints)
    return row


def run(csv_path, out_path, cache_path, db_path, delay=1.0, limit=None, fetch=None, today=None, progress=print):
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    today = today or date.today()
    todo = []
    for i, raw in enumerate(rows):
        res = validate_row(raw, i + 2, today)
        if not res.rejected and {w.code for w in res.warnings} & (ISBN_WARNINGS | YEAR_WARNINGS):
            todo.append((raw, res))
    if limit:
        todo = todo[:limit]
    ol = OpenLibrary(Path(cache_path), delay, fetch)
    in_use = isbns_in_use(db_path)
    out = []
    try:
        for n, (raw, res) in enumerate(todo, 1):
            out.append(suggestion_row(raw, res, ol.search(*search_terms(raw)), in_use))
            if n % 25 == 0 or n == len(todo):
                progress(f"  {n:,}/{len(todo):,} books looked up")
    finally:
        ol.save()
    # utf-8 with BOM so Excel shows accented and non-Latin titles correctly
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, COLUMNS)
        w.writeheader()
        w.writerows(out)
    found = sum(1 for r in out if r.get("lookup_result", "").startswith("found"))
    errors = sum(1 for r in out if r.get("lookup_result", "").startswith("error"))
    return {"books": len(out), "found": found, "not_found": len(out) - found - errors, "errors": errors, "requests": ol.requests}


def main(argv=None):
    p = argparse.ArgumentParser(description="Suggest ISBNs/years from Open Library for books with warnings.")
    p.add_argument("csv_file", nargs="?", default="books.csv", help="books file to check (default: books.csv)")
    p.add_argument("--out", default="isbn-suggestions.csv", help="suggestions file to write (default: isbn-suggestions.csv)")
    p.add_argument("--cache", default="open-library-cache.json", help="saved Open Library answers (default: open-library-cache.json)")
    p.add_argument("--db", default="books.db", help="database, to mark suggested ISBNs already used by another book")
    p.add_argument("--limit", type=int, help="only look up the first N books (for a quick try)")
    a = p.parse_args(argv)
    print(f"Looking up books with ISBN or year warnings in {a.csv_file} on Open Library (1 per second)...")
    s = run(a.csv_file, a.out, a.cache, a.db, limit=a.limit)
    print(f"Done: {s['books']:,} books, {s['found']:,} found, {s['not_found']:,} not found, {s['errors']:,} errors "
          f"({s['requests']:,} new searches). Wrote {a.out}.")
    print("Next: open it in Excel, fill in the approved_ columns for the books you've checked, and save it as isbn-corrections.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
