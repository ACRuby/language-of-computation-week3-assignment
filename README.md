# language-of-computation-week3-assignment

This is my Module 3 assignment for MSAI-5523, updated to follow the **group's agreed rules** (Kristina, Anthony and Abigail, 2026-11-06).

## What this project does

Every night a new file of books arrives, and many of its ISBN numbers are broken. This project's program reads the file and checks every book on it. It fixes only what can be fixed without guessing, saves the books into a small database, never saves the same book twice, and writes down what happened so a person can check it the next morning.

The rules it follows are in [rules.md](rules.md) (the group's agreed rules, plus a section 5 that records how this build fills the gaps). The database layout is in [erd.md](erd.md). [run-instructions.md](run-instructions.md) is the short version of these steps.

You can read what happened in two ways:
- **a web page** (`report.html`) that opens in your browser;
- **an Excel file** (`ingestion-report.xlsx`).

---

## How to run it, step by step

You don't need any programming knowledge. You'll copy a line, paste it into a window, and press **Enter**. Do the steps in order.

### Step 1: Open PowerShell

1. Press the **Windows key** on your keyboard.
2. Type **PowerShell**.
3. Click **Windows PowerShell** in the list.

A window opens with a line that ends with `>`, for example `PS C:\Users\abiga>`. That's where you type.

### Step 2: Go to the project folder

Copy this line, click in the PowerShell window, paste it (**Ctrl + V**), and press **Enter**:

```bash
cd ~\workspace\language-of-computation\week3-assignment
```

**Check:** the line should now end with `week3-assignment>`. If you close PowerShell later, do this step again.

### Step 3: Check that Python works

```bash
py -3.13 --version
```

**You should see** something starting with `Python 3.13`.

> Always type `py -3.13`, never `python3`. On Windows, `python3` opens the Microsoft Store instead of running Python.

### Step 4: Load the books

This reads `books.csv` (10,000 books), checks every row, and saves the books into `books.db`.

```bash
py -3.13 ingest.py
```

It takes about 20 seconds. **You should see one line:**

```
status=COMPLETED WITH ISSUES rows_read=10000 loaded=0 updated=0 skipped=10000 rejected=0 rows_with_warning=723
```

What the words mean:

| Word | Meaning |
|---|---|
| **status** | **SUCCESS** = every row loaded with no warnings. **COMPLETED WITH ISSUES** = it finished, but some rows were rejected or carry a warning. **FAILED** = the file couldn't be read, or something stopped the run partway. |
| **rows_read** | How many books were in the file. |
| **loaded** | New books saved for the first time. |
| **updated** | Books already saved where something changed, like the rating. |
| **skipped** | Books already saved and unchanged, so nothing was done. This is how duplicates are prevented. |
| **rejected** | Rows that weren't saved, and need a person. |
| **rows_with_warning** | Books saved, but with something a person should check, such as no usable ISBN. |

**Why "loaded=0"?** The database that comes with this project already holds all 10,000 books, so they're all **skipped**. That's correct: loading the same file again must never create duplicates. On an empty database you'd see `loaded=10000`.

Every time you do this step, one new entry is added to `ingestion-log.json`. Earlier entries are never erased.

### Step 5: Load the second file

`books-batch2.csv` has 200 books, all of which are also in `books.csv`. There are no command-line options, so this line tells the program which file to use:

```bash
py -3.13 -c "import ingest; print(ingest.summary_line(ingest.run(ingest.HERE / 'books-batch2.csv')))"
```

**You should see** `rows_read=200 loaded=0 updated=0 skipped=200 rejected=0 rows_with_warning=18`.

(Another way: open `ingest.py` in Notepad, change `CSV_FILENAME = "books.csv"` near the top to `"books-batch2.csv"`, save, and run Step 4 again. Change it back afterwards.)

### Step 6: See the results in your web browser

1. Open **File Explorer** (the yellow folder icon on your taskbar).
2. Click the **address bar**, paste this, and press **Enter**:

   ```
   C:\Users\abiga\workspace\language-of-computation\week3-assignment
   ```

3. Double-click **report.html**. It opens in your web browser.
4. Click the blue button **Open ingestion-log.json**, choose **ingestion-log.json**, and click **Open**.

You'll see one box for each run, **newest at the top**, with a coloured label (green / yellow / red) and the numbers from Step 4. **Click a box** to open it and see:
- **Rejected rows: need a person**: every rejected row, the rule it broke, and what the system did;
- **Breakdown by rule**: how many times each rule applied (the codes are explained in `rules.md` section 5);
- **Warnings**, **Updated fields (old → new)** and **Repairs**: click each line to open its list.

Boxes marked **earlier rules** are runs from before the group's agreed rules. They're kept because the log is never erased.

Nothing is sent to the internet. The page just reads the file on your computer.

### Step 7: Make the Excel report

```bash
py -3.13 make_report.py
```

Then double-click **ingestion-report.xlsx** in File Explorer. It has six tabs: **Runs**, **Rejected**, **Warnings**, **Updates**, **Repairs** and **Breakdown by rule**. You can sort or filter any column with the small arrow in its heading. After loading a file again, repeat this step to update it.

### Step 8 (optional): Run the automatic checks

```bash
py -3.13 -m unittest discover tests
```

You'll see a row of dots (each one a passed test), then:

```
Ran 51 tests in 1.3s

OK
```

---

## If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `can't open file ... No such file or directory` | PowerShell isn't in the project folder. | Do Step 2 again. |
| `Python was not found` | You typed `python3` or `python`. | Type `py -3.13` instead. |
| `PermissionError` when making the Excel report | The Excel file is open. | Close it in Excel, then run Step 7 again. |
| `ingestion-log.json exists but is not a readable JSON list` | The log was damaged, for example by editing it by hand. Nothing was loaded. | Get the original back with `git checkout -- ingestion-log.json`, then try again. |
| `status=FAILED` | The run stopped. **Rows before the stop may already be saved** (the group did not adopt a "failed run saves nothing" rule). | Read the `error:` line, fix what it says, and run again. Re-running is safe: books already saved are skipped. |

---

## What's in this folder

| File | What it is |
|---|---|
| [rules.md](rules.md) | The group's agreed rules, plus section 5: this build's gap decisions and the list of rule codes |
| [erd.md](erd.md) | The agreed database layout (`books` + `warnings`) |
| [run-instructions.md](run-instructions.md) | Short reference for running the program and reading the report |
| [data-validation.md](data-validation.md) | The original diagnosis of what's wrong with the ISBNs |
| [implementation.md](implementation.md) | How the code follows the rules |
| `ingest.py` | **The main program:** loads a book file into `books.db` and adds an entry to `ingestion-log.json` |
| `isbn.py`, `validate.py` | Helper code with the ISBN rules and the row rules |
| `report.html` | The web page that shows `ingestion-log.json` |
| `make_report.py` | Makes `ingestion-report.xlsx` from `ingestion-log.json` |
| `books.db` | The database of saved books |
| `ingestion-log.json` | The record of every run |
| `ingestion-report.xlsx` | The Excel report |
| `books.csv` | The 10,000 books, from [goodbooks-10k](https://github.com/zygmuntz/goodbooks-10k), unchanged |
| `books-batch2.csv` | 200 books picked at random from `books.csv` |
| `tests/` | The automatic tests from Step 8 |
