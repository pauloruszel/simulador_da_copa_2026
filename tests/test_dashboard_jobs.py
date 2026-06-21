from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import backend.api as dashboard_api
import backend.job_manager as job_manager_module
from backend.command_runner import CommandRequest
from backend.job_manager import DashboardJobManager


def test_job_manager_runs_command_asynchronously(monkeypatch):
    def fake_run(request):
        return {"ok": True, "action": request.action, "stdout": "ok", "stderr": "", "returncode": 0}

    monkeypatch.setattr(job_manager_module, "run_dashboard_command", fake_run)
    manager = DashboardJobManager()

    job = manager.submit(CommandRequest("source_health_check"))

    for _ in range(100):
        current = manager.get(job["id"])
        if current["status"] == "succeeded":
            break
        time.sleep(0.01)

    assert manager.get(job["id"])["status"] == "succeeded"
    assert manager.get(job["id"])["result"]["stdout"] == "ok"


def test_job_manager_persists_finished_jobs(monkeypatch):
    def fake_run(request):
        return {"ok": True, "action": request.action, "stdout": "ok", "stderr": "", "returncode": 0}

    monkeypatch.setattr(job_manager_module, "run_dashboard_command", fake_run)
    storage_path = Path("output/dashboard_jobs/jobs.json")
    manager = DashboardJobManager(storage_path=storage_path)

    job = manager.submit(CommandRequest("source_health_check"))
    for _ in range(100):
        current = manager.get(job["id"])
        if current["status"] == "succeeded":
            break
        time.sleep(0.01)

    reloaded = DashboardJobManager(storage_path=storage_path)

    assert reloaded.get(job["id"])["status"] == "succeeded"
    assert reloaded.get(job["id"])["result"]["stdout"] == "ok"


def test_job_manager_marks_interrupted_jobs_as_failed():
    storage_path = Path("output/dashboard_jobs/jobs.json")
    storage_path.parent.mkdir(parents=True)
    storage_path.write_text(
        json.dumps(
            [
                {
                    "id": "job-1",
                    "request": {"action": "workflow_global", "team": "Brasil", "simulations": 50000, "seed": 42},
                    "status": "running",
                    "created_at": "2026-06-20T00:00:00+00:00",
                    "started_at": "2026-06-20T00:00:01+00:00",
                    "finished_at": None,
                    "result": None,
                    "error": None,
                }
            ]
        ),
        encoding="utf-8",
    )

    manager = DashboardJobManager(storage_path=storage_path)

    job = manager.get("job-1")
    assert job["status"] == "failed"
    assert job["error"] == "Job interrompido antes da conclusao."


def test_job_manager_retries_failed_job(monkeypatch):
    calls = []

    def fake_run(request):
        calls.append(request)
        return {"ok": False, "action": request.action, "stdout": "", "stderr": "erro", "returncode": 1}

    monkeypatch.setattr(job_manager_module, "run_dashboard_command", fake_run)
    manager = DashboardJobManager(storage_path=Path("output/dashboard_jobs/jobs.json"))

    failed = manager.submit(CommandRequest("workflow_global", simulations=1000, seed=7))
    for _ in range(100):
        current = manager.get(failed["id"])
        if current["status"] == "failed":
            break
        time.sleep(0.01)

    retried = manager.retry(failed["id"])
    for _ in range(100):
        current = manager.get(retried["id"])
        if current["status"] == "failed":
            break
        time.sleep(0.01)

    assert retried["request"] == failed["request"]
    assert retried["retried_from"] == failed["id"]
    assert len(calls) >= 2


def test_jobs_api_contract(monkeypatch):
    class FakeJobs:
        def submit(self, request):
            return {"id": "job-1", "status": "queued", "request": request.__dict__}

        def list(self):
            return [{"id": "job-1", "status": "queued"}]

        def get(self, job_id):
            return {"id": job_id, "status": "succeeded"}

        def retry(self, job_id):
            return {"id": "job-2", "status": "queued", "retried_from": job_id}

    monkeypatch.setattr(dashboard_api, "jobs", FakeJobs())
    client = TestClient(dashboard_api.app)

    created = client.post("/api/jobs", json={"action": "source_health_check"})
    listed = client.get("/api/jobs")
    fetched = client.get("/api/jobs/job-1")
    retried = client.post("/api/jobs/job-1/retry")

    assert created.status_code == 200
    assert listed.json()["jobs"][0]["id"] == "job-1"
    assert fetched.json()["status"] == "succeeded"
    assert retried.json()["retried_from"] == "job-1"
