# language-of-computation-week3-assignment

This is my Module 3 assignment for MSAI-5523.

A nightly import that checks every row of a books CSV (goodbooks-10k format), loads the good rows into SQLite, never loads the same book twice, and writes a report a person can read the next morning.

| File | What it is |
|---|---|
| [data-validation.md](data-validation.md) | Diagnosis of the ISBN problems in `books.csv` and `books-batch2.csv` |
| [rules.md](rules.md) | The rules the code must follow: repair, reject or warn; duplicates; existing records; the report; examples |
| [implementation.md](implementation.md) | How the code follows the rules, the tests, and known limitations |
| `ingest.py` | Loads a books CSV into `books.db` and appends one entry per run to `ingestion-log.json` |
| `report.html` | Opens `ingestion-log.json` in a browser (no server) and shows each run, newest first |
| `isbn.py`, `validate.py` | The ISBN and row rules, shared by `ingest.py` and `import_books.py` |
| `import_books.py`, `report.py` | The earlier version of the import (`library.db` + Markdown/CSV reports) |
| `tests/` | Automated tests |
| `examples/` | Real reports produced by the code |
| `books.csv` | Source data: [goodbooks-10k](https://github.com/zygmuntz/goodbooks-10k) `books.csv`, unchanged |
| `books-batch2.csv` | 200 rows picked at random from `books.csv` (seed 5523), copied byte-for-byte |

## Run it

```bash
py -3.13 ingest.py books.csv
```

```bash
py -3.13 ingest.py books-batch2.csv
```

Then open `report.html` in a browser, click **Open ingestion-log.json**, and pick the log file.

Each run reads every row, loads new books, updates changed ones, skips books that already exist, and rejects rows the rules don't allow. Running the same file twice never creates duplicates. Every run, even a failed one, is appended to `ingestion-log.json`: when it ran, which file, how many rows were read, loaded, updated, skipped and rejected, and every row that wasn't loaded with its reason and what to do. If the log file is damaged, the script stops without importing anything or changing the log.

To re-import corrected rows that an earlier run rejected:

```bash
py -3.13 ingest.py fixed-rows.csv --reprocess-of RUN_ID
```

Run the tests:

```bash
py -3.13 -m unittest discover tests -v
```
