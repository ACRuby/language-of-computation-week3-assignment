# Library Import Report — 3-demo-batch.csv

**Status: COMPLETED WITH ISSUES** — The import finished and the catalog is updated, but some rows were rejected or need attention (see Actions required).

| | |
|---|---:|
| Import ID | `20261031T142223-68bcab` |
| File | 3-demo-batch.csv |
| Started | 2026-10-31 14:22:23 |
| Finished | 2026-10-31 14:22:23 |
| Total rows | 6 |
| Created | 1 |
| Updated | 1 |
| Unchanged | 1 |
| Rejected | 3 |
| Total accepted | 3 |
| Automatically repaired | 3 |
| Loaded with warnings | 2 |
| Status | COMPLETED WITH ISSUES |

**Check:** 6 rows = 1 created + 1 updated + 1 unchanged + 3 rejected — adds up.

## Actions required

- **1 row(s) rejected: `missing_title`.** Add the title to the source row and re-import it.
- **1 row(s) rejected: `isbn_in_use`.** Check which book the ISBN really belongs to, then correct the source or the catalog.
- **1 row(s) rejected: `conflicts_existing`.** Compare the old and new values and decide which is right; update the catalog or the source manually.
- **1 row(s) loaded with a warning: `future_year`.** Check whether the year is a typo or the book is not yet published.
- **1 row(s) loaded with a warning: `no_usable_isbn`.** Look up the ISBN if the book has one (ebook-only titles may not).

Every issue, with row number and original values, is in `3-demo-issues.csv`. Rejected rows with their original data are in `3-demo-rejected.csv`; correct them and re-import with `--reprocess-of 20261031T142223-68bcab`.

## Rejected rows

| Row | Goodreads ID | Title | isbn | isbn13 | Field | Problem | Why | What to do |
|---:|---|---|---|---|---|---|---|---|
| 3 | 90000002 | — | 0-439-02348-3 | — | title | title is blank or only spaces | A book can't be cataloged without a title. | Add the title to the source row and re-import it. |
| 4 | 90000003 | Not The Hunger Games | 439023483 | — | isbn13 | ISBN 9780439023481 already belongs to goodreads_book_id 2767052 ('The Hunger Games (The Hunger Games, #1)') | This ISBN already belongs to a different book in the catalog; one ISBN can't identify two publications. | Check which book the ISBN really belongs to, then correct the source or the catalog. |
| 5 | 2767052 | The Hunger Games: Special Edition | 439023483 | 9.78043902348e+12 | title | title: catalog has 'The Hunger Games (The Hunger Games, #1)', file has 'The Hunger Games: Special Edition' | Incoming values conflict with the existing catalog record; nothing was changed so trusted data isn't overwritten. | Compare the old and new values and decide which is right; update the catalog or the source manually. |

## Warnings (rows were loaded)

### `future_year` — 1 row(s)

The year is later than the import date; it was kept as given. **What to do:** Check whether the year is a typo or the book is not yet published.

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 2 | 90000001 | A Made-Up Future Book | — | 979-10-323-0569-0 | 2027 is later than the import date (2026-10-31) |

### `no_usable_isbn` — 1 row(s)

The book was loaded and identified by its Goodreads ID, but it has no ISBN that passes validation. **What to do:** Look up the ISBN if the book has one (ebook-only titles may not).

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 7 | 9418327 | Bossypants | — | — | both ISBN columns are empty |

## Automatic repairs

Only repairs with exactly one possible answer are made; originals are kept in the audit log.

| Field | Repair | Rows |
|---|---|---:|
| original_publication_year | removed '.0' from a whole-number year | 2 |
| isbn13 | removed formatting with no meaning (ISBN label, spaces, hyphens, lowercase x) | 1 |
| isbn | restored 1 dropped leading zero(s); only one answer is possible and the check digit confirms it | 1 |
| isbn13 | isbn13 had lost its last digit(s); rebuilt from the row's valid ISBN-10, which matches the rounded value | 1 |
