# ruff: noqa: I001
"""The generator is reproducible and its manifest describes exactly what it wrote."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.data.conftest import Rendered
from synthetic.generate import generate


def test_manifest_lists_every_file_with_its_hash(rendered: Rendered) -> None:
    files = rendered.manifest["files"]
    assert len(files) == 23
    by_role: dict[str, int] = {}
    for f in files:
        by_role[f["role"]] = by_role.get(f["role"], 0) + 1
        data = rendered.path(f["path"]).read_bytes()
        assert f["bytes"] == len(data)
        assert f["sha256"] == hashlib.sha256(data).hexdigest()
    assert by_role == {"case": 15, "withheld": 2, "broken": 6}
    on_disk = {
        p.relative_to(rendered.out).as_posix() for p in rendered.out.rglob("*") if p.is_file()
    }
    assert on_disk == {f["path"] for f in files} | {"manifest.json"}
    assert (
        json.loads(rendered.path("manifest.json").read_text(encoding="utf-8")) == rendered.manifest
    )


def test_manifest_says_which_scenario_versions_produced_it(rendered: Rendered) -> None:
    assert set(rendered.manifest["scenarios"]) == {"angela_whitfield", "daniel_reyes"}
    assert "invented" in rendered.manifest["synthetic"]


def test_two_runs_produce_identical_files(rendered: Rendered, tmp_path: Path) -> None:
    again = generate(tmp_path)
    assert (
        again == rendered.manifest
    )  # same paths, sizes and SHA-256 for every file, locked one too


def test_only_renders_just_the_chosen_borrower(tmp_path: Path) -> None:
    manifest = generate(tmp_path, only=["angela_whitfield"])
    paths = [f["path"] for f in manifest["files"]]
    assert all(p.startswith(("angela_whitfield/", "broken/")) for p in paths)
    assert paths.count("broken/scan_mortgage_statement.jpg") == 1
    assert len(paths) == 9  # her eight documents and the scan made from her statement
    assert not (tmp_path / "daniel_reyes").exists()


def test_regenerating_replaces_stale_files(tmp_path: Path) -> None:
    generate(tmp_path)
    stale = tmp_path / "daniel_reyes" / "old_file.pdf"
    stale.write_bytes(b"leftover")
    generate(tmp_path)
    assert not stale.exists()
