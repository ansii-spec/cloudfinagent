"""Detector evaluation for the FYP report (specs/09 §4).

    python scripts/evaluate.py labels.csv --connection-id <uuid> [--scan] [--out evaluation_report.md]

labels.csv: instance_id,expected_label   (IDLE / OVER_PROVISIONED / UNDER_PROVISIONED / NEEDS_REVIEW / ACTIVE)
With --scan a fresh scan is run synchronously first; otherwise the latest findings are used.
Writes a confusion matrix and per-class precision / recall / F1 to a markdown file."""
import argparse
import csv
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import AwsConnection, Finding, Scan  # noqa: E402
from app.services import scan_service  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels")
    ap.add_argument("--connection-id", required=True)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--out", default="evaluation_report.md")
    args = ap.parse_args()

    expected = {r["instance_id"].strip(): r["expected_label"].strip().upper()
                for r in csv.DictReader(open(args.labels))}
    with SessionLocal() as db:
        conn = db.get(AwsConnection, uuid.UUID(args.connection_id))
        if args.scan:
            scan = Scan(connection_id=conn.id, trigger="manual", regions=conn.regions or [])
            db.add(scan)
            db.commit()
            scan_service.run_scan(scan.id)
        found = {f.instance_id: f.status for f in db.scalars(select(Finding).where(
            Finding.connection_id == conn.id, Finding.is_latest.is_(True)))}

    labels = sorted(set(expected.values()) | {found.get(i, "MISSING") for i in expected})
    matrix = {e: {p: 0 for p in labels} for e in labels}
    for iid, exp in expected.items():
        matrix[exp][found.get(iid, "MISSING")] += 1
    lines = [f"# Detector evaluation ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)", "",
             f"{len(expected)} labelled instances.", "", "## Confusion matrix (rows = expected, cols = predicted)",
             "", "| expected \\ predicted | " + " | ".join(labels) + " |", "|" + "---|" * (len(labels) + 1)]
    for e in labels:
        lines.append(f"| **{e}** | " + " | ".join(str(matrix[e][p]) for p in labels) + " |")
    lines += ["", "## Per class", "", "| class | precision | recall | F1 | support |", "|---|---|---|---|---|"]
    correct = 0
    for c in labels:
        tp = matrix[c][c]
        correct += tp
        fp = sum(matrix[e][c] for e in labels if e != c)
        fn = sum(matrix[c][p] for p in labels if p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        lines.append(f"| {c} | {prec:.2f} | {rec:.2f} | {f1:.2f} | {tp + fn} |")
    lines += ["", f"**Accuracy:** {correct / max(len(expected), 1):.2%}", "", "## Per instance", "",
              "| instance | expected | predicted |", "|---|---|---|"]
    lines += [f"| {i} | {e} | {found.get(i, 'MISSING')} |" for i, e in expected.items()]
    Path(args.out).write_text("\n".join(lines) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
