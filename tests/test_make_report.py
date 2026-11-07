"""make_report.py: the Excel workbook built from ingestion-log.json.
Run: py -3.13 -m unittest discover tests"""
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.dom import minidom

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import make_report

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def run(run_id, started, status="COMPLETED WITH ISSUES", rejected=(), warnings=(), error=None, add_up=True):
    return {"run_id": run_id, "started_at": started, "finished_at": started, "file": f"{run_id}.csv",
            "rules": "rules.md (group agreed rules, 2026-11-06)",
            "status": status, "status_note": "may already be saved" if status == "FAILED" else None,
            "error": error, "counts_add_up": add_up,
            "counts": {"rows_read": 3, "loaded": 1, "loaded_clean": 1, "loaded_with_warning": 0, "updated": 0,
                       "skipped": 1, "rejected": len(rejected), "rows_with_warning": len(warnings), "rows_repaired": 1},
            "problem_counts": {"no-usable-isbn": 1}, "needs_attention": list(rejected), "warnings": list(warnings),
            "updates": [], "repairs": []}


def issue(row, title="A Book", reason="isbn-collision"):
    return {"source_file": "x.csv", "row_number": row, "goodreads_book_id": "9", "title": title,
            "reason": reason, "detail": "detail", "field": "isbn13", "raw_value": "9.78043902348e+12",
            "action": "do this"}


class Workbook(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.out = self.dir / "report.xlsx"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def sheet_rows(self, n):
        """Cell text/values of sheet n as a list of rows (empty cells skipped)."""
        from xml.etree import ElementTree as ET
        with zipfile.ZipFile(self.out) as z:
            root = ET.fromstring(z.read(f"xl/worksheets/sheet{n}.xml"))
        rows = []
        for r in root.iter(NS + "row"):
            cells = []
            for c in r.iter(NS + "c"):
                t = c.find(f"{NS}is/{NS}t")
                v = c.find(NS + "v")
                cells.append(t.text if t is not None else int(v.text))
            rows.append(cells)
        return rows

    def test_valid_package_with_named_tabs(self):
        make_report.build_workbook([run("a", "2026-10-30T02:00:00")], self.out)
        with zipfile.ZipFile(self.out) as z:
            for name in z.namelist():
                minidom.parseString(z.read(name))          # every part is well-formed XML
            names = re.findall(r'<sheet name="([^"]+)"', z.read("xl/workbook.xml").decode())
        self.assertEqual(names, ["Runs", "Rejected", "Warnings", "Updates", "Repairs", "Breakdown by rule"])

    def test_runs_newest_first_with_counts_as_numbers(self):
        runs = [run("old", "2026-10-29T02:00:00"), run("new", "2026-10-31T02:00:00"), run("mid", "2026-10-30T02:00:00")]
        make_report.build_workbook(runs, self.out)
        rows = self.sheet_rows(1)
        self.assertEqual(rows[0][:5], ["Started", "File", "Status", "Rules", "Rows processed"])
        self.assertEqual([r[1] for r in rows[1:]], ["new.csv", "mid.csv", "old.csv"])
        self.assertEqual(rows[1][4:12], [3, 1, 0, 0, 1, 0, 0, 1])

    def test_same_second_runs_keep_log_order_newest_first(self):
        make_report.build_workbook([run("first", "2026-10-31T02:00:00"), run("second", "2026-10-31T02:00:00")], self.out)
        self.assertEqual([r[1] for r in self.sheet_rows(1)[1:]], ["second.csv", "first.csv"])

    def test_rejected_and_warning_tabs_list_every_row_with_its_run(self):
        runs = [run("a", "2026-10-30T02:00:00", rejected=[issue(2), issue(5)], warnings=[issue(3, reason="no-usable-isbn")]),
                run("b", "2026-10-31T02:00:00", rejected=[issue(7)])]
        counts = make_report.build_workbook(runs, self.out)
        self.assertEqual(counts, {"Runs": 2, "Rejected": 3, "Warnings": 1, "Updates": 0, "Repairs": 0, "Breakdown by rule": 2})
        not_loaded = self.sheet_rows(2)
        self.assertEqual([(r[1], r[2]) for r in not_loaded[1:]], [("x.csv", 7), ("x.csv", 2), ("x.csv", 5)])
        self.assertEqual(not_loaded[1][-1], "b")                     # run ID column
        self.assertIn("do this", not_loaded[1])

    def test_text_is_escaped_and_control_characters_removed(self):
        make_report.build_workbook([run("a", "2026-10-31T02:00:00", rejected=[issue(2, title="<b>Bold</b> & \x07Co")])], self.out)
        self.assertIn("<b>Bold</b> & Co", self.sheet_rows(2)[1])

    def test_failed_run_and_empty_tabs(self):
        make_report.build_workbook([run("f", "2026-10-31T02:00:00", status="FAILED", error="file not found", add_up=None)], self.out)
        row = self.sheet_rows(1)[1]
        self.assertIn("FAILED", row)
        self.assertIn("n/a (run failed)", row)
        self.assertIn("file not found", row)
        self.assertIn("may already be saved", row)
        self.assertEqual(len(self.sheet_rows(2)), 1)                 # header only

    def test_earlier_rules_runs_appear_on_runs_tab_only(self):
        old = {"run_id": "old", "started_at": "2026-10-29T02:00:00", "file": "books.csv", "status": "COMPLETED WITH ISSUES",
               "counts": {"read": 3}, "not_loaded": [issue(2)], "warnings": [issue(3)]}
        counts = make_report.build_workbook([old, run("new", "2026-10-31T02:00:00")], self.out)
        self.assertEqual(counts["Runs"], 2)
        self.assertEqual(counts["Warnings"], 0)
        self.assertIn("earlier rules (Abigail)", self.sheet_rows(1)[2])

    def test_same_log_gives_identical_file(self):
        runs = [run("a", "2026-10-31T02:00:00", rejected=[issue(2)])]
        make_report.build_workbook(runs, self.out)
        first = self.out.read_bytes()
        make_report.build_workbook(runs, self.out)
        self.assertEqual(first, self.out.read_bytes())

    def test_missing_or_damaged_log_is_an_error(self):
        with self.assertRaises(SystemExit):
            make_report.load_runs(self.dir / "nope.json")
        bad = self.dir / "bad.json"
        bad.write_text("{ nope", encoding="utf-8")
        with self.assertRaises(SystemExit):
            make_report.load_runs(bad)

    def test_command_line(self):
        log = self.dir / "log.json"
        log.write_text(json.dumps([run("a", "2026-10-31T02:00:00")]), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = make_report.main(["--log", str(log), "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertTrue(self.out.exists())


if __name__ == "__main__":
    unittest.main()
