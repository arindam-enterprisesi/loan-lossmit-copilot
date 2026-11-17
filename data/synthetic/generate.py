"""Render every borrower's documents, and the broken set, from the scenario files.

    cd backend
    uv run python ../data/synthetic/generate.py [--out DIR] [--only daniel_reyes ...]

Output (``data/synthetic/rendered/`` by default, which git ignores)::

    <borrower>/                documents uploaded into the case
    <borrower>/withheld/       documents the demo case is deliberately missing
    broken/                    locked, corrupt, unsupported, duplicate and scanned uploads
    manifest.json              every file: type, role, pages, SHA-256, expected behaviour
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: make `synthetic` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from synthetic import broken
from synthetic.layout import build_pdf
from synthetic.renderers import render_pages
from synthetic.schema import BankStatementDoc, Scenario, load_scenario, scenario_names

DEFAULT_OUT = Path(__file__).resolve().parent / "rendered"
BROKEN_DIR = "broken"


def _entry(path: Path, root: Path, **fields: Any) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        **fields,
    }


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def generate(out: Path = DEFAULT_OUT, only: Sequence[str] | None = None) -> dict[str, Any]:
    """Write all files and ``manifest.json`` under ``out``; return the manifest."""
    names = [n for n in scenario_names() if only is None or n in only]
    if not names:
        raise SystemExit(f"no scenarios match {only!r}; available: {scenario_names()}")
    scenarios = {name: load_scenario(name) for name in names}

    for name in names:  # only remove what this tool writes
        shutil.rmtree(out / name, ignore_errors=True)
    shutil.rmtree(out / BROKEN_DIR, ignore_errors=True)

    files: list[dict[str, Any]] = []
    clean: dict[tuple[str, str], bytes] = {}
    for name, scenario in scenarios.items():
        for doc in scenario.documents:
            pages = render_pages(doc)
            data = build_pdf(pages, title=doc.file_name)
            clean[(name, doc.id)] = data
            folder = out / name / ("withheld" if doc.role == "withheld" else "")
            path = _write(folder / doc.file_name, data)
            files.append(
                _entry(
                    path,
                    out,
                    borrower=name,
                    document_id=doc.id,
                    doc_type=doc.type,
                    role=doc.role,
                    declared_type=doc.declared_type,
                    page_count=len(pages),
                    notes=doc.notes,
                )
            )

    files += _broken_set(out, scenarios, clean)
    files.sort(key=lambda f: f["path"])
    manifest = {
        "generator": "data/synthetic/generate.py",
        "scenarios": {n: s.version for n, s in scenarios.items()},
        "synthetic": "All people, employers and accounts are invented.",
        "files": files,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def _broken_set(
    out: Path, scenarios: dict[str, Scenario], clean: dict[tuple[str, str], bytes]
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    folder = out / BROKEN_DIR

    def add(file_name: str, data: bytes, **fields: Any) -> None:
        files.append(_entry(_write(folder / file_name, data), out, role="broken", **fields))

    if "daniel_reyes" in scenarios:
        daniel = scenarios["daniel_reyes"]
        w2 = daniel.document("w2_2025")
        add(
            "locked_w2_2025.pdf",
            broken.locked_pdf(w2),
            kind="password_protected",
            source_document="daniel_reyes/w2_2025",
            password=broken.LOCK_PASSWORD,
            expected_behaviour="rejected with a reason: the file is password protected",
        )
        aug = daniel.document("bank_statement_2026-08")
        add(
            "corrupt_bank_statement.pdf",
            broken.corrupt_pdf(clean[("daniel_reyes", aug.id)]),
            kind="corrupt",
            source_document="daniel_reyes/bank_statement_2026-08",
            expected_behaviour="rejected with a reason: the file cannot be read",
        )
        sep = daniel.document("bank_statement_2026-09")
        assert isinstance(sep, BankStatementDoc)
        add(
            "bank_transactions_export.csv",
            broken.csv_export(sep),
            kind="unsupported_type",
            source_document="daniel_reyes/bank_statement_2026-09",
            expected_behaviour="rejected with a reason: only PDF, PNG and JPEG are accepted",
        )
        stub = daniel.document("pay_stub_2026-09-27")
        add(
            "duplicate_pay_stub.pdf",
            clean[("daniel_reyes", stub.id)],
            kind="duplicate",
            source_document="daniel_reyes/pay_stub_2026-09-27",
            expected_behaviour="warned: this file is already in the case (same SHA-256)",
        )
        add(
            "scan_pay_stub_photo.pdf",
            broken.photographed_pdf(clean[("daniel_reyes", stub.id)], title="scan_pay_stub_photo"),
            kind="scan",
            source_document="daniel_reyes/pay_stub_2026-09-27",
            page_count=2,
            expected_behaviour="reads with low confidence; page 2 flagged as hard to read",
        )
    if "angela_whitfield" in scenarios:
        statement = scenarios["angela_whitfield"].document("mortgage_statement_2026-10")
        add(
            "scan_mortgage_statement.jpg",
            broken.scanned_jpeg(clean[("angela_whitfield", statement.id)]),
            kind="scan",
            source_document="angela_whitfield/mortgage_statement_2026-10",
            page_count=1,
            expected_behaviour="reads with low confidence; flagged as a poor scan",
        )
    return files


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output folder")
    parser.add_argument("--only", nargs="*", help="scenario names (default: all)")
    args = parser.parse_args(argv)
    manifest = generate(args.out, args.only)
    by_role: dict[str, int] = {}
    for f in manifest["files"]:
        by_role[f["role"]] = by_role.get(f["role"], 0) + 1
    print(f"Wrote {len(manifest['files'])} files to {args.out}: {by_role}")


if __name__ == "__main__":
    main()
