from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "cleanup_generated_artifacts.py"
spec = importlib.util.spec_from_file_location("cleanup_generated_artifacts", SCRIPT_PATH)
cleanup = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["cleanup_generated_artifacts"] = cleanup
spec.loader.exec_module(cleanup)


def write_file(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def touch_with_mtime(path: Path, offset: int) -> None:
    write_file(path, "x" * (offset + 1))
    ts = time.time() + offset
    path.touch()
    path.chmod(0o666)
    import os

    os.utime(path, (ts, ts))


def minimal_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    write_file(root / "main.py", "print('ok')")
    return root


def test_collect_old_workflows_keeps_latest_aliases_and_recent_runs(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    for idx, stamp in enumerate(
        [
            "2026-06-20_22-00-00",
            "2026-06-20_23-00-00",
            "2026-06-21_00-00-00",
            "2026-06-21_01-00-00",
        ]
    ):
        touch_with_mtime(root / "output" / "workflows" / f"{stamp}_full_report.json", idx)
        touch_with_mtime(root / "output" / "workflows" / f"{stamp}_full_report.txt", idx)
    write_file(root / "output" / "workflows" / "latest_full_report.json")
    write_file(root / "output" / "workflows" / "latest_full_report.txt")
    write_file(root / "output" / "workflows" / "latest_report.txt")

    candidates = cleanup.collect_old_workflows(root, keep=2)
    rels = {cleanup.relpath(root, item.path) for item in candidates}

    assert "output/workflows/2026-06-20_22-00-00_full_report.json" in rels
    assert "output/workflows/2026-06-20_23-00-00_full_report.txt" in rels
    assert "output/workflows/2026-06-21_01-00-00_full_report.json" not in rels
    assert "output/workflows/latest_full_report.json" not in rels
    assert "output/workflows/latest_full_report.txt" not in rels
    assert "output/workflows/latest_report.txt" not in rels


def test_raw_retention_is_per_source_group(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    for idx in range(5):
        touch_with_mtime(root / "data" / "raw" / "fifa" / f"fifa_official_20260621T00000{idx}Z.json", idx)
        touch_with_mtime(root / "data" / "raw" / "openfootball" / f"openfootball_20260621T00000{idx}Z.json", idx)
        touch_with_mtime(root / "data" / "raw" / "wikipedia" / f"wikipedia_worldcup_20260621T00000{idx}Z.html", idx)

    candidates = cleanup.collect_group_retention(root, cleanup.RAW_GROUPS, keep=2)
    rels = {cleanup.relpath(root, item.path) for item in candidates}

    assert len([rel for rel in rels if "/fifa/" in rel]) == 3
    assert len([rel for rel in rels if "/openfootball/" in rel]) == 3
    assert len([rel for rel in rels if "/wikipedia/" in rel]) == 3
    assert "data/raw/fifa/fifa_official_20260621T000004Z.json" not in rels
    assert "data/raw/openfootball/openfootball_20260621T000004Z.json" not in rels
    assert "data/raw/wikipedia/wikipedia_worldcup_20260621T000004Z.html" not in rels


def test_root_report_cleanup_preserves_current_reports_by_default(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    write_file(root / "output" / "latest_global_report.txt")
    write_file(root / "output" / "global_title_ranking.csv")
    write_file(root / "output" / "old_probe.csv")
    write_file(root / "output" / "some_temp.json")

    candidates = cleanup.collect_root_reports(root, keep_current=True)
    rels = {cleanup.relpath(root, item.path) for item in candidates}

    assert "output/old_probe.csv" in rels
    assert "output/some_temp.json" in rels
    assert "output/latest_global_report.txt" not in rels
    assert "output/global_title_ranking.csv" not in rels


def test_snapshot_directory_retention_keeps_recent_dirs(tmp_path: Path) -> None:
    root = minimal_project(tmp_path)
    for idx, stamp in enumerate(["20260620T170000Z", "20260620T180000Z", "20260620T190000Z"]):
        d = root / "data" / "snapshots" / stamp
        write_file(d / "matches.json", "{}")
        ts = time.time() + idx
        import os

        os.utime(d, (ts, ts))

    candidates = cleanup.collect_old_snapshot_dirs(root, keep=1)
    rels = {cleanup.relpath(root, item.path) for item in candidates}

    assert "data/snapshots/20260620T170000Z" in rels
    assert "data/snapshots/20260620T180000Z" in rels
    assert "data/snapshots/20260620T190000Z" not in rels
