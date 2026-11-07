# Implementation: how the code follows the agreed rules

The rules are in [rules.md](rules.md) (the group's agreed rules, with this
build's gap decisions in section 5). The database layout is in
[erd.md](erd.md). How to run it is in [README.md](README.md) and
[run-instructions.md](run-instructions.md).

Python 3.13 standard library only; no packages to install. No AI and no
internet: the same file against the same database always gives the same
result.

## Files

| File | What it does | Rules |
|---|---|---|
| [isbn.py](isbn.py) | Check digits, ISBN-10 ↔ ISBN-13 conversion, and `resolve()`, which decides each row's `isbn` and `isbn13` and returns the repairs and the warning reason codes. Pure functions. | §1, §5 notes 1–5, 11, 15 |
| [validate.py](validate.py) | One CSV row → the record to store. Rejects a missing/invalid `goodreads_book_id`; passes every other field through unchanged. Holds the volatile / identity-relevant field lists and the case-insensitive title comparison. | §1, §2, §3, §5 notes 6, 7, 13, 14 |
| [ingest.py](ingest.py) | Reads the CSV (a row with the wrong number of fields or broken quoting is a `structural-parse-error`), checks ISBN collisions, loads / updates / skips / rejects by `goodreads_book_id`, writes `books` + `warnings`, commits each row, and appends one entry to `ingestion-log.json`. | §1–§4, Resolved conflict, §5 notes 8–10, 12 |
| [report.html](report.html) | Reads `ingestion-log.json` in the browser: one card per run, newest first, status pill, headline counts; click to expand rejections, breakdown by rule, warnings, updates and repairs. | §4 |
| [make_report.py](make_report.py) | The same log as an Excel workbook (`ingestion-report.xlsx`). | §4 |
| [tests/](tests/) | 51 automatic tests: every ISBN row of §1, the schema, loading, rejections, updates, failures and the Excel file. | |

## One run, step by step

1. **The log is checked first.** If `ingestion-log.json` exists but can't be
   read, the program stops before touching anything (the log is never
   overwritten).
2. **The file is read.** A missing file, a file that isn't UTF-8 text, or a
   missing column makes the run `FAILED`.
3. **Each row**, in file order:
   - a broken row is rejected (`structural-parse-error`);
   - `validate_row` rejects a blank/invalid `goodreads_book_id`, otherwise
     resolves the ISBNs (`isbn.resolve`);
   - a valid ISBN already held by a different `goodreads_book_id` is
     rejected (`isbn-collision`);
   - a new `goodreads_book_id` is inserted (`identity_key` = the same
     value) with its warnings;
   - a known one is compared: identity-relevant fields fill gaps or, if
     they disagree, the row is rejected (`identity-field-conflict`) and the
     stored book is left alone; volatile fields are updated; no change at
     all is a skip;
   - the row is committed.
4. **The run status** is SUCCESS (nothing rejected, no warnings),
   COMPLETED WITH ISSUES, or FAILED. A FAILED entry carries the agreed
   sentence that rows from before the failure may already be saved.
5. **The log entry** holds the headline counts, whether they add up, the
   breakdown by rule, the rejections (needs a person), and the warning,
   update (old → new) and repair lists.

## Results on the project data

See the end of [run-instructions.md](run-instructions.md): `books.csv`
loads 10,000 books with 723 warnings and no rejections; `books-batch2.csv`
is then skipped entirely (200 duplicates, 18 still carrying warnings).

## Known limitations and gaps for the group

- The `isbn` values that lost a leading zero *and* had 978 stripped are not
  repaired (13 rows; `rules.md` §5 note 15).
- A blank/invalid `goodreads_book_id` is rejected even though the agreed
  rules assume it never happens (§5 note 6).
- `fallback_key` is always empty, waiting for the group's yes/no (erd.md).
- With no atomicity, a run that fails partway leaves the rows before the
  failure saved. Re-running is safe: they are skipped.
- A valid ISBN is only well formed; nothing checks that it belongs to that
  book.
