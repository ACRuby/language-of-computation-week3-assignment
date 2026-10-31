"""Write the morning report for one import: a Markdown summary plus two CSVs
(every rejected row with its original data, and every issue in detail)."""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from validate import ISSUE_TYPES

STATUS_MEANING = {
    "SUCCESS": "Every row was loaded with no warnings. Nothing to do.",
    "COMPLETED WITH ISSUES": "The import finished and the catalog is updated, but some rows were rejected or need attention (see Actions required).",
    "FAILED": "The import did not finish. Nothing from this file was saved; the catalog is exactly as it was before.",
}
WARNINGS_SHOWN_PER_TYPE = 10
ISSUE_COLUMNS = ["source_file", "row_number", "goodreads_book_id", "title", "original_isbn", "original_isbn13",
                 "field", "problem", "detail", "action_taken", "reason", "recommended_action"]


def _issue_lines(s):
    for r in s.rows:
        raw = r.result.raw
        for issue in r.problems:
            t = ISSUE_TYPES[issue.code]
            yield {
                "source_file": s.file_name, "row_number": r.result.row_number,
                "goodreads_book_id": raw.get("goodreads_book_id"), "title": raw.get("title"),
                "original_isbn": raw.get("isbn"), "original_isbn13": raw.get("isbn13"),
                "field": issue.field, "problem": issue.code, "detail": issue.detail,
                "action_taken": "REJECTED (not loaded)" if r.outcome == "REJECTED" else f"loaded as {r.outcome} with warning",
                "reason": t.reason, "recommended_action": t.recommended,
            }


def _md_escape(text):
    return str(text).replace("|", "\\|") if text is not None and str(text).strip() else "—"


def write_reports(s, reports_dir: Path) -> dict:
    reports_dir.mkdir(parents=True, exist_ok=True)
    paths = {"report": reports_dir / f"{s.import_id}.md",
             "rejected": reports_dir / f"{s.import_id}-rejected.csv",
             "issues": reports_dir / f"{s.import_id}-issues.csv"}
    issues = list(_issue_lines(s))

    with open(paths["issues"], "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, ISSUE_COLUMNS)
        w.writeheader()
        w.writerows(issues)

    with open(paths["rejected"], "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["row_number", "problem", "detail", "recommended_action"] + s.columns)
        for r in s.rows:
            if r.outcome == "REJECTED":
                first = r.problems[0]
                w.writerow([r.result.row_number, first.code, "; ".join(p.detail for p in r.problems),
                            ISSUE_TYPES[first.code].recommended] + [r.result.raw.get(c, "") for c in s.columns])

    paths["report"].write_text(_markdown(s, issues, paths), encoding="utf-8")
    return paths


def _markdown(s, issues, paths) -> str:
    n = {o: s.count(o) for o in ("CREATED", "UPDATED", "UNCHANGED", "REJECTED")}
    total = len(s.rows)
    out = [f"# Library Import Report — {s.file_name}", "",
           f"**Status: {s.status}** — {STATUS_MEANING[s.status]}", ""]
    if s.note:
        out += [f"**Reason:** {s.note}", ""]
    if s.previous_import:
        out += [f"Note: this exact file was already imported as `{s.previous_import}`. Re-importing it should only produce UNCHANGED rows (plus the same rejections as before).", ""]
    if s.reprocess_of:
        out += [f"This import re-processes corrected rows rejected by import `{s.reprocess_of}`.", ""]

    out += ["| | |", "|---|---:|",
            f"| Import ID | `{s.import_id}` |", f"| File | {s.file_name} |",
            f"| Started | {s.started_at:%Y-%m-%d %H:%M:%S} |", f"| Finished | {s.ended_at:%Y-%m-%d %H:%M:%S} |",
            f"| Total rows | {total:,} |", f"| Created | {n['CREATED']:,} |", f"| Updated | {n['UPDATED']:,} |",
            f"| Unchanged | {n['UNCHANGED']:,} |", f"| Rejected | {n['REJECTED']:,} |",
            f"| Total accepted | {total - n['REJECTED']:,} |",
            f"| Automatically repaired | {s.repaired:,} |", f"| Loaded with warnings | {s.warned:,} |",
            f"| Status | {s.status} |", ""]
    if s.status != "FAILED":
        ok = s.reconciles()
        out += [f"**Check:** {total:,} rows = {n['CREATED']:,} created + {n['UPDATED']:,} updated + "
                f"{n['UNCHANGED']:,} unchanged + {n['REJECTED']:,} rejected — {'adds up' if ok else 'DOES NOT ADD UP'}.", ""]

    out += ["## Actions required", ""]
    if s.status == "FAILED":
        out += ["- Fix the problem above and run the import again. No rows were loaded, so nothing needs to be undone.", ""]
    by_code = defaultdict(list)
    for line in issues:
        by_code[line["problem"]].append(line)
    if s.status != "FAILED" and not by_code:
        out += ["- None.", ""]
    for code in sorted(by_code, key=lambda c: (ISSUE_TYPES[c].action != "REJECT", -len(by_code[c]))):
        t, k = ISSUE_TYPES[code], len(by_code[code])
        verb = "rejected" if t.action == "REJECT" else "loaded with a warning"
        out.append(f"- **{k:,} row(s) {verb}: `{code}`.** {t.recommended}")
    if by_code:
        out += ["", f"Every issue, with row number and original values, is in `{paths['issues'].name}`."]
        if s.count("REJECTED"):
            out[-1] += (f" Rejected rows with their original data are in `{paths['rejected'].name}`; correct them and "
                        f"re-import with `--reprocess-of {s.import_id}`.")
        out.append("")

    rejected = [l for l in issues if l["action_taken"].startswith("REJECTED")]
    if rejected:
        out += ["## Rejected rows", "",
                "| Row | Goodreads ID | Title | isbn | isbn13 | Field | Problem | Why | What to do |",
                "|---:|---|---|---|---|---|---|---|---|"]
        for l in rejected:
            out.append("| " + " | ".join(_md_escape(l[c]) for c in ("row_number", "goodreads_book_id", "title", "original_isbn", "original_isbn13", "field", "detail", "reason", "recommended_action")) + " |")
        out.append("")

    warned = {c: v for c, v in by_code.items() if ISSUE_TYPES[c].action != "REJECT"}
    if warned:
        out += ["## Warnings (rows were loaded)", ""]
        for code, lines in sorted(warned.items(), key=lambda kv: -len(kv[1])):
            t = ISSUE_TYPES[code]
            out += [f"### `{code}` — {len(lines):,} row(s)", "", f"{t.reason} **What to do:** {t.recommended}", "",
                    "| Row | Goodreads ID | Title | isbn | isbn13 | Detail |", "|---:|---|---|---|---|---|"]
            for l in lines[:WARNINGS_SHOWN_PER_TYPE]:
                out.append("| " + " | ".join(_md_escape(l[c]) for c in ("row_number", "goodreads_book_id", "title", "original_isbn", "original_isbn13", "detail")) + " |")
            if len(lines) > WARNINGS_SHOWN_PER_TYPE:
                out.append(f"\n…and {len(lines) - WARNINGS_SHOWN_PER_TYPE:,} more in `{paths['issues'].name}`.")
            out.append("")

    repairs = Counter((rep.field, rep.reason) for r in s.rows if r.outcome != "REJECTED" for rep in r.result.repairs)
    if repairs:
        out += ["## Automatic repairs", "",
                "Only repairs with exactly one possible answer are made; originals are kept in the audit log.", "",
                "| Field | Repair | Rows |", "|---|---|---:|"]
        out += [f"| {f} | {reason} | {k:,} |" for (f, reason), k in repairs.most_common()]
        out.append("")
    return "\n".join(out)
