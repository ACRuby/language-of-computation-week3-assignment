# Library Import Report — books.csv

**Status: COMPLETED WITH ISSUES** — The import finished and the catalog is updated, but some rows were rejected or need attention (see Actions required).

| | |
|---|---:|
| Import ID | `20261031T142156-0f0e8a` |
| File | books.csv |
| Started | 2026-10-31 14:21:56 |
| Finished | 2026-10-31 14:21:59 |
| Total rows | 10,000 |
| Created | 10,000 |
| Updated | 0 |
| Unchanged | 0 |
| Rejected | 0 |
| Total accepted | 10,000 |
| Automatically repaired | 9,998 |
| Loaded with warnings | 753 |
| Status | COMPLETED WITH ISSUES |

**Check:** 10,000 rows = 10,000 created + 0 updated + 0 unchanged + 0 rejected — adds up.

## Actions required

- **723 row(s) loaded with a warning: `no_usable_isbn`.** Look up the ISBN if the book has one (ebook-only titles may not).
- **23 row(s) loaded with a warning: `isbn10_invalid`.** Check the ISBN printed on the book and correct the source row.
- **21 row(s) loaded with a warning: `missing_year`.** Add the year if known; the next import will fill it in.
- **12 row(s) loaded with a warning: `isbn_conflict`.** Decide which edition this record describes and correct the source row.

Every issue, with row number and original values, is in `1-books-issues.csv`.

## Warnings (rows were loaded)

### `no_usable_isbn` — 723 row(s)

The book was loaded and identified by its Goodreads ID, but it has no ISBN that passes validation. **What to do:** Look up the ISBN if the book has one (ebook-only titles may not).

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 107 | 9418327 | Bossypants | — | — | both ISBN columns are empty |
| 122 | 7604 | Lolita | — | — | both ISBN columns are empty |
| 163 | 49552 | The Stranger | — | — | both ISBN columns are empty |
| 189 | 10664113 | A Dance with Dragons (A Song of Ice and Fire, #5) | — | — | both ISBN columns are empty |
| 204 | 11505797 | Beautiful Disaster (Beautiful, #1) | — | — | both ISBN columns are empty |
| 261 | 4865 | How to Win Friends and Influence People | — | 9.78067172365e+12 | isbn13 '9.78067172365e+12': written in scientific notation; the last digit(s) were lost |
| 325 | 16068905 | Fangirl | — | — | both ISBN columns are empty |
| 349 | 16143347 | We Were Liars | — | — | both ISBN columns are empty |
| 414 | 7190 | The Three Musketeers | — | — | both ISBN columns are empty |
| 465 | 1923820 | Holy Bible: King James Version | — | — | both ISBN columns are empty |

…and 713 more in `1-books-issues.csv`.

### `isbn10_invalid` — 23 row(s)

The ISBN-10 fails the ISBN rules; digits are never changed to make it pass. **What to do:** Check the ISBN printed on the book and correct the source row.

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 917 | 7603 | Reading Lolita in Tehran | 812971060 | 9.78081297106e+12 | '812971060': check digit is wrong even after restoring 1 leading zero(s) (expected X) |
| 1096 | 213753 | Life As We Knew It (Last Survivors, #1) | 152061548 | — | '152061548': check digit is wrong even after restoring 1 leading zero(s) (expected 1) |
| 1444 | 11827808 | The Secret of the Nagas (Shiva Trilogy #2) | 9380658797 | 97893806587.0 | '9380658797': check digit is wrong (expected 6) |
| 1544 | 13573236 | The Racketeer | 385535144 | 9.78038553514e+12 | '385535144': check digit is wrong even after restoring 1 leading zero(s) (expected 7) |
| 1628 | 3507 | Twelve Sharp (Stephanie Plum, #12) | 312349486 | 9.78031234949e+12 | '312349486': check digit is wrong even after restoring 1 leading zero(s) (expected 3) |
| 2375 | 292408 | Angle of Repose | 140169300 | 9.7801401693e+12 | '140169300': check digit is wrong even after restoring 1 leading zero(s) (expected X) |
| 2600 | 15861491 | The Fall of Five (Lorien Legacies, #4) | 61974618 | 9.78006197462e+12 | '61974618': check digit is wrong even after restoring 2 leading zero(s) (expected 7) |
| 2779 | 1672727 | Two-Way Street | 1416913184 | 9.78141691318e+12 | '1416913184': check digit is wrong (expected 1) |
| 3301 | 13154952 | Calico Joe | 385536073 | 9.78038553607e+12 | '385536073': check digit is wrong even after restoring 1 leading zero(s) (expected 0) |
| 3395 | 2177236 | Hold Tight | 525950608 | 9.78052595061e+12 | '525950608': check digit is wrong even after restoring 1 leading zero(s) (expected 5) |

…and 13 more in `1-books-issues.csv`.

### `missing_year` — 21 row(s)

Publication year was left blank, not guessed. **What to do:** Add the year if known; the next import will fill it in.

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 221 | 3609760 | Twilight: The Complete Illustrated Movie Companion | 316043133 | 9.78031604314e+12 | publication year is blank |
| 977 | 90072 | Dr. Seuss's Green Eggs and Ham: For Soprano, Boy Soprano, and Orchestra | 793551617 | 9.78079355161e+12 | publication year is blank |
| 3507 | 856917 | Absolute Boyfriend, Vol. 1 | 1421500167 | 9.78142150016e+12 | publication year is blank |
| 4230 | 36 | The Lord of the Rings: Weapons and Warfare | 618391002 | 9.780618391e+12 | publication year is blank |
| 4249 | 8724779 | Marked / Betrayed / Chosen / Untamed / Hunted (House of Night #1-5) | 312530641 | 9.78031253065e+12 | publication year is blank |
| 4411 | 349254 | The Lord of the Rings: The Return of the King: Visual Companion | 618390979 | 9.78061839098e+12 | publication year is blank |
| 4709 | 9832370 | BookRags Summary:  A Storm of Swords | — | — | publication year is blank |
| 4772 | 5171894 | The Doomsday Key (Sigma Force, #6) | 61231401 | 9.78006123141e+12 | publication year is blank |
| 4879 | 17733861 | A Shade of Blood (A Shade of Vampire, #2) | — | — | publication year is blank |
| 5611 | 1044141 | The 8th Habit: From Effectiveness to Greatness | 743287932 | 9.78074328794e+12 | publication year is blank |

…and 11 more in `1-books-issues.csv`.

### `isbn_conflict` — 12 row(s)

The isbn and isbn13 columns point to different publications, so neither was stored as the book's ISBN. **What to do:** Decide which edition this record describes and correct the source row.

| Row | Goodreads ID | Title | isbn | isbn13 | Detail |
|---:|---|---|---|---|---|
| 623 | 15926 | Nights in Rodanthe | 446612707 | 9.78055381395e+12 | isbn '446612707' is ISBN-13 9780446612708, which doesn't match isbn13 '9.78055381395e+12' |
| 1028 | 18705209 | The Blood of Olympus (The Heroes of Olympus, #5) | 1484724917 | 9.78142314674e+12 | isbn '1484724917' is ISBN-13 9781484724910, which doesn't match isbn13 '9.78142314674e+12' |
| 1107 | 17267 | The Great Divorce | 6280560 | 9.79000767239e+12 | isbn '6280560' is ISBN-13 9780006280569, which doesn't match isbn13 '9.79000767239e+12' |
| 4352 | 828084 | Pictures of Hollis Woods | 439692393 | 9.78044041579e+12 | isbn '439692393' is ISBN-13 9780439692397, which doesn't match isbn13 '9.78044041579e+12' |
| 4502 | 244383 | Ask and It Is Given: Learning to Manifest Your Desires | 1401904599 | 9.78819041695e+12 | isbn '1401904599' is ISBN-13 9781401904593, which doesn't match isbn13 '9.78819041695e+12' |
| 5184 | 16116760 | Silence (Silence, #1) | 1480118516 | 9.78130144243e+12 | isbn '1480118516' is ISBN-13 9781480118515, which doesn't match isbn13 '9.78130144243e+12' |
| 7143 | 513367 | In Search of Schrödinger's Cat: Quantum Physics and Reality | 553341030 | 9.78055334254e+12 | isbn '553341030' is ISBN-13 9780553341034, which doesn't match isbn13 '9.78055334254e+12' |
| 7839 | 122649 | Lady Windermere's Fan | 140621733 | 9.78014119794e+12 | isbn '140621733' is ISBN-13 9780140621730, which doesn't match isbn13 '9.78014119794e+12' |
| 7857 | 851678 | What Remains: A Memoir of Fate, Friendship, and Love | 739458736 | 9.78074327695e+12 | isbn '739458736' is ISBN-13 9780739458730, which doesn't match isbn13 '9.78074327695e+12' |
| 8619 | 530793 | The Wives of Henry VIII | 140132937 | 9.78067973002e+12 | isbn '140132937' is ISBN-13 9780140132939, which doesn't match isbn13 '9.78067973002e+12' |

…and 2 more in `1-books-issues.csv`.

## Automatic repairs

Only repairs with exactly one possible answer are made; originals are kept in the audit log.

| Field | Repair | Rows |
|---|---|---:|
| original_publication_year | removed '.0' from a whole-number year | 9,979 |
| isbn13 | isbn13 had lost its last digit(s); rebuilt from the row's valid ISBN-10, which matches the rounded value | 9,239 |
| isbn | restored 1 dropped leading zero(s); only one answer is possible and the check digit confirms it | 5,563 |
| isbn | restored 2 dropped leading zero(s); only one answer is possible and the check digit confirms it | 913 |
| original_title | removed extra whitespace | 382 |
| authors | removed extra whitespace | 168 |
| isbn | restored 3 dropped leading zero(s); only one answer is possible and the check digit confirms it | 111 |
| title | removed extra whitespace | 107 |
| isbn13 | rewrote number format as plain digits; no digits changed | 8 |
