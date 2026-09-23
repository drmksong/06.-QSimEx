"""Audit the codebase for legacy and canonical metric names.

Writes a JSON report to Specification/nomenclature_audit_{timestamp}.json
and prints a short summary to stdout.
"""
from __future__ import annotations

import re
import json
import datetime
from pathlib import Path
from typing import List, Dict, Any

ROOT = Path(__file__).resolve().parents[2]
SPEC_DIR = ROOT / "Specification"
REPORT_PATH = SPEC_DIR / f"nomenclature_audit_{datetime.date.today().isoformat()}.json"

try:
    from src.core import constants
except Exception:
    # Fallback: import relative if running from package context
    import sys

    sys.path.insert(0, str(ROOT))
    from src.core import constants


def patterns() -> List[str]:
    pats = set()
    # scan both legacy keys and canonical names
    for k in list(constants.LEGACY_TO_CANONICAL.keys()):
        pats.add(re.escape(k))
    for v in constants.CANONICAL.values():
        pats.add(re.escape(v))
    for v in constants.STANDARD_COST_KEYS.values():
        pats.add(re.escape(v))
    return sorted(pats)


def scan_files(root: Path, include_exts=(".py", ".md", ".yaml", ".yml", ".csv", ".json")) -> List[Path]:
    files = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in include_exts:
            files.append(p)
    return files


def audit() -> Dict[str, Any]:
    pats = patterns()
    regex = re.compile(r"\b(" + "|".join(pats) + r")\b")

    files = scan_files(ROOT)
    report: Dict[str, Any] = {"generated": str(datetime.datetime.now()), "matches": []}

    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            for m in regex.finditer(line):
                token = m.group(1)
                report["matches"].append({
                    "file": str(f.relative_to(ROOT)),
                    "line": i,
                    "token": token,
                    "text": line.strip(),
                })

    # summary counts by token
    summary: Dict[str, int] = {}
    for r in report["matches"]:
        summary[r["token"]] = summary.get(r["token"], 0) + 1

    report["summary"] = summary

    # write report
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def main():
    print("Running nomenclature audit...")
    rep = audit()
    total = len(rep.get("matches", []))
    print(f"Found {total} matches across {len(rep.get('summary', {}))} tokens.")
    # print top 10 tokens
    items = sorted(rep.get("summary", {}).items(), key=lambda x: x[1], reverse=True)[:10]
    for tok, cnt in items:
        print(f"  {tok}: {cnt}")
    print(f"Report written to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
