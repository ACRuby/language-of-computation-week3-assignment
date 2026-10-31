# language-of-computation-week3-assignment

This is my Module 3 assignment for MSAI-5523.

## What this project does

Every night a new file of books arrives, and many of its ISBN numbers are broken. This project's program reads the file and checks every book on it. It fixes only what can be fixed without guessing, saves the good books into a small database, never saves the same book twice, and writes down what happened so a person can check it the next morning.

You can read what happened in two ways:
- **a web page** (`report.html`) that opens in your browser;
- **an Excel file** (`ingestion-report.xlsx`).

---

## How to run it, step by step

You don't need any programming knowledge. You'll copy a line, paste it into a window, and press **Enter**. Do the steps in order.

### Step 1: Open PowerShell

PowerShell is a window where you type commands for your computer.

1. Press the **Windows key** on your keyboard (the key with the Windows logo).
2. Type **PowerShell**.
3. Click **Windows PowerShell** in the list.

A window opens with some text, and a line that ends with `>`. For example:

```
PS C:\Users\abiga>
```

That line is where you type. It's called the **prompt**.

### Step 2: Go to the project folder

The program only works if PowerShell is "standing in" the project folder.

1. Copy this line (select it, then press **Ctrl + C**):

   ```bash
   cd ~\workspace\language-of-computation\week3-assignment
   ```

2. Click inside the PowerShell window.
3. Paste it by pressing **Ctrl + V** (or right-click).
4. Press **Enter**.

**Check:** the prompt should now end with `week3-assignment>`, like this:

```
PS C:\Users\abiga\workspace\language-of-computation\week3-assignment>
```

If it does, you're in the right place. If you close PowerShell later, do Step 2 again when you reopen it.

### Step 3: Check that Python works

Python is the program that runs this project's code. It's already installed on this computer.

Copy, paste and press **Enter**:

```bash
py -3.13 --version
```

**You should see:**

```
Python 3.13.16
```

(The last number may differ. Anything starting with `Python 3.13` is fine.)

> Always type `py -3.13`, never `python3`. On Windows, `python3` opens the Microsoft Store instead of running Python.

### Step 4: Load the books

This reads `books.csv` (the list of 10,000 books), checks every row, and saves the books into the database file `books.db`.

Copy, paste and press **Enter**:

```bash
py -3.13 ingest.py books.csv
```

It takes a few seconds. **You should see something like:**

```
COMPLETED WITH ISSUES: read 10000, loaded 0, updated 0, skipped (already exist) 10000, rejected 0 | repaired 9998, with warnings 753
Run 20261031T150212-a1b2c3 added to ingestion-log.json. Open report.html to read it.
```

What the words mean:

| Word | Meaning |
|---|---|
| **COMPLETED WITH ISSUES** | It finished. Some books need a person to look at them (see Step 6). |
| **read** | How many books were in the file. |
| **loaded** | New books saved for the first time. |
| **updated** | Books already saved, but something like their rating changed. |
| **skipped (already exist)** | Books already saved and unchanged, so nothing was done. This is how duplicates are prevented. |
| **rejected** | Books that couldn't be saved, for example because the title is missing. |
| **repaired** | Books where something was fixed safely, such as a missing zero at the start of an ISBN. |
| **with warnings** | Books saved, but with something a person should check, such as no usable ISBN. |

**Why "loaded 0"?** The database that comes with this project already holds all 10,000 books, so they're all **skipped**. That's correct: loading the same file again must never create duplicates. (On an empty database you'd see `loaded 10000`.)

Every time you do this step, one new entry is added to the log file `ingestion-log.json`. Earlier entries are never erased.

### Step 5: Load the second file

`books-batch2.csv` is a second file of 200 books. All of them are already in `books.csv`, so this shows that duplicates are skipped.

Copy, paste and press **Enter**:

```bash
py -3.13 ingest.py books-batch2.csv
```

**You should see** `read 200, loaded 0, ... skipped (already exist) 200, rejected 0`.

### Step 6: See the results in your web browser

1. Open **File Explorer** (the yellow folder icon on your taskbar).
2. Click the **address bar** at the top of the window, paste this, and press **Enter**:

   ```
   C:\Users\abiga\workspace\language-of-computation\week3-assignment
   ```

3. Double-click **report.html**. It opens in your web browser.
4. Click the blue button **Open ingestion-log.json**.
5. In the window that appears, click **ingestion-log.json**, then click **Open**.

You'll see one box for each time the program ran, **newest at the top**. Each box shows:
- a coloured label: **green** = everything fine, **yellow** = finished but something needs checking, **red** = it failed and nothing was saved;
- the numbers from Step 4;
- **Actions required**: what a person should do next;
- **Rows not loaded**: every rejected book, why, and what to do about it;
- **Rows loaded with warnings**: click this line to open the list.
- **Notes: accepted without ISBN**: books a person confirmed as ebook or self-published (see Step 10).

Nothing is sent to the internet. The page just reads the file on your computer.

### Step 7: Make the Excel report

Go back to the PowerShell window. Copy, paste and press **Enter**:

```bash
py -3.13 make_report.py
```

**You should see something like:**

```
Wrote ingestion-report.xlsx: Runs: 6 row(s), Rows not loaded: 3 row(s), Warnings: 2,381 row(s)
```

Then, in the File Explorer window from Step 6, double-click **ingestion-report.xlsx** to open it in Excel.

It has four tabs at the bottom:

| Tab | What's on it |
|---|---|
| **Runs** | One line per run, newest first, with its numbers. The status is coloured green, yellow or red. |
| **Rows not loaded** | Every book that was rejected, why, and what to do. |
| **Warnings** | Every book that was saved but needs checking. |
| **Notes** | Books accepted without an ISBN because a person confirmed they're an ebook or self-published (see Step 10). |

You can sort or filter any column with the small arrow in its heading.

The Excel file is a snapshot. After you load a file again (Step 4 or 5), repeat this step to update it.

### Step 8 (optional): Run the automatic checks

The project comes with 104 automatic tests that check the program follows the rules. Copy, paste and press **Enter**:

```bash
py -3.13 -m unittest discover tests
```

It takes about 10 seconds. First you'll see a row of dots: each dot is a test that passed, and each `s` is a skipped test. At the end **you should see:**

```
----------------------------------------------------------------------
Ran 104 tests in 8.113s

OK (skipped=2)
```

`OK` means every test passed. The 2 skipped tests are for things this data doesn't have (publishers and library inventory). The time will be different.

---

## Fixing books with warnings: looking up missing ISBNs

Some books load with a warning because their ISBN or year is missing or broken. The program never guesses, so a person has to supply the right information. These steps help you find it on **Open Library** (a free online library catalog) and approve it.

You only need these steps when you want to clear warnings. They're never part of the nightly load.

### Step 9: Look up suggestions on Open Library

In PowerShell (still in the project folder from Step 2), copy, paste and press **Enter**:

```bash
py -3.13 lookup_isbns.py
```

The first time, this takes about **13 minutes**. It checks one book per second, as Open Library asks. You'll see progress lines like `  250/753 books looked up`. The answers are saved in `open-library-cache.json`, so running it again later takes only seconds.

When it's done, it writes **`isbn-suggestions.csv`**: one row per book that has a warning.

### Step 10: Check the suggestions in Excel

1. In File Explorer (the project folder from Step 6), double-click **isbn-suggestions.csv**. It opens in Excel.
2. For each book you want to fix, look at these columns:

| Column | What it tells you |
|---|---|
| `title`, `authors` | The book |
| `problem` | What's wrong (e.g. no usable ISBN, missing year) |
| `suggested_isbn13s` | ISBNs Open Library has for this book. **A book has a different ISBN for each edition** (hardcover, paperback, UK edition…), so you pick one. |
| `suggested_year` | The year Open Library says the book was first published |
| `format_hint` | A clue that the book may be an ebook or self-published (only a clue) |
| `open_library_link` | Copy it into your browser to see the book's editions and check which one matches |
| `lookup_result` | `found`, `not found on Open Library`, or an error |

3. For a book you've checked, fill in the **approval columns** on the same row:

| Column | What to type |
|---|---|
| `approved_isbn13` | The ISBN you chose, **with the word ISBN in front**, e.g. `ISBN 9780316175869`. (Copy it from `suggested_isbn13s`.) Without the word ISBN, Excel turns the number into something like `9.78032E+12` and ruins it. |
| `approved_year` | The publication year, if it was missing, e.g. `2011` |
| `approved_no_isbn_reason` | Only if the book really has no ISBN: type `ebook` or `self-published` |
| `approved_by` | **Your name.** A row without a name isn't approved and is ignored. |

Leave a row's approval columns empty if you haven't checked that book. You don't have to do them all at once.

### Step 11: Save your approvals as isbn-corrections.csv

1. In Excel, click **File → Save As**.
2. Choose the project folder (`week3-assignment`).
3. In **File name**, type: `isbn-corrections`
4. In **Save as type**, choose **CSV UTF-8 (Comma delimited) (\*.csv)**.
5. Click **Save**. If Excel warns that some features may be lost, click **Yes** (or **Keep Current Format**).
6. Close Excel before the next step.

### Step 12: Load the books again

Back in PowerShell, copy, paste and press **Enter**:

```bash
py -3.13 ingest.py books.csv
```

You'll now see an extra line, for example:

```
Corrections from isbn-corrections.csv: 40 applied, 12 accepted without ISBN, 0 unusable
```

- **applied:** books whose ISBN or year was filled in from your approvals. Their warnings are gone.
- **accepted without ISBN:** books you marked as `ebook` or `self-published`. They pass without an ISBN and appear as **notes**, not warnings.
- **unusable:** approvals that broke a rule, e.g. an ISBN Excel turned into a number. Open the report (Step 6) to see which ones and why.

Then make the Excel report again (Step 7) to see the results.

**When will the run be green (SUCCESS)?** Only when every book in the file either has no problems or has been fixed by an approval. Books Open Library can't find keep their warning until someone finds the information elsewhere.

---

## If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `can't open file ... No such file or directory` | PowerShell isn't in the project folder. | Do Step 2 again, then try again. |
| `Python was not found; run without arguments to install from the Microsoft Store` | You typed `python3` or `python`. | Type `py -3.13` instead, exactly as shown. |
| `'py' is not recognized` or a message that Python 3.13 can't be found | Python 3.13 isn't installed on this computer. | Install Python 3.13 from python.org, close PowerShell, then start again at Step 1. |
| `PermissionError` when making the Excel report | The Excel file is still open in Excel. | Close it in Excel, then run Step 7 again. |
| `ERROR: ingestion-log.json is not valid JSON` | The log file was damaged, for example by editing it by hand. Nothing was loaded. | Get the original back from GitHub with `git checkout -- ingestion-log.json`, then try again. |
| The web page shows only a button | That's normal: the page waits for you to choose the log file. | Do Step 6, parts 4 and 5. |
| The status is **FAILED** (red) | The program stopped and saved nothing, so the database is unchanged. | Read the **Error** line in that run's box, fix what it says, and run the step again. |
| `isbn-corrections.csv is missing required column(s)` | The corrections file isn't the suggestions file saved under a new name, or a column was deleted. | Redo Step 11 from `isbn-suggestions.csv` without deleting columns. |
| A warning called `correction_invalid` | One of your approvals broke a rule. The reason is in the report, e.g. "Excel probably turned it into a number". | Fix that row in `isbn-corrections.csv` (type `ISBN 978…`), save, and run Step 12 again. |
| A warning called `correction_not_applied` | Your approval would replace a valid value already in the book file. Approvals only fill gaps. | Remove that approval if the file's value is right. |
| `lookup_result` says `error` | Open Library didn't answer (no internet, or it's busy). | Run Step 9 again later. Only the failed books are looked up again. |

---

## Fixing rejected books (advanced)

If a run rejects some books, you can fix them in a copy of the file, for example `fixed-rows.csv`, and load just that file. Add the run ID of the run that rejected them, so the fix is linked to it. The run ID is shown in the report, for example `20261031T143449-0c8457`.

```bash
py -3.13 ingest.py fixed-rows.csv --reprocess-of 20261031T143449-0c8457
```

---

## What's in this folder

| File | What it is |
|---|---|
| [data-validation.md](data-validation.md) | What's wrong with the ISBNs in the book files, and how often |
| [rules.md](rules.md) | The rules the program must follow: what to fix, reject or flag, how duplicates are found, and what the report must say |
| [implementation.md](implementation.md) | How the program follows the rules, the tests, and what it can't do |
| `ingest.py` | **The main program:** loads a book file into `books.db` and adds an entry to `ingestion-log.json` |
| `report.html` | The web page that shows `ingestion-log.json` |
| `make_report.py` | Makes the Excel file `ingestion-report.xlsx` from `ingestion-log.json` |
| `books.db` | The database of saved books |
| `ingestion-log.json` | The record of every run |
| `ingestion-report.xlsx` | The Excel report |
| `books.csv` | The 10,000 books, from [goodbooks-10k](https://github.com/zygmuntz/goodbooks-10k), unchanged |
| `books-batch2.csv` | 200 books picked at random from `books.csv` |
| `lookup_isbns.py` | Looks up suggested ISBNs and years on Open Library (Step 9). Uses the internet, so it's never part of the nightly load. |
| `isbn-suggestions.csv` | What the lookup found, with empty approval columns for you to fill in |
| `isbn-corrections.csv` | Your approved corrections (Step 11), read by `ingest.py` |
| `open-library-cache.json` | Saved Open Library answers, so nothing is looked up twice |
| `corrections.py` | Helper code that checks and applies approved corrections |
| `isbn.py`, `validate.py` | Helper code with the ISBN and row rules, used by `ingest.py` |
| `import_books.py`, `report.py` | An earlier version of the program (makes `library.db` and reports in `reports/`) |
| `tests/` | The automatic tests from Step 8 |
| `examples/` | Example reports from the earlier version |
