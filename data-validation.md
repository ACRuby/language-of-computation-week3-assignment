# ISBN Data Validation — Diagnosis

Diagnosis only. Neither data file was changed and nothing was fixed.

| File | Source | Rows | Status |
|---|---|---|---|
| `books.csv` | https://raw.githubusercontent.com/zygmuntz/goodbooks-10k/master/books.csv | 10,000 | Diagnosed below |
| `books-batch2.csv` | 200 rows sampled at random from `books.csv` (see below) | 200 | Diagnosed below |

## What counts as a valid ISBN

Checked against ISBN International's definition page, https://www.isbn-international.org/content/what-isbn/10.

- **ISBN-13** (the current standard): the page says that since 1 January 2007 an ISBN always has 13 digits, in five parts:
  - a **prefix**, which "can only be either 978 or 979";
  - a registration group (1–5 digits);
  - a registrant, meaning the publisher (up to 7 digits);
  - a publication number (up to 6 digits);
  - a final **check digit**, worked out with a "Modulus 10 system with alternate weights of 1 and 3".

  So a value is a valid ISBN-13 if it has 13 digits, starts with 978 or 979, and passes that checksum: multiply the digits by weights 1, 3, 1, 3, …, add them up, and the total must be divisible by 10. *This matches the page exactly.*
- **ISBN-10** (used before 2007): the page only says ISBNs were 10 digits before 2007. It does **not** give the ISBN-10 check digit rule or how to convert to 13 digits. The rules used here come from the ISBN standard itself (ISO 2108):
  - exactly 10 characters: 9 digits, then a check digit that is 0–9 or `X` (meaning 10);
  - checksum: multiply the 10 characters by weights 10, 9, …, 1 and add them up; the total must be divisible by 11;
  - converting to ISBN-13: put `978` in front of the first 9 digits and **recalculate** the check digit with the ISBN-13 rule. Only 978 ISBNs have a 10-digit form; 979 ISBNs never had one.

  *Checked against the official ISBN Users' Manual (International ISBN Agency, 7th edition, downloaded from isbn-international.org):* the manual covers **only the 13-digit ISBN** and does **not** describe the ISBN-10 check digit or how to convert ISBN-10 to ISBN-13.
  - It confirms the history: "the original 10-digit ISBN was extended to 13 digits", and since 1 January 2007 agencies "only provide ISBNs that consist of 13 digits".
  - The site's ISBN Calculator page says it can "convert the old 10-digit ISBNs" to 13 digits, but it doesn't explain how and needs a publisher login.
  - So the ISBN-10 rules above rest on ISO 2108 (an earlier edition of the standard) and can't be confirmed from isbn-international.org. They are, however, backed up by the data itself: of the 9,258 rows with both a usable ISBN-10 and an ISBN-13, **9,239 (99.8%) agree** under this conversion. The other 19 look like different editions (see "Cross-column observations").
- **ISBN-13 check digit, as worded in the manual (Appendix 1):** multiply each of the first 12 digits alternately by 1 and 3; the check digit is 10 minus the remainder of the sum divided by 10, and is 0 when the remainder is 0. "The sum of the weighted products of the first 12 digits plus the check digit must be divisible by 10 without a remainder for the ISBN to be valid." *This is the same rule used here.*
- **Leading zeros are part of the number:** the manual (section 5.4) says "blank digits are represented by leading zeros" to keep the ISBN the correct length. So dropping them changes the identifier. It isn't harmless formatting.
- **Hyphens and spaces:** the definition page and the manual both allow the five parts to be separated by hyphens or spaces (e.g. `ISBN 978-0-439-02348-1`). The manual adds that they have "no lexical significance and is purely to enhance readability". So a loader should remove hyphens, spaces and any leading "ISBN" label before checking, not reject the value. Neither file contains any of these, so this changes none of the counts below.
- **How to store it:** the manual's required metadata table lists the ISBN "In the 13-digit ISBN format, without spaces or hyphens". That is a sensible target format for loaded rows.
- **Limits of a checksum:** passing the checksum shows the number is well formed. It does not prove the number was actually assigned to a book, or to *this* book. The page notes that each product form (paperback, EPUB, PDF) gets its own ISBN. That is why two valid ISBNs on the same row can point to different editions (see "Cross-column observations").

A value is valid only if it is valid **exactly as written in the file**. Where a value could become valid with a mechanical repair (such as adding back leading zeros), that is called out separately as *recoverable*. Recovery is not done here.

### Worked example (book_id 1, *The Hunger Games*)

- **In the file:** `isbn` = `439023483`, `isbn13` = `9.78043902348e+12`.
- **Restore the ISBN-10:** add the missing leading zero to get `0439023483`. Checksum: 0·10 + 4·9 + 3·8 + 9·7 + 0·6 + 2·5 + 3·4 + 4·3 + 8·2 + 3·1 = 176 = 16 × 11, so it is **valid**.
- **Convert to ISBN-13:** `978` + `043902348` + new check digit `1` gives `9780439023481`. Checksum with weights 1, 3, 1, 3, … totals 100, which is divisible by 10, so it is **valid**.
- **Compare with the file:** the stored `isbn13` reads `978043902348` with the final `1` missing.

---

## `books.csv` — `isbn` column (ISBN-10)

| Category | Rows | Example (book_id → value) | Valid as written? |
|---|---:|---|---|
| Valid ISBN-10 | 2,690 | 11 → `1594480001` (*The Kite Runner*); 18 → `043965548X` | Yes |
| Leading zeros dropped (1 zero missing, 9 chars) | 5,563 | 1 → `439023483` should be `0439023483` (*The Hunger Games*) | No; recoverable |
| Leading zeros dropped (2 zeros missing, 8 chars) | 913 | 4 → `61120081` should be `0061120081` (*To Kill a Mockingbird*) | No; recoverable |
| Leading zeros dropped (3 zeros missing, 7 chars) | 111 | 69 → `7442912` should be `0007442912` (*Insurgent*) | No; recoverable |
| Empty | 700 | 106 → `` (*Bossypants*) | No |
| Checksum fails (even after adding back zeros) | 23 | 1543 → `385535144` (*The Racketeer*); correct check digit would be `7` | No |
| **Total** | **10,000** | | |

### Problem details

**1. Leading zeros dropped: 6,587 rows (65.9%)**
- *What's wrong:* the value is shorter than 10 characters. Adding `0`s to the front until it is 10 long makes the checksum pass every time, so the only defect is the missing zeros.
- *Probable cause:* the column was treated as a **number**, not text, at some point (in a spreadsheet, or a pandas/CSV reader guessing the type). Numbers don't keep leading zeros, so `0439023483` became `439023483`. The giveaway is that **all 814 ISBNs ending in `X` kept their leading zeros** (e.g. `043965548X`). `X` isn't a digit, so those values could never be read as numbers and stayed text.

**2. Empty: 700 rows (7.0%)**
- *What's wrong:* no ISBN-10 at all.
- *Probable cause:* the book (as Goodreads catalogs it) has no ISBN-10. Many are ebook-only or self-published editions. 135 of these rows do have an `isbn13` value, and 565 have neither column filled in.

**3. Checksum failure: 23 rows (0.2%)**
- *What's wrong:* the value has (or can be padded to) the right shape, but the check digit is wrong. 9 are full 10-digit values (e.g. 2778 → `1416913184`) and 14 are short values that still fail after padding (e.g. 1543 → `385535144`).
- *Probable cause:* **20 of the 23** end in the check digit from the book's ISBN-13 rather than the correct ISBN-10 check digit. ISBN-10 and ISBN-13 use different checksum formulas. These were probably made by stripping `978` off an ISBN-13 and forgetting to recalculate the last digit. The remaining 3 look like data-entry errors:
  - 916 `812971060`: the check digit should be `X`, and `X` appears to have been replaced by `0`.
  - 4322 `1400139027`: digits shifted compared with its own isbn13 `978140139027…`.
  - 8552 `84386874`: digits don't match its isbn13 `978084238688…` at all.

---

## `books.csv` — `isbn13` column (ISBN-13)

**No value in this column is a valid ISBN-13 as written: 0 of 10,000.**

| Category | Rows | Example (book_id → value) |
|---|---:|---|
| Scientific notation, real ISBN prefix (978/979) | 9,382 | 1 → `9.78043902348e+12` (*The Hunger Games*) |
| Scientific notation, not an ISBN (prefix `2940`) | 22 | 1165 → `2.94001623192e+12` (*Wait for You*) |
| Scientific notation, not an ISBN (other barcodes/junk) | 6 | 2894 → `6.45573003012e+11` (*Sailor Moon #1*); 8941 → `1.2300000055e+12` |
| Decimal number with `.0` suffix, wrong length | 5 | 1443 → `97893806587.0`; 8174 → `195170342.0` |
| Empty | 585 | 106 → `` (*Bossypants*) |
| **Total** | **10,000** | |

### Problem details

**1. Scientific notation: 9,410 rows (94.1%)**
- *What's wrong:* the value is a floating-point number like `9.78043902348e+12`, not a 13-digit string. Written out, it shows only **12 significant digits**, so the 13th digit (the check digit) is **lost**. The value was **rounded**, not cut off. Comparing each one with the ISBN-13 rebuilt from the same row's ISBN-10 (9,250 rows where both are usable) gave:
  - 929 match exactly, because the real check digit happened to be 0;
  - 4,105 were rounded down, so the 12 visible digits are correct and only the 13th is missing;
  - **4,204 were rounded up**, so the 12th visible digit is too high by one. Example: book 10 shows `9.78067978327e+12`, but the real ISBN-13 is `9780679783268`;
  - 12 don't match the ISBN-10 at all (different editions).

  So taking the 12 visible digits and recalculating a check digit would give a **wrong ISBN for about 45% of rows**. These values can't be checked or restored from this column alone.
- *Probable cause:* the same number conversion as above, but worse. A 13-digit number stored as a float and written back out with default formatting (12 significant digits) becomes scientific notation. Trailing zeros get trimmed too, which is why some show fewer digits (e.g. 2374 → `9.7801401693e+12`).
- *Note:* for most of these rows the full ISBN-13 could be rebuilt from the `isbn` column, since an ISBN-10 converts to an ISBN-13 by a fixed rule. That is a fix and was not done.

**2. Not an ISBN at all: 28 rows** (all also in scientific notation)
- *What's wrong:* the number doesn't start with 978/979, so it isn't an ISBN even before the digit loss.
  - **22 rows start with `2940`.** This is the Barnes & Noble internal product code for Nook ebooks. Every one of these rows has an empty `isbn`, which fits ebook-only books with no real ISBN.
  - **3 rows look like 12-digit UPC retail barcodes** (`e+11`, e.g. 2894 Sailor Moon, 3689, 5268).
  - **2 rows start with `622`**, the GS1 country prefix for Egypt (Arabic-language books 5647 and 8247). These are product barcodes, not ISBNs.
  - **1 row is a placeholder-looking value**: 8941 → `1.2300000055e+12`.
- *Probable cause:* the source catalog (Goodreads) stores whatever barcode it has when a book lacks an ISBN-13, and this column took it in unchecked.

**3. Decimal with `.0` and wrong length: 5 rows**
- *What's wrong:* a value like `97893806587.0` is an 11-digit decimal number. It's too short to be an ISBN-13, and the `.0` shows it went through a float.
- *Probable cause:* the same float conversion, applied to values that were already wrong or truncated:
  - 958 `76783609419.0`: a UPC barcode missing its leading 0.
  - 1443 `97893806587.0`: an ISBN-13 cut off after 11 digits.
  - 6142 and 6437: UPC-style barcodes.
  - 8174 `195170342.0`: the book's ISBN-10 body (same as its `isbn` column) put in the wrong column.

**4. Empty: 585 rows (5.9%)**
- *What's wrong:* no ISBN-13.
- *Probable cause:* the book has no ISBN-13 in the source. 565 of these have no ISBN-10 either. 20 do have an `isbn` value, so their ISBN-13 could be derived.

---

## Cross-column observations (`isbn` vs `isbn13`)

- **The columns disagree in 19 rows.** In these rows the ISBN-10 is valid, or becomes valid with its zeros added back, but it does not match the `isbn13` value. Examples:
  - 622: `446612707` vs `9.78055381395e+12`
  - 1027: `1484724917` vs `9.78142314674e+12`

  These most likely belong to **different editions** of the same book (a different publisher or format). Neither column is "wrong" on its own, but a row shouldn't claim two different books.
- **Both columns empty in 565 rows (5.7%).** These books have no ISBN of any kind in this file.
- **No duplicate `isbn` values** among non-empty rows, and **no stray whitespace** in either column.

## Summary for `books.csv`

| | ISBN-10 (`isbn`) | ISBN-13 (`isbn13`) |
|---|---:|---:|
| Valid as written | 2,690 (26.9%) | **0 (0%)** |
| Invalid, but mechanically recoverable | 6,587 (leading zeros) | most of 9,382 (rebuild from ISBN-10) |
| Invalid, not ISBN / not recoverable from this column | 23 | 33 |
| Empty | 700 | 585 |

**Main root cause:** the ISBN columns were handled as **numbers instead of text** somewhere upstream. That one mistake explains the dropped leading zeros, the scientific notation, the lost check digits, and the `.0` suffixes, which together cover about 96% of all problem values. Any loader must read both columns as text and never trust the type a tool guesses.

## Is the information still there, or is it lost?

| Problem | Information still there? | Why |
|---|---|---|
| ISBN-10 missing leading zeros | **Still there** | An ISBN-10 is always exactly 10 characters, so the number of zeros that went missing is known (10 minus the length). Adding them back can only give one answer, and the checksum confirms it. |
| ISBN-13 in scientific notation | **Lost from this column** | The check digit is gone, and in 45% of rows the 12th digit was rounded up. For 978 books it can be **rebuilt from the `isbn` column**, but only when that column is valid and describes the same edition. 979 ISBNs have no ISBN-10 form, so there is no backup for them. |
| ISBN-10 with wrong check digit | **Uncertain** | The first 9 digits are probably correct (in 20 of 23 rows only the check digit is wrong), but that can't be proven from the file. Recalculating the check digit would be a guess. |
| Not an ISBN (Nook `2940…` codes, UPC barcodes, placeholders) | **Never there** | These books have no ISBN in the source. There is nothing to restore. |
| Truncated `.0` values | **Lost** | Digits are missing from the end, and nothing says what they were. |
| Empty cells | **Never there** | Nothing was recorded. |

---

## `books-batch2.csv`

### How the file was made

200 data rows were picked at random from the 10,000 in `books.csv`, without replacement, using Python's `random.Random(5523).sample(...)`. The fixed seed (5523, from the course number) means the same 200 rows can be picked again exactly. Each line was copied **byte-for-byte** from `books.csv`, with the same header and no reformatting, so every data problem below is the original problem and not something added while copying. The rows are in the random order they were drawn, not sorted by `book_id`.

### `isbn` column (ISBN-10)

| Category | Rows | Example (book_id → value) |
|---|---:|---|
| Valid ISBN-10 | 42 | 8101 → `1416577572`; 9950 → `145553322X` |
| Leading zeros dropped (1 missing) | 115 | 4766 → `439014573` (*Captain Underpants*) |
| Leading zeros dropped (2 missing) | 23 | 9348 → `61143316` (*Promise Not to Tell*) |
| Leading zeros dropped (3 missing) | 1 | 4497 → `7208006` (*The Tea Rose*) |
| Empty | 17 | 5451 → `` (*Perahu Kertas*) |
| Checksum fails | 2 | 3473 → `1847386823`; 1095 → `152061548` |
| **Total** | **200** | |

Both checksum failures are the "ISBN-13 check digit on an ISBN-10" kind described above. All 14 values ending in `X` kept their leading zeros, which again points to the numbers-not-text cause.

### `isbn13` column (ISBN-13)

**0 of 200 are valid as written.**

| Category | Rows | Example (book_id → value) |
|---|---:|---|
| Scientific notation, 978/979 prefix (check digit lost) | 186 | 4766 → `9.78043901457e+12` |
| Scientific notation, not an ISBN | 1 | 8941 → `1.2300000055e+12` (placeholder-looking value) |
| Empty | 13 | 742 → `` (*Wool Omnibus*) |
| **Total** | **200** | |

### Cross-column

- **Both columns empty:** 12 rows. `isbn` empty but `isbn13` present: 5. `isbn13` empty but `isbn` present: 1.
- **Columns disagree:** 0 rows in this sample.

### Compared with `books.csv`

- **No new kinds of problem.** Every problem in batch 2 is one already described for `books.csv`, and it shows up at about the same rate. For example, 70% of ISBN-10s have dropped zeros here vs. 66% in the full file, and 0% of ISBN-13s are valid in both. The sample didn't happen to draw any `2940` Nook codes, UPC barcodes or `.0` decimals.
- **Every one of the 200 rows is already in `books.csv`.** That includes the same `book_id`, the same ISBNs and an identical line. If `books.csv` is loaded first and then `books-batch2.csv`, **a correct loader must add zero new books from batch 2.** This is exactly the "never load the same book twice" case. Note too that **12 batch-2 rows have no ISBN at all**, so duplicates can't be detected by ISBN alone. Something like `book_id` (or `goodreads_book_id`) is needed to recognize them.
