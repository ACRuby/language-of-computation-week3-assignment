# language-of-computation-week3-assignment

This is my Module 3 assignment for MSAI-5523.

A nightly import that checks every row of a books CSV (goodbooks-10k format), loads the good rows into SQLite, never loads the same book twice, and writes a report a person can read the next morning.

| File | What it is |
|---|---|
| [data-validation.md](data-validation.md) | Diagnosis of the ISBN problems in `books.csv` and `books-batch2.csv` |
| [rules.md](rules.md) | The rules the code must follow: repair, reject or warn; duplicates; existing records; the report; examples |
| [implementation.md](implementation.md) | How the code follows the rules, the tests, and known limitations |
| `isbn.py`, `validate.py`, `import_books.py`, `report.py` | The code (Python 3.13 standard library only) |
| `tests/` | Automated tests |
| `examples/` | Real reports produced by the code |
| `books.csv` | Source data: [goodbooks-10k](https://github.com/zygmuntz/goodbooks-10k) `books.csv`, unchanged |
| `books-batch2.csv` | 200 rows picked at random from `books.csv` (seed 5523), copied byte-for-byte |

## Run it

```bash
py -3.13 import_books.py books.csv
```

```bash
py -3.13 import_books.py books-batch2.csv
```

```bash
py -3.13 -m unittest discover tests -v
```

The catalog is saved to `library.db`, and each run's report goes in `reports/`.
