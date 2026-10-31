# Implementation: Nightly Book Import

How the import code works, and how it follows the rules in [rules.md](rules.md). [data-validation.md](data-validation.md) is the original diagnosis of the data and was not changed.

## Files

| File | What it does |
|---|---|
| [isbn.py](isbn.py) | ISBN-10 / ISBN-13 cleaning, check digits, conversion, scientific-notation cross-check. Pure functions, no database. |
| [validate.py](validate.py) | Applies the row rules: whitespace, years, required fields, which ISBN the book gets. Also holds the list of problem types, each with its action, reason and recommended librarian action. No database. |
| [import_books.py](import_books.py) | The nightly command. Reads the CSV, matches rows against the database (SQLite), creates/updates/rejects, keeps the audit log and review items, and checks the counts add up. |
| [report.py](report.py) | Writes the morning report (Markdown) plus the rejected-rows CSV and the all-issues CSV. |
| [tests/](tests/) | 58 automated tests (`test_isbn.py`, `test_import.py`). |
| [examples/](examples/) | Real reports produced by the code (see Deliverable 4). |

Python 3.13 standard library only, no packages to install.

```bash
py -3.13 import_books.py books.csv
```

```bash
py -3.13 import_books.py books-batch2.csv
```

```bash
py -3.13 -m unittest discover tests -v
```

The database defaults to `library.db` (`--db` to change it) and reports to `reports/` (`--reports`). The exit code is 2 when the import FAILED, so a nightly scheduler can alert on it. Both `library.db` and `reports/` are git-ignored.

---

## Deliverable 1 / A. Validation decision matrix

Every problem from `data-validation.md`, plus the general rules from my requirements. Problem codes are the names used in the report.

| Problem | Decision | Why | Conditions / exceptions | Example input | Result |
|---|---|---|---|---|---|
| Spaces, hyphens, `ISBN` label | REPAIR | ISBN manual: they have "no lexical significance" | — | `978-0-439-02348-1` | `9780439023481` |
| Lowercase `x` at end of ISBN-10 | REPAIR | same character | `X` only allowed as the last character | `043965548x` | `043965548X` |
| Valid ISBN-10 | Convert to ISBN-13; keep ISBN-10 as alternate | catalog key is ISBN-13 | — | `0439023483` | isbn13 `9780439023481`, isbn10 `0439023483` |
| ISBN-10 missing leading zeros (6,587 rows) | REPAIR | only one possible answer | only 1–3 zeros, **and** check digit must pass after | `7442912` | `0007442912` |
| ISBN-10 wrong check digit (23) | ISBN unusable, LOAD WITH WARNING `isbn10_invalid` | fixing it would be a guess | — | `1847386823` | no ISBN-10 stored |
| ISBN-10 wrong length / invalid characters | ISBN unusable, warning | fails ISBN rules | — | `12345`, `ABC123` | no ISBN-10 stored |
| ISBN-13 in scientific notation (9,382) | Never used. REPAIR from the row's ISBN-10 when it matches the rounded value; otherwise unusable | digits lost; 45% rounded up | must match the rounded number exactly | `9.78067978327e+12` + isbn `679783261` | `9780679783268` |
| ISBN-13 not an ISBN: Nook `2940…`, barcodes (28) | unusable; warning `no_usable_isbn` only if no other ISBN | nothing to restore | — | `2.94001623192e+12` | no ISBN |
| ISBN-13 truncated `.0` (5) | unusable | digits missing | — | `97893806587.0` | no ISBN |
| ISBN-13 as `….0` with all 13 digits | REPAIR | format only | — | `9780439023481.0` | `9780439023481` |
| ISBN-13 wrong check digit / prefix / length / characters | unusable | fails ISBN rules | digits never changed | `9770439023481` | no ISBN |
| `isbn` and `isbn13` disagree (12 rows) | LOAD WITH WARNING `isbn_conflict` + review | probably different editions; can't tell which | only real ISBN conflicts count; non-ISBN barcodes don't (see note) | book 622 | no ISBN stored |
| No usable ISBN (723 rows) | LOAD WITH WARNING `no_usable_isbn` | Goodreads ID identifies the book | — | book 106 | loaded, isbn13 empty |
| Extra whitespace in title/authors/original title | REPAIR | no meaning | other fields only trimmed | `Angels & Demons  (…)` | single space |
| Year `2008.0` | REPAIR | format only | — | `2008.0` | `2008` |
| Missing title / only spaces | REJECT `missing_title` | can't catalog without it | — | `"   "` | rejected |
| Missing or invalid `goodreads_book_id` | REJECT `missing_id` / `invalid_id` | can't match it, so it could become a duplicate | — | `abc` | rejected |
| Missing author | LOAD WITH WARNING `missing_author` | not needed to identify | never guessed | `""` | authors empty |
| Missing year (21) | LOAD WITH WARNING `missing_year` | never guessed | — | `""` | year empty |
| Invalid year | drop field + warning `invalid_year` | rest of row is fine | year 0 is invalid | `20o8` | year empty |
| Negative year (31) | accept as BC | real dates | — | `-750.0` | `-750` |
| Future year | LOAD WITH WARNING `future_year` | typo or upcoming book | compared to the import date | `2030` | `2030` kept |
| Capitalization / special characters | keep as written | not errors | — | `Café & حكاية` | unchanged |
| Missing language code (1,084) | accept, no warning | optional | — | `""` | empty |
| Exact duplicate row in a file | second copy UNCHANGED | not a new book | — | same row twice | 1 record |
| Publisher, edition, format, inventory | not applicable | no such columns in the data | see Known limitations | — | — |

*Note:* `data-validation.md` counted 19 rows where the columns disagree. 12 of them are real ISBN conflicts. The other 7 have a non-ISBN barcode or a truncated `.0` value in `isbn13`, which isn't an ISBN at all, so the valid ISBN-10 is used and there's no conflict.

## Deliverable 2. Implementation summary

**How a row is processed, in order:**

1. **Read** (`read_rows`): the file is read as UTF-8 text. Every value stays a string, so nothing is ever turned into a number and the original problem can't happen again. Missing required columns, an unreadable file or a missing file → **FAILED**.
2. **Validate and clean** (`validate_row`): required fields, whitespace, year, then `_resolve_isbns`, which decides the book's ISBN-13 and ISBN-10 from the two columns using the matrix above. The result is a cleaned record, plus lists of repairs and warnings, or a rejection.
3. **Match and save** (`Importer.process`): looks up `goodreads_book_id` and then creates, compares/updates, or rejects (Deliverable 3). It writes the audit log, review items and rejected rows.
4. **Reconcile:** checks that every row got exactly one outcome and that the four counts add up to the total. If not, → **FAILED**.
5. **Status:**
   - **SUCCESS:** no rejections and no warnings;
   - **COMPLETED WITH ISSUES:** otherwise;
   - **FAILED:** on any error, in which case the whole transaction is rolled back.
6. **Report** (`report.write_reports`).

**Steps 2–4 run in one database transaction.** A crash or failed check saves nothing, so a rerun starts clean.

**Database tables:**

| Table | What it holds |
|---|---|
| `publications` | One row per book, keyed by `goodreads_book_id`. Unique index on `isbn13`. Stores the original `source_isbn` / `source_isbn13` text. |
| `imports` | One row per run, with its counts and status, the file's SHA-256 (to notice a re-imported file), and `reprocess_of`. |
| `row_outcomes` | The outcome, repairs and warnings for every row of every import. |
| `audit_log` | Every repair and every database change: import ID, source file, row, field, old value, new value, reason, time, `automatic`. |
| `rejected_rows` | The original row as JSON, the reason, and `resolved_by_import` once a corrected version loads. |
| `review_items` | Everything a person must decide, with status `open`. |

## Deliverable 3 / B / C. Duplicate and update logic

**Same publication** means the same `goodreads_book_id`, the trusted internal ID. It's unique and never blank in goodbooks-10k. `book_id` is only the dataset row number.

**ISBN normalization:** formatting is removed and an ISBN-10 is converted to ISBN-13 before comparing. So `0-439-02348-3` and `9780439023481` are equal.

**Work / publication / copy:**
- `work_id` is the work, and is stored but never merged on.
- `goodreads_book_id` is the publication.
- There is no copy data, so no inventory is ever created. That means repeated imports can't inflate it.

```
row ──► rejected by validation? ──yes──► REJECTED
            │ no
            ▼
   goodreads_book_id already in catalog?
       │ no                                  │ yes
       ▼                                     ▼
 ISBN-13 owned by another book?        compare field by field
   yes ─► REJECTED (isbn_in_use)          identifying field changed ─► REJECTED (conflicts_existing),
   no  ─► CREATED                                                      nothing applied, review item
          (no ISBN + same title & author       blank filled / refreshable value changed ─► UPDATED (audited)
           as another book ─► warning           nothing different ─► UNCHANGED
           possible_duplicate + review)
```

**What the comparison does with each kind of field:**

- **Identifying fields:** title, original title, authors, year, work_id, language, isbn13, isbn10.
  - Filling a blank → update.
  - Changing a value → conflict, which needs review.
  - A blank incoming value → ignored, so it never erases data.
- **Refreshable fields:** ratings, `books_count`, image URLs, `book_id`, `best_book_id`, and the original ISBN text. These are overwritten, and every change is audited.

**Same title is never enough.** Different valid ISBNs are never merged. A book with no ISBN that shares a title and author with an existing book is created *and* flagged `possible_duplicate`.

**Manual review is created for:**

| Review item | When |
|---|---|
| `isbn_in_use` | The ISBN conflicts with another book. |
| `conflicts_existing` | Incoming data conflicts with trusted catalog data. |
| `isbn_conflict` | The row's two ISBN columns disagree. |
| `possible_duplicate` | A possible duplicate that can't be confirmed. |

There's no review screen. Review items live in the `review_items` table and appear in every report with what to do.

**Idempotency and reprocessing:**
- Re-importing a file gives only UNCHANGED rows, plus the same rejections as before. The report notes when the exact file was imported before.
- Corrected rejected rows are imported with `--reprocess-of <import_id>`. They go through exactly the same rules, including duplicate detection, and earlier rejections of the same book are marked `resolved_by_import`.

## Deliverable 4 / D. Import report

**What each report contains:**
- status and what it means;
- the summary fields: import ID, file, start and end time, total, created, updated, unchanged, rejected, accepted, repaired, warnings, status;
- the reconciliation line `Total = Created + Updated + Unchanged + Rejected`;
- an **Actions required** list;
- every rejected row, with the row number, Goodreads ID, title, original ISBNs, field, problem, why and what to do;
- warnings grouped by type (first 10 of each shown);
- repair counts.

**The two CSV files:**
- `…-issues.csv` has every rejection and warning with all of the fields above.
- `…-rejected.csv` has the rejected rows' original data, ready to correct and re-import.

**Status definitions:**
- **SUCCESS:** every row loaded with no warnings.
- **COMPLETED WITH ISSUES:** finished, with rejections or warnings.
- **FAILED:** nothing saved.

"Repaired" alone doesn't prevent SUCCESS, because a repair has exactly one answer.

**Real reports produced by the code:**
- [examples/1-books-report.md](examples/1-books-report.md): `books.csv` into an empty database gives 10,000 created, 0 rejected, 753 with warnings, COMPLETED WITH ISSUES.
- [examples/2-batch2-report.md](examples/2-batch2-report.md): `books-batch2.csv` afterwards gives **0 created, 200 unchanged**.
- [examples/3-demo-report.md](examples/3-demo-report.md): a small made-up batch ([examples/3-demo-batch.csv](examples/3-demo-batch.csv)) loaded after `books.csv`, to show rejections. It produces:
  - 1 created, with a 979 ISBN and a future year;
  - 1 rejected for a missing title;
  - 1 rejected because the ISBN belongs to *The Hunger Games*;
  - 1 rejected because *The Hunger Games*' title changed;
  - 1 updated (ratings);
  - 1 unchanged.

## E. Repair versus guessing

| Deterministic repair (done) | Why it isn't a guess | Guess (never done) | Why it is a guess |
|---|---|---|---|
| `439023483` → `0439023483` | ISBN-10 is always 10 characters; the check digit confirms | `385535144` → `0385535147` | assumes the first 9 digits are right and the check digit is wrong |
| `9.78067978327e+12` → `9780679783268` (from the row's ISBN-10) | taken from a valid ISBN-10, and the number matches | `9.78067978327e+12` → `978067978327` + new check digit = `9780679783275` | 12th digit was rounded up; this is a **different, wrong** ISBN |
| `978-0-439-02348-1` → `9780439023481` | hyphens carry no meaning | `2.94001623192e+12` → some ISBN | the book has no ISBN in the source |
| `2008.0` → `2008` | same number | missing year → current year | invents a fact |
| `  The Hunger  Games ` → `The Hunger Games` | whitespace only | `The Hunger Games!` replacing an existing title | a different value; a person decides |
| — | — | two *The Stranger*s merged | same title isn't the same book |

## Deliverable 5 / F. Tests

`py -3.13 -m unittest discover tests -v` gives **58 tests: 56 passed, 2 skipped, 0 failed.**

| Requirement test | Test(s) | Expected |
|---|---|---|
| 1 Valid ISBN-10 | `test_01_valid_isbn10` | accepted, no repair |
| 2 Valid ISBN-13 | `test_02_valid_isbn13` | accepted, incl. 979 |
| 3 X check character | `test_03_valid_x_check_character` | accepted |
| 4 Lowercase x | `test_04_lowercase_x_is_repaired` | repaired to `X` |
| 5–6 Spaces / hyphens | `test_05_06_*` (both classes) | removed, value valid |
| 7 Wrong length | `test_07_wrong_length` (both) | invalid; 5-digit value not padded |
| 8 Invalid characters | `test_08_invalid_characters` (both) | invalid |
| 9 Wrong check digit | `test_09_*`, `test_bad_isbn10_digits_are_never_changed` | invalid, digits unchanged |
| 10 Invalid prefix | `test_10_invalid_prefix` | `977` rejected |
| 11 Missing ISBN | `test_11_*` | loaded with `no_usable_isbn` |
| 12 Missing title | `test_12_missing_title_rejected` | REJECTED, original in rejected CSV |
| 13 Missing author | `test_13_*` | loaded with warning |
| 14 Missing publisher | `test_14_missing_publisher` | **skipped: not applicable** |
| 15 Missing year | `test_15_*` | warning, not filled in |
| 16 Invalid year | `test_16_*` | field dropped, row loaded |
| 17 Future year | `test_17_*` | kept with warning |
| 18 Exact duplicate rows | `test_18_*` | CREATED then UNCHANGED, 1 record |
| 19 Same ISBN, same metadata | `test_19_*` | matched, no new record |
| 20 Same ISBN, conflicting | `test_20_*` | REJECTED `isbn_in_use` + review |
| 21 Same title, different ISBNs | `test_21_*` | 2 records, no flag |
| 22 Different editions | `test_22_*` | separate records, same `work_id` |
| 23 No ISBNs | `test_23_*` | created; same title+author flagged |
| 24 Existing + new info | `test_24_*` | UPDATED, audited |
| 25 Existing + conflict | `test_25_*` (author, year, title, ISBN) | REJECTED, catalog unchanged, 4 reviews |
| 26 Repeated import | `test_26_*` | all UNCHANGED, re-import noticed |
| 27 Reprocess corrected rows | `test_27_*` | corrected row CREATED, duplicate still caught, rejection resolved |
| 28 Inventory protection | `test_28_inventory_protection` | **skipped: not applicable** |
| 29 Reconciliation | `test_29_*` | counts add up, status, report text, issues CSV |
| 30 Audit logging | `test_30_*` | repairs + creation logged with old/new |

**Extra tests:**
- the scientific-notation cross-check, including the rounded-up case (book 10) and the other-edition case (book 622);
- the zero restore being refused when the checksum fails;
- `0` never being padded;
- negative years accepted as BC;
- capitalization and special characters kept;
- a blank value never erasing existing data;
- a whitespace-only title change staying UNCHANGED;
- a ratings refresh being audited;
- a missing column or missing file causing FAILED with nothing saved and exit code 2;
- the real data: `books.csv` then `books-batch2.csv` gives 200 UNCHANGED / 0 CREATED, and re-importing `books.csv` leaves all 10,000 UNCHANGED.

## Deliverable 6. Known limitations

- **No publisher, edition, format or inventory rules.** The data has no such columns. The two matching requirement tests are skipped, not faked. Adding those columns later means adding them to `IDENTIFYING_FIELDS` and writing the missing tests.
- **ISBNs are checked for form only.** Nothing is looked up in an outside registry, so "valid" means well formed, not "assigned to this book". The report never claims more.
- **ISBN-10 rules come from ISO 2108.** The International ISBN Agency's current manual covers ISBN-13 only, so these rules couldn't be confirmed from that site. In the data, 9,239 of the 9,258 rows with both numbers agree under these rules, and the other 19 are explained above.
- **Restoring at most 3 leading zeros is a judgment call** based on this data, where 1–3 zeros were missing. A value missing 4 or more zeros will be reported as unusable rather than repaired.
- **The future-year check uses the computer's clock**, at the date of the import.
- **Same-title checking is exact** (ignoring capitals), not fuzzy, so a slightly different spelling won't be flagged as a possible duplicate.
- **No review screen.** Items are in `review_items` and in each report, and are closed by editing the source and re-importing. Rejections close automatically; there's no "mark reviewed" command yet.
- **Rejected again every night.** A conflicting row is rejected (and reported) on every run until someone resolves it. That's intended, but it repeats.
- **Repairs in every report.** Every run repeats the same repairs on unchanged rows, so the audit log grows by about 26,500 entries for each full re-import of `books.csv` (the first import writes about 36,500, including one "created" entry per book).
- **One file at a time.** Two imports must not run at once; SQLite's lock makes the second one fail rather than corrupt anything.

---

## ingest.py, ingestion-log.json and report.html

`ingest.py` is the version of the import built for the Part 4 step. It uses the same row rules as `import_books.py` (it imports `isbn.py` and `validate.py`), but writes to `books.db` and records each run in `ingestion-log.json` instead of Markdown/CSV reports. `report.html` reads that log in the browser.

The questions that `rules.md` left open were answered as follows before any code was written:

| # | Question | Decision |
|---|---|---|
| 1 | New script or reuse? | Reuse `isbn.py` and `validate.py`; `import_books.py` left as it is |
| 2 | Which outputs? | `books.db`, `ingestion-log.json`, and `report.html` only (no Markdown/CSV reports) |
| 3 | Audit log and review items | Tables in `books.db` (`audit_log`, `review_items`, plus `runs` and `rejected_rows`) |
| 4 | What goes in each log entry | Everything `rules.md` section 4 asks for: status, run ID, start/end time, counts, problem counts, actions required |
| 5 | Count names | loaded = CREATED, updated = UPDATED, skipped (already exist) = UNCHANGED, rejected = REJECTED |
| 6 | "Rows not loaded" | Only rejected rows; rows loaded with a warning are listed separately under `warnings` |
| 7 | Fields per listed row | Row number, Goodreads ID, title, original ISBNs, field, problem, detail, action, why, what to do |
| 8 | FAILED runs | Logged too |
| 9 | Damaged log file | Stop with an error before importing; the log is not touched |
| 10 | Required columns | `goodreads_book_id`, `title`, `authors`, `original_publication_year`, `isbn`, `isbn13` |
| 11 | Valid ISBN-10 + non-matching scientific ISBN-13 | Conflict: warning + review, no ISBN stored |
| 12 | Whitespace | Collapse in `title`, `authors`, `original_title`; trim the ends of every other value |
| 13 | `original_title` changes | Reject and review (filling a blank one is an update) |
| 14 | Invalid `goodreads_book_id` | Anything but a positive whole number (`123.0`, `-5`, `0`, blank) is rejected |
| 15 | Future year | Kept, compared with the run date |
| 16 | Possible duplicates | Same title and author, ignoring capitals and extra spaces |
| 17 | "Already imported" | Same file contents (SHA-256), not the same name |
| 18 | Linking corrected rows | `--reprocess-of RUN_ID`; an unknown run ID makes the run FAILED |

**Log file:** a JSON list, one object per run. It's written by saving the whole list to a temporary file and renaming it over the old one, so earlier runs are never lost, even if the script crashes mid-write.

**Deterministic:** no AI, no network, no randomness in results. Only the run ID, timestamps and the future-year check depend on when the script runs. `test_same_file_gives_same_result` checks this.

**Tests:** `tests/test_ingest.py`, 16 tests. They cover:
- count mapping, and that the counts add up;
- rejected-row details;
- SUCCESS status;
- running the same file twice;
- possible-duplicate matching;
- decisions 11, 13 and 14;
- the log being created and appended;
- a FAILED run being logged;
- a damaged log being left untouched;
- identical results for identical input;
- exit codes;
- `--reprocess-of`, including an unknown run ID;
- the real data, where `books.csv` then `books-batch2.csv` gives 10,000 loaded, then 0 loaded and 200 skipped.

**report.html:** verified in a browser:
- runs show newest first, including runs started in the same second;
- FAILED, COMPLETED WITH ISSUES and SUCCESS runs all display;
- text from the CSV is shown as text, not run as HTML;
- the real three-run log (514 KB, 779 warning rows) renders in about 1 second;
- there is no sideways scrolling.

**Limitation:** the log grows with every run, since each entry lists every warning (about 500 KB for a full `books.csv` run).

## make_report.py and ingestion-report.xlsx

Choices made for this addition:
- **Format:** a real Excel `.xlsx`.
- **Separate script:** `ingest.py` is unchanged.
- **Scope:** all runs, in three tabs.

`make_report.py` reads `ingestion-log.json` and writes `ingestion-report.xlsx`. The tabs are:

| Tab | Rows | Columns |
|---|---|---|
| Runs | One per run, newest first | Started, file, status (green SUCCESS / yellow COMPLETED WITH ISSUES / red FAILED), rows read, loaded, updated, skipped, rejected, repaired, rows with warnings, counts add up, error, actions required, already imported as, re-processes run, finished, run ID |
| Rows not loaded | Every rejected row of every run | Run started, file, row, Goodreads ID, title, original isbn/isbn13, field, problem, detail, action, why, what to do, run ID |
| Warnings | Every warning of every run | Same columns as Rows not loaded |

How it's built:
- **Easy to read in Excel:**
  - each tab has a bold header row that stays frozen when scrolling, with a filter on every column;
  - columns have set widths, and long text wraps;
  - counts are real numbers, with thousands separators.
- **No install needed:** Python's standard library writes the workbook directly. An `.xlsx` file is a zip of XML files.
- **Repeatable:** the same log always produces a byte-identical file.
- **Checked:** it was opened with an independent Excel reader (openpyxl, under Python 3.9), which found the right tabs, frozen header, filters, colours and numbers.
- **Tests:** `tests/test_make_report.py`, 9 tests.

**Limitation:** the workbook is a snapshot. Run `make_report.py` again after each import. Each tab holds about a million rows (Excel's limit); past that, the script stops with an error instead of writing a partial file.
