# Library Import Report — books-batch2.csv

**Status: COMPLETED WITH ISSUES** — The import finished and the catalog is updated, but some rows were rejected or need attention (see Actions required).

| | |
|---|---:|
| Import ID | `20261031T142159-c22aa4` |
| File | books-batch2.csv |
| Started | 2026-10-31 14:21:59 |
| Finished | 2026-10-31 14:21:59 |
| Total rows | 200 |
| Created | 0 |
| Updated | 0 |
| Unchanged | 200 |
| Rejected | 0 |
| Total accepted | 200 |
| Automatically repaired | 200 |
| Loaded with warnings | 19 |
| Status | COMPLETED WITH ISSUES |

**Check:** 200 rows = 0 created + 0 updated + 200 unchanged + 0 rejected — adds up.

## Actions required

- **19 row(s) loaded with a warning: `no_usable_isbn`.** Look up the ISBN if the book has one (ebook-only titles may not).
- **2 row(s) loaded with a warning: `isbn10_invalid`.** Check the ISBN printed on the book and correct the source row.

Every issue, with row number and original values, is in `2-batch2-issues.csv`.

## Warnings (rows were loaded)

### `no_usable_isbn` — 19 row(s)

The book was loaded and identified by its Goodreads ID, but it has no ISBN that passes validation. **What to do:** Look up the ISBN if the book has one (ebook-only titles may not).

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 14 | 6765740 | Perahu Kertas | — | 9.78979122778e+12 | isbn13 '9.78979122778e+12': written in scientific notation; the last digit(s) were lost |
| 26 | 16148938 | Second Shift: Order (Shift, #2) | — | — | both ISBN columns are empty |
| 27 | 23357188 | Bound by Honor (Born in Blood Mafia Chronicles, #1) | — | 9.78131173642e+12 | isbn13 '9.78131173642e+12': written in scientific notation; the last digit(s) were lost |
| 29 | 13453029 | Wool Omnibus (Silo, #1) | — | — | both ISBN columns are empty |
| 32 | 27152124 | Dirty English (English, #1) | — | — | both ISBN columns are empty |
| 33 | 4865 | How to Win Friends and Influence People | — | 9.78067172365e+12 | isbn13 '9.78067172365e+12': written in scientific notation; the last digit(s) were lost |
| 62 | 153785 | Page (Protector of the Small, #2) | — | — | both ISBN columns are empty |
| 68 | 18943009 | Rock Bottom (Tristan & Danika, #2) | — | — | both ISBN columns are empty |
| 69 | 17181905 | The Arrangement: The Ferro Family (The Arrangement, #1) | — | — | both ISBN columns are empty |
| 83 | 6780439 | Dark Visions (Dark Visions, #1-3) | 1847386823 | 9.78184738682e+12 | isbn '1847386823': check digit is wrong (expected 2); isbn13 '9.78184738682e+12': written in scientific notation; the last digit(s) were lost |

…and 9 more in `2-batch2-issues.csv`.

### `isbn10_invalid` — 2 row(s)

The ISBN-10 fails the ISBN rules; digits are never changed to make it pass. **What to do:** Check the ISBN printed on the book and correct the source row.

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 83 | 6780439 | Dark Visions (Dark Visions, #1-3) | 1847386823 | 9.78184738682e+12 | '1847386823': check digit is wrong (expected 2) |
| 117 | 213753 | Life As We Knew It (Last Survivors, #1) | 152061548 | — | '152061548': check digit is wrong even after restoring 1 leading zero(s) (expected 1) |

## Automatic repairs

Only repairs with exactly one possible answer are made; originals are kept in the audit log.

| Field | Repair | Rows |
|---|---|---:|
| original_publication_year | removed '.0' from a whole-number year | 200 |
| isbn13 | isbn13 had lost its last digit(s); rebuilt from the row's valid ISBN-10, which matches the rounded value | 181 |
| isbn | restored 1 dropped leading zero(s); only one answer is possible and the check digit confirms it | 115 |
| isbn | restored 2 dropped leading zero(s); only one answer is possible and the check digit confirms it | 23 |
| original_title | removed extra whitespace | 11 |
| title | removed extra whitespace | 1 |
| isbn | restored 3 dropped leading zero(s); only one answer is possible and the check digit confirms it | 1 |
