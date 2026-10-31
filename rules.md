# Rules for the Nightly Book Import

These are the rules the import code must follow. They come from my requirements document for this project and the six decisions I approved after reviewing it against `data-validation.md`. The data is `books.csv` from goodbooks-10k (and nightly files in the same format, like `books-batch2.csv`).

**The most important rule: the system never invents information to make a record look valid.** It never changes an ISBN digit, never guesses a year or an author, and never merges two books because their titles look alike.

Every repair, rejection and warning keeps the original value from the source file.

---

## 1. Repair, reject, or load with a warning

Three possible actions:

- **REPAIR:** correct it automatically. Allowed only when there is exactly one possible right answer, so the correction is not a guess.
- **REJECT:** don't load the row; keep it for a person to fix and re-import.
- **LOAD WITH WARNING:** load the row, but list it in the report for someone to look at.

**An invalid ISBN does not reject the whole book.** Every row has a `goodreads_book_id`, which identifies the book. So a book with a bad or missing ISBN can still be loaded, just without an ISBN and with a warning.

### ISBN problems

| Problem (from `data-validation.md`) | Action | Why |
|---|---|---|
| Spaces, hyphens, or an `ISBN` label in the value | REPAIR: remove them | The ISBN manual says hyphens and spaces have no meaning; they're only for readability. |
| ISBN-10 ending in lowercase `x` | REPAIR: make it `X` | Same character, same meaning. |
| Valid ISBN-10 | Convert to ISBN-13 (978 + first 9 digits + new check digit); keep the ISBN-10 as an alternate | The catalog stores ISBN-13, as the ISBN manual recommends. |
| ISBN-10 missing 1–3 leading zeros (6,587 rows) | REPAIR: add the zeros back | An ISBN-10 is always 10 characters, so there is only one possible answer. **Only allowed if the check digit then passes.** Not allowed for more than 3 missing zeros, because very short junk (like `0`) would then "pass". |
| ISBN-10 with a wrong check digit (23 rows) | ISBN unusable → LOAD WITH WARNING | Fixing the check digit means assuming the other 9 digits are right. That's a guess. |
| ISBN-13 in scientific notation (`9.78043902348e+12`, 9,382 rows) | **Never used as an ISBN.** If the row has a valid ISBN-10 whose ISBN-13 matches the rounded number, store that ISBN-13: REPAIR, not a warning. If not, the ISBN-13 is unusable. | The last digit is gone, and in 45% of rows the 12th digit was rounded up. Recalculating a check digit from what's left gives a wrong ISBN almost half the time. The ISBN-10 is the only safe source. |
| ISBN-13 column holds something that isn't an ISBN (Nook `2940…`, store barcodes, placeholders, 28 rows) | ISBN-13 unusable; warning only if the book has no other usable ISBN | These books have no ISBN-13 in the source. There's nothing to restore. |
| Truncated `.0` value (`97893806587.0`, 5 rows) | ISBN-13 unusable | Digits are missing and nothing says what they were. |
| A number written as `….0` but with all 13 digits present | REPAIR: write it as plain digits | No digit changes. |
| ISBN-13 with a wrong check digit, wrong length, letters, or a prefix other than 978/979 | ISBN unusable | It fails the ISBN rules. Digits are never changed to make it pass. |
| `isbn` and `isbn13` point to different publications (19 rows) | LOAD WITH WARNING + manual review; no ISBN stored for the book | Each format gets its own ISBN, so these are probably different editions. Which one this record is can't be known from the file. |
| No usable ISBN at all (565 rows) | LOAD WITH WARNING | The Goodreads ID still identifies the book. Ebooks often have no ISBN. |

A **valid** ISBN only means the number is well formed. It does not prove the ISBN was assigned to this book. The report never claims an ISBN was "verified" unless an outside source was actually checked.

### Other fields

| Problem | Action | Why |
|---|---|---|
| Extra spaces at the start/end or in the middle of a title or author (107 / 168 rows) | REPAIR | Whitespace carries no meaning. |
| Year written as `2008.0` (every row) | REPAIR to `2008` | Format only, no information changes. |
| Missing title, or a title that's only spaces | REJECT | A book can't be cataloged without a title. |
| Missing or invalid `goodreads_book_id` | REJECT | Without it the book can't be matched, so loading it could create a duplicate. |
| Missing author | LOAD WITH WARNING | Not needed to identify the book. Left blank, never guessed. |
| Missing publication year (21 rows) | LOAD WITH WARNING | Left blank, never filled with the current year. |
| Year that isn't a whole number, or year 0 | Drop that field and warn | The rest of the row is still fine. |
| Negative year (31 rows) | Accept as BC | `-750` for Homer is a real date, not an error. |
| Year later than the import date | LOAD WITH WARNING | Could be a typo or an upcoming book. A person should check. |
| Different capitalization | Keep it as written | Not an error. |
| Special characters in titles (`&`, `é`, Arabic script) | Keep | They're part of the title. |
| Missing language code (1,084 rows) | Accept, no warning | Optional field. Warning would only add noise. |

**Not applicable to this data:** publisher, edition, format and physical copies/inventory. `books.csv` has no such columns, so these rules aren't implemented. That also means repeated imports can't inflate any inventory count.

## 2. What makes two rows the same book

Three ideas are kept separate:

- **Work:** the story itself. In this data it's `work_id`.
- **Publication:** one edition in one format, with its own ISBN. In this data it's `goodreads_book_id`.
- **Physical copy:** a book the library owns. Not in this data.

Matching rules:

1. **Same `goodreads_book_id` = same publication.** This is the trusted internal ID. It's never blank, and it's unique across all 10,000 rows. (`book_id` is only this dataset's row number, so it isn't used for matching.)
2. **ISBNs are compared as normalized ISBN-13s.** Formatting is removed and ISBN-10s are converted first, so `0439023483`, `0-439-02348-3` and `9780439023481` are the same ISBN.
3. **Same ISBN-13 but a different `goodreads_book_id`** → REJECT and send for manual review. One ISBN can't belong to two publications, and the system won't choose between them.
4. **Different valid ISBNs are different publications**, even with the same title and author. A paperback and an ebook stay separate.
5. **Same title alone never means the same book.** goodbooks-10k has 33 titles shared by different books, like two different *The Stranger*s.
6. **A book with no usable ISBN** is matched only by `goodreads_book_id`. If a new one has the same title and author as an existing book, it's still loaded as its own record, but flagged as a **possible duplicate** for review.
7. **Exact duplicate rows in the same file** load once. Later copies are UNCHANGED.

## 3. A book that's already in the database arrives again

| What's different | What happens |
|---|---|
| Nothing | **UNCHANGED.** No new record, and the existing one isn't touched. |
| A field that was empty is now filled in (author, year, original title, language, ISBN) | **UPDATED**, after the new value passes validation. Recorded in the audit log. |
| A value is missing in the new row but present in the database | Keep the database value. Missing information never erases existing information. |
| Title differs only in spaces | **UNCHANGED.** Spaces are repaired before comparing. |
| Title (any other change, capitals included), author, year, `work_id` or language changes | **REJECT and review.** Nothing from the row is applied, and the existing record stays as it was. |
| ISBN changes | **Never overwrite. REJECT and review.** |
| Ratings counts, average rating, `books_count`, image URLs, `book_id`, `best_book_id` change | **UPDATED.** These change every night and don't identify the book. Every change is recorded in the audit log with old and new values. |

Re-importing the same file must change nothing: every row comes back UNCHANGED (rows with conflicts are rejected again). This is what lets the job run every night safely. Example: importing `books-batch2.csv` after `books.csv` must give **200 UNCHANGED, 0 CREATED**.

Rejected rows can be corrected and imported again. They go through exactly the same rules, including duplicate detection, and the new import is linked to the one that rejected them.

## 4. The morning report

Every run writes a report a librarian can read without opening the CSV or the database. It must answer:

1. **Did it finish?** Status:
   - **SUCCESS:** every row loaded with no warnings.
   - **COMPLETED WITH ISSUES:** finished, but some rows were rejected or have warnings. Never reported as a plain success.
   - **FAILED:** the file couldn't be read, required columns are missing, an error stopped the run, or the counts don't add up. In that case nothing is saved, so the database is never left half loaded.
2. **What came in:** import ID, file name, start and end time, total rows, and whether this exact file was already imported before.
3. **What happened to each row:** every row has exactly one outcome, CREATED, UPDATED, UNCHANGED or REJECTED, and the report must show that **Total = Created + Updated + Unchanged + Rejected**. Repaired and warnings are counted separately, since a row can have both.
4. **What went wrong:** a count for each kind of problem. For every rejected row and every warning, a line with:
   - the source file and row number;
   - the title and the original ISBN values;
   - the field and the problem;
   - the action taken and why;
   - **what the librarian should do**.
5. **What to do next:** a short "Actions required" list, such as "Fix 2 rejected rows and re-import" or "Review 19 ISBN conflicts".
6. **Files to download:** a CSV of the rejected rows with their original data and reasons, and a CSV of every issue.

Every repair and every database change also goes in an audit log: import ID, row, field, old value, new value, reason, time, automatic or manual, and source file.

## 5. Examples: ISBN values and what the rules do with them

24 examples, some taken from the data (the book number is given) and some made up. **Good** = a valid ISBN as written. **Repairable** = bad as written, but the rules can fix it without guessing. **Bad** = can't be used as an ISBN, or the row can't be loaded as is.

Unless a row says otherwise, the value is in the `isbn` (ISBN-10) column and the rest of the row is fine.

| # | ISBN value | Where it's from | Good or bad? | What the rules say |
|---|---|---|---|---|
| 1 | `0439023483` | made up (correct form of book 1) | **Good** | Valid ISBN-10. Stored as ISBN-13 `9780439023481`, with the ISBN-10 kept as an alternate. |
| 2 | `043965548X` | book 18, *Prisoner of Azkaban* | **Good** | Valid; `X` means 10. Stored as `9780439655484`. |
| 3 | `043965548x` | made up | Repairable | REPAIR lowercase `x` → `X`, then valid as in #2. |
| 4 | `439023483` | book 1, *The Hunger Games* | Repairable | REPAIR: restore 1 leading zero → `0439023483` (the check digit passes). Stored as `9780439023481`. |
| 5 | `7442912` | book 69, *Insurgent* | Repairable | REPAIR: restore 3 leading zeros → `0007442912`. Stored as `9780007442911`. |
| 6 | `12345` | made up | **Bad** | Unusable: 5 characters. Too many zeros missing to restore safely. Loaded with warning if there's no other ISBN. |
| 7 | `1847386823` | book 3473, *Dark Visions* | **Bad** | Unusable: check digit is wrong (should be 2). Digits are **not** changed. LOAD WITH WARNING. |
| 8 | `385535144` | book 1543, *The Racketeer* | **Bad** | Unusable: still fails after restoring the zero (expected 7). LOAD WITH WARNING. |
| 9 | `ABC123` | made up | **Bad** | Unusable: invalid characters. LOAD WITH WARNING. |
| 10 | `978-0-439-02348-1` in `isbn13` | made up | Repairable | REPAIR: remove hyphens → `9780439023481`, which is valid. |
| 11 | `ISBN 978 0 439 02348 1` in `isbn13` | made up | Repairable | REPAIR: remove label and spaces → `9780439023481`, which is valid. |
| 12 | `9780439023482` in `isbn13` | made up | **Bad** | Unusable: check digit is wrong (should be 1). Not changed. |
| 13 | `9770439023481` in `isbn13` | made up | **Bad** | Unusable: prefix 977 isn't 978/979 (977 is used for magazines). |
| 14 | `9791032305690` in `isbn13` | made up | **Good** | Valid ISBN-13 with the 979 prefix. Has no ISBN-10 form. |
| 15 | `9.78043902348e+12` in `isbn13`, `isbn` = `439023483` | book 1 | Repairable | REPAIR: ISBN-13 rebuilt from the ISBN-10 as `9780439023481`, which matches the rounded number. |
| 16 | `9.78067978327e+12` in `isbn13`, `isbn` = `679783261` | book 10 | Repairable | REPAIR: rebuilt from the ISBN-10 as `9780679783268`. Recalculating from the visible digits would have given a wrong ISBN, because the 12th digit was rounded up. |
| 17 | `9.78043902348e+12` in `isbn13`, `isbn` empty | made up | **Bad** | Unusable: digits lost, nothing to check against. LOAD WITH WARNING, no ISBN. |
| 18 | `2.94001623192e+12` in `isbn13`, `isbn` empty | book 1165, *Wait for You* | **Bad** | Not an ISBN (Nook ebook code). LOAD WITH WARNING, no ISBN. |
| 19 | `97893806587.0` in `isbn13` | book 1443 | **Bad** | Unusable: only 11 digits. |
| 20 | `isbn` = `446612707`, `isbn13` = `9.78055381395e+12` | book 622 | **Bad** | The two columns point to different publications. LOAD WITH WARNING + review; no ISBN stored. |
| 21 | both empty | book 106, *Bossypants* | **Bad** | LOAD WITH WARNING: no ISBN. Identified by Goodreads ID. |
| 22 | `439023483` again, same `goodreads_book_id`, nothing else changed | `books-batch2.csv` | Repairable | UNCHANGED. No new record. |
| 23 | `9780439023481` on a **different** `goodreads_book_id` | made up | **Bad** | REJECT + review: this ISBN already belongs to another book. |
| 24 | `0439023483`, same `goodreads_book_id`, but the title has changed | made up | **Bad** | REJECT + review: the existing record is not overwritten. |
