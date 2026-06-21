from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from backend.command_runner import CommandRequest, run_dashboard_command


@dataclass
class DashboardJob:
    id: str
    request: dict[str, Any]
    status: str
    created_at: str
    retried_from: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class DashboardJobManager:
    def __init__(self, max_workers: int = 1, storage_path: str | Path | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._storage_path = Path(storage_path) if storage_path is not None else Path.cwd() / "output" / "dashboard_jobs" / "jobs.json"
        self._jobs: dict[str, DashboardJob] = {}
        self._futures: dict[str, Future] = {}
        self._lock = Lock()
        self._load()

    def submit(self, request: CommandRequest, retried_from: str | None = None) -> dict[str, Any]:
        job = DashboardJob(
            id=uuid4().hex,
            request=asdict(request),
            status="queued",
            created_at=_now(),
            retried_from=retried_from,
        )
        with self._lock:
            self._jobs[job.id] = job
            self._persist_locked()
        future = self._executor.submit(self._run, job.id, request)
        with self._lock:
            self._futures[job.id] = future
        return self.get(job.id)

    def retry(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status != "failed":
                raise ValueError(f"Apenas jobs com status failed podem ser reenfileirados: {job.status}")
            request = _request_from_payload(job.request)
        return self.submit(request, retried_from=job_id)


    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status not in {"queued", "running"}:
                raise ValueError(f"Apenas jobs queued/running podem ser cancelados: {job.status}")
            future = self._futures.get(job_id)
            if future and not future.running() and future.cancel():
                job.status = "canceled"
                job.finished_at = _now()
                job.error = "Job cancelado antes da execucao."
                self._persist_locked()
                return self._public(job)
            if job.status == "queued":
                job.status = "canceled"
                job.finished_at = _now()
                job.error = "Job cancelado antes da execucao."
                self._persist_locked()
                return self._public(job)
            raise ValueError("Job ja esta em execucao e nao pode ser cancelado com seguranca neste modo local.")

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public(job) for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)]

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise KeyError(job_id)
            return self._public(job)

    def _run(self, job_id: str, request: CommandRequest) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current and current.status == "canceled":
                return
        self._update(job_id, status="running", started_at=_now())
        try:
            result = run_dashboard_command(request)
            status = "succeeded" if result.get("ok") else "failed"
            self._update(job_id, status=status, result=result, finished_at=_now())
        except Exception as exc:  # noqa: BLE001 - surfaced to dashboard user
            self._update(job_id, status="failed", error=str(exc), finished_at=_now())

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)
            self._persist_locked()

    def _public(self, job: DashboardJob) -> dict[str, Any]:
        return {
            "id": job.id,
            "request": job.request,
            "status": job.status,
            "created_at": job.created_at,
            "retried_from": job.retried_from,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "result": job.result,
            "error": job.error,
        }

    def _load(self) -> None:
        if not self._storage_path.exists():
            return
        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, list):
            return

        changed = False
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                job = DashboardJob(
                    id=str(item["id"]),
                    request=dict(item["request"]),
                    status=str(item["status"]),
                    created_at=str(item["created_at"]),
                    retried_from=item.get("retried_from"),
                    started_at=item.get("started_at"),
                    finished_at=item.get("finished_at"),
                    result=item.get("result"),
                    error=item.get("error"),
                )
            except (KeyError, TypeError, ValueError):
                continue

            if job.status in {"queued", "running"}:
                job.status = "failed"
                job.finished_at = job.finished_at or _now()
                job.error = job.error or "Job interrompido antes da conclusao."
                changed = True
            self._jobs[job.id] = job

        if changed:
            with self._lock:
                self._persist_locked()

    def _persist_locked(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [self._public(job) for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)[:100]]
        content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self._storage_path.write_text(content, encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _request_from_payload(payload: dict[str, Any]) -> CommandRequest:
    return CommandRequest(
        action=str(payload["action"]),
        team=str(payload.get("team", "Brasil")),
        simulations=int(payload.get("simulations", 50000)),
        seed=payload.get("seed"),
    )
