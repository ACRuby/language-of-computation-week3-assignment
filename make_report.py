"""Turn ingestion-log.json into an easy-to-read Excel workbook.

    python make_report.py
    python make_report.py --log ingestion-log.json --out ingestion-report.xlsx

Six tabs, covering every run in the log:
  Runs               one row per run, newest first: status and headline counts
  Rejected           every rejected row (needs a person), with the rule and detail
  Warnings           every row that carries a warning, with the original value
  Updates            every updated field, old -> new
  Repairs            every repair that was saved
  Breakdown by rule  how many times each rule applied, per run

Runs recorded under Abigail's earlier rules (before the group's agreed rules)
appear on the Runs tab only.

Standard library only: the .xlsx file (a zip of XML files) is written
directly, so nothing needs installing. The same log always produces a
byte-identical workbook. ingest.py is not changed by this script.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

LOG_PATH = "ingestion-log.json"
OUT_PATH = "ingestion-report.xlsx"

EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_CELL = 32_767
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Cell styles (indexes into cellXfs in STYLES below).
HEADER, TEXT, WRAP, NUMBER, OK, ISSUES, FAILED = 1, 2, 3, 4, 5, 6, 7
STATUS_STYLE = {"SUCCESS": OK, "COMPLETED WITH ISSUES": ISSUES, "FAILED": FAILED}


def _when(iso):
    return (iso or "").replace("T", " ")


def _count(name):
    return lambda run, _row=None: (run.get("counts") or {}).get(name)


def _yes_no(value):
    return {True: "Yes", False: "NO"}.get(value, "n/a (run failed)")


# (header, column width, value(run, row), kind) -- kind: text / wrap / number / status
RUN_COLUMNS = [
    ("Started", 19, lambda r, _=None: _when(r.get("started_at")), "text"),
    ("File", 22, lambda r, _=None: r.get("file"), "text"),
    ("Status", 23, lambda r, _=None: r.get("status"), "status"),
    ("Rules", 22, lambda r, _=None: "agreed rules" if r.get("rules") else "earlier rules (Abigail)", "text"),
    ("Rows processed", 11, _count("rows_read"), "number"),
    ("Loaded clean", 10, _count("loaded_clean"), "number"),
    ("Loaded with a warning", 12, _count("loaded_with_warning"), "number"),
    ("Updated", 10, _count("updated"), "number"),
    ("Skipped as duplicates", 12, _count("skipped"), "number"),
    ("Rejected", 10, _count("rejected"), "number"),
    ("Rows with a warning", 12, _count("rows_with_warning"), "number"),
    ("Rows repaired", 10, _count("rows_repaired"), "number"),
    ("Counts add up", 11, lambda r, _=None: _yes_no(r.get("counts_add_up")) if r.get("rules") else None, "text"),
    ("Error", 30, lambda r, _=None: r.get("error"), "wrap"),
    ("Status note", 50, lambda r, _=None: r.get("status_note"), "wrap"),
    ("Finished", 19, lambda r, _=None: _when(r.get("finished_at")), "text"),
    ("Run ID", 24, lambda r, _=None: r.get("run_id"), "text"),
]

_BOOK = [
    ("Run started", 19, lambda r, row: _when(r.get("started_at")), "text"),
    ("File", 20, lambda r, row: row.get("source_file") or r.get("file"), "text"),
    ("Row", 7, lambda r, row: row.get("row_number"), "number"),
    ("Goodreads ID", 13, lambda r, row: row.get("goodreads_book_id"), "text"),
    ("Title", 40, lambda r, row: row.get("title"), "wrap"),
]
_RUN_ID = [("Run ID", 24, lambda r, row: r.get("run_id"), "text")]


def _get(key):
    return lambda r, row: row.get(key)


REJECTED_COLUMNS = _BOOK + [("Rule", 22, _get("reason"), "text"), ("Detail", 50, _get("detail"), "wrap"),
                            ("What the system did", 30, _get("action"), "wrap")] + _RUN_ID
WARNING_COLUMNS = _BOOK + [("Field", 9, _get("field"), "text"), ("Original value", 20, _get("raw_value"), "text"),
                           ("Rule(s)", 30, _get("reason"), "text"), ("What the system did", 40, _get("action"), "wrap")] + _RUN_ID
UPDATE_COLUMNS = _BOOK + [("Field", 20, _get("field"), "text"), ("Old", 30, _get("old"), "wrap"),
                          ("New", 30, _get("new"), "wrap")] + _RUN_ID
REPAIR_COLUMNS = _BOOK + [("Field", 9, _get("field"), "text"), ("Original value", 20, _get("original"), "text"),
                          ("Repaired value", 16, _get("new"), "text"), ("Rule", 26, _get("reason"), "text")] + _RUN_ID
BREAKDOWN_COLUMNS = [
    ("Run started", 19, lambda r, row: _when(r.get("started_at")), "text"),
    ("File", 20, lambda r, row: r.get("file"), "text"),
    ("Rule (rules.md section 5)", 28, lambda r, row: row[0], "text"),
    ("Times", 10, lambda r, row: row[1], "number"),
] + _RUN_ID


def newest_first(runs):
    """Newest run first; runs started in the same second keep log order (later entry = newer)."""
    indexed = list(enumerate(runs))
    indexed.sort(key=lambda x: (x[1].get("started_at") or "", x[0]), reverse=True)
    return [run for _, run in indexed]


def _col_letter(n):
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _cell(ref, value, kind):
    if value is None or value == "":
        return ""
    if kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{NUMBER}"><v>{value}</v></c>'
    text = _ILLEGAL_XML.sub("", str(value))
    if len(text) > EXCEL_MAX_CELL:
        text = text[: EXCEL_MAX_CELL - 30] + " ...[cut: see ingestion-log.json]"
    style = STATUS_STYLE.get(text, ISSUES) if kind == "status" else {"header": HEADER, "wrap": WRAP}.get(kind, TEXT)
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def sheet_xml(columns, rows):
    """rows: list of (run, row) pairs. Header row is frozen and filterable."""
    if len(rows) + 1 > EXCEL_MAX_ROWS:
        raise SystemExit(f"ERROR: {len(rows):,} rows is more than one Excel sheet can hold.")
    last_col = _col_letter(len(columns))
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           f'<dimension ref="A1:{last_col}{len(rows) + 1}"/>',
           '<sheetViews><sheetView workbookViewId="0">'
           '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
           '<sheetFormatPr defaultRowHeight="15"/><cols>']
    out += [f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, (_, w, _, _) in enumerate(columns, 1)]
    out.append('</cols><sheetData>')
    out.append('<row r="1">' + "".join(_cell(f"{_col_letter(i)}1", h, "header") for i, (h, _, _, _) in enumerate(columns, 1)) + "</row>")
    for n, (run, row) in enumerate(rows, 2):
        cells = "".join(_cell(f"{_col_letter(i)}{n}", get(run, row), kind) for i, (_, _, get, kind) in enumerate(columns, 1))
        out.append(f'<row r="{n}">{cells}</row>')
    out.append('</sheetData>')
    out.append(f'<autoFilter ref="A1:{last_col}{len(rows) + 1}"/>')
    out.append('<pageMargins left="0.5" right="0.5" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')
    return "".join(out)


STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2"><font><sz val="11"/><name val="Calibri"/><family val="2"/></font><font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font></fonts>
<fills count="6"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFD9E1F2"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFC6EFCE"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFEB9C"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFFFC7CE"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>
<border><left/><right/><top/><bottom style="thin"><color rgb="FF8EA9DB"/></bottom><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="8">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="1" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="1" fillId="4" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="top"/></xf>
<xf numFmtId="0" fontId="1" fillId="5" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment vertical="top"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def build_workbook(runs, out_path: Path):
    ordered = newest_first(runs)
    agreed = [run for run in ordered if run.get("rules")]     # row details exist only under the agreed rules
    rows = lambda key: [(run, row) for run in agreed for row in run.get(key) or []]  # noqa: E731
    sheets = [
        ("Runs", sheet_xml(RUN_COLUMNS, [(run, None) for run in ordered])),
        ("Rejected", sheet_xml(REJECTED_COLUMNS, rows("needs_attention"))),
        ("Warnings", sheet_xml(WARNING_COLUMNS, rows("warnings"))),
        ("Updates", sheet_xml(UPDATE_COLUMNS, rows("updates"))),
        ("Repairs", sheet_xml(REPAIR_COLUMNS, rows("repairs"))),
        ("Breakdown by rule", sheet_xml(BREAKDOWN_COLUMNS, [(run, item) for run in agreed
                                                            for item in (run.get("problem_counts") or {}).items()])),
    ]
    ns = 'xmlns="http://schemas.openxmlformats.org/package/2006/relationships"'
    files = {
        "[Content_Types].xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
                      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                      for i in range(1, len(sheets) + 1))
            + '</Types>',
        "_rels/.rels":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships {ns}>'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>',
        "xl/workbook.xml":
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
            + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1))
            + '</sheets></workbook>',
        "xl/_rels/workbook.xml.rels":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships {ns}>'
            + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                      f'Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1))
            + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>',
        "xl/styles.xml": STYLES,
    }
    for i, (_, xml) in enumerate(sheets, 1):
        files[f"xl/worksheets/sheet{i}.xml"] = xml

    tmp = out_path.with_name(out_path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))   # fixed date: same log -> same bytes
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, content.encode("utf-8"))
    tmp.replace(out_path)
    return {name: xml.count("<row ") - 1 for name, xml in sheets}


def load_runs(log_path: Path):
    try:
        runs = json.loads(log_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"ERROR: {log_path} not found. Run ingest.py first.")
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SystemExit(f"ERROR: {log_path} is not valid JSON ({e}).")
    if not isinstance(runs, list):
        raise SystemExit(f"ERROR: {log_path} should contain a JSON list of runs.")
    return runs


def main(argv=None):
    p = argparse.ArgumentParser(description="Build an Excel report from ingestion-log.json.")
    p.add_argument("--log", default=LOG_PATH, help=f"run log to read (default: {LOG_PATH})")
    p.add_argument("--out", default=OUT_PATH, help=f"workbook to write (default: {OUT_PATH})")
    a = p.parse_args(argv)
    runs = load_runs(Path(a.log))
    counts = build_workbook(runs, Path(a.out))
    print(f"Wrote {a.out}: " + ", ".join(f"{name}: {n:,} row(s)" for name, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
