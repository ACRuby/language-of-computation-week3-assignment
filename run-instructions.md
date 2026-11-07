# Running the pipeline and reading the report

This is the one-stop reference for running `ingest.py` against the
**agreed rules** ([`rules.md`](rules.md)) and reading its output. The code
lives in `week3-assignment/` (that's where the CSVs, the database, and the
script are). This copy is adapted to Abigail's build: her folder path, and
`py -3.13` instead of `python` (on her Windows machine `python`/`python3`
open the Microsoft Store instead of running Python).

## Parameters

`ingest.py` takes **no command-line parameters**. Every "parameter" is a
constant at the top of the file instead — by design, per the script's own
docstring, so that a given run is always exactly reproducible from the
file alone, with no way to silently pass the wrong flag on the command
line.

| Constant | Default | What it controls |
|---|---|---|
| `CSV_FILENAME` | `"books.csv"` | The input file to ingest, resolved relative to `week3-assignment/`. |
| `DB_FILENAME` | `"books.db"` | The SQLite database written to / read from. |
| `LOG_FILENAME` | `"ingestion-log.json"` | Where each run's report entry is appended (never overwritten). |

To ingest a different file, open `week3-assignment/ingest.py` in a text
editor, change `CSV_FILENAME` near the top, save, and run it again — see
below.

## Running it

```powershell
cd "C:\Users\abiga\workspace\language-of-computation\week3-assignment"
py -3.13 ingest.py
```

This is safe to run as many times as you like: it updates `books.db` and
appends a new entry to `ingestion-log.json` each time, rather than
overwriting anything.

To ingest both `books.csv` and `books-batch2.csv` in one go, without
hand-editing `CSV_FILENAME` twice:

```powershell
py -3.13 -c "import ingest; [print(ingest.summary_line(ingest.run(ingest.HERE / f))) for f in ['books.csv', 'books-batch2.csv']]"
```

Either way, it prints one summary line per file when it finishes, e.g.:

```
status=COMPLETED WITH ISSUES rows_read=10000 loaded=10000 updated=0 skipped=0 rejected=0 rows_with_warning=723
```

`status` is the three-tier run verdict from Decision 7:

- **SUCCESS** — every row loaded with no warnings.
- **COMPLETED WITH ISSUES** — the run finished, but something was rejected
  or carries a warning.
- **FAILED** — the file couldn't be read, a required column is missing, or
  an error stopped the run partway through. This is a status label, not a
  rollback guarantee — see `rules.md`'s *Resolved conflict* section for
  exactly what it does and doesn't promise about `books.db`. The log entry
  and the report say so explicitly.

## Reading the report

`week3-assignment/report.html` reads `ingestion-log.json` directly in your
browser — nothing is uploaded anywhere.

1. In File Explorer, go to `week3-assignment/` and double-click
   `report.html` (or run `start report.html` from the same terminal).
2. Click **"Open ingestion-log.json"** and select that file from the same
   folder.
3. Each run appears as a card, newest first, with a colored status pill
   (green SUCCESS / amber COMPLETED WITH ISSUES / red FAILED) plus the
   headline counts: processed / loaded clean / loaded with a warning /
   updated / skipped / rejected. Click a card to expand it into the full
   detail: rejected rows (kept separate, they need a person), the
   breakdown by rule, and lists of warnings, updated fields (old → new)
   and repairs.

Older log entries from before this update were written under Abigail's
earlier rules. They keep their own status pill, are marked **earlier
rules**, and have no row-by-row detail to expand.

`py -3.13 make_report.py` writes the same information to
`ingestion-report.xlsx` (tabs: Runs, Rejected, Warnings, Updates, Repairs,
Breakdown by rule).

## What the numbers mean, per the agreed rules

- **rejected** rows are rejected for exactly three reasons:
  `structural-parse-error` (the CSV row itself didn't parse),
  `isbn-collision` (a valid ISBN already belongs to a different
  `goodreads_book_id`), or `identity-field-conflict` (an identity-relevant
  field — title/authors/year/`work_id`/language/ISBN — already had a
  different value on file). See `rules.md` §1 and §3. This build also
  rejects a blank or non-number `goodreads_book_id`
  (`missing-goodreads-id` / `invalid-goodreads-id`), which the agreed rules
  assume never happens — see `rules.md` §5, note 6.
- **updated** rows had either a volatile-metadata field change (ratings,
  counts, image URLs — always applied) or an identity-relevant field that
  was previously empty and got filled in. See `rules.md` §3.
- **rows_with_warning** counts rows (loaded, updated or skipped) whose book
  has at least one entry in the `warnings` table — including the
  `no-usable-isbn` reason (Decision 3: loaded with a warning, not silently)
  and comma-separated multi-reason warnings like `lost-precision,bad-prefix`
  when more than one problem applies to the same field. Every code is
  listed in `rules.md` §5.

## The numbers in this build (Abigail's)

On an empty database:

| File | Result |
|---|---|
| `books.csv` | `rows_read=10000 loaded=10000 rejected=0 rows_with_warning=723` (9,277 loaded clean) |
| `books-batch2.csv`, after `books.csv` | `rows_read=200 skipped=200 rejected=0 rows_with_warning=18` |

In `books.csv`, 715 of the 723 rows have no usable ISBN at all: 565 are
empty in both columns, 149 have an `isbn13` that lost its digits (25 of
those are also `bad-prefix` Nook codes), and 1 has a bad `isbn` with an
empty `isbn13`. The other 8 rows have a usable ISBN but an `isbn13` of the
wrong length, which is warned and replaced from the valid `isbn`. Separately,
15 rows have an `isbn` with a bad checksum. The report's "Breakdown by
rule" has the exact count for every code.
