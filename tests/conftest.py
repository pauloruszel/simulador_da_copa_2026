from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_workspace(monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    tmp_path = repo_root / ".pytest_workspace" / uuid.uuid4().hex
    tmp_path.mkdir(parents=True)
    shutil.copytree(repo_root / "data", tmp_path / "data", ignore=shutil.ignore_patterns("raw", "snapshots"))
    (tmp_path / "data" / "raw").mkdir()
    (tmp_path / "data" / "snapshots").mkdir()
    for path in (tmp_path / "data").rglob("*"):
        if path.is_file():
            path.chmod(0o666)
    (tmp_path / "output").mkdir()
    monkeypatch.chdir(tmp_path)
    yield
    monkeypatch.chdir(repo_root)
    for path in sorted(tmp_path.rglob("*"), reverse=True):
        try:
            path.chmod(0o777)
        except OSError:
            pass
    shutil.rmtree(tmp_path, ignore_errors=True)
