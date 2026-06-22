from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.command_runner import CommandRequest, available_actions, run_dashboard_command
from backend.job_manager import DashboardJobManager
from backend.report_store import ReportStore


app = FastAPI(title="Simulador Copa 2026 Dashboard API")
store = ReportStore()
jobs = DashboardJobManager()


class RunCommandPayload(BaseModel):
    action: str
    team: str = "Brasil"
    simulations: int = Field(default=50000, ge=1, le=500000)
    seed: int | None = 42
    market_mode: str | None = None


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "reports": len(store.available_reports())}


@app.get("/api/dashboard")
def dashboard(model: str = Query(default="balanced")) -> dict:
    return store.dashboard_summary(model=model)


@app.get("/api/dashboard/full")
def full_dashboard(model: str = Query(default="balanced")) -> dict:
    return store.full_dashboard(model=model)


@app.get("/api/global")
def global_report() -> dict:
    return store.global_report()


@app.get("/api/market")
def market_report() -> dict:
    """Retorna dados da aba Mercado: anchor, alerts, odds."""
    return store.market_report()


@app.get("/api/workflows/latest")
def latest_workflow() -> dict:
    latest = store.latest_workflow(default={})
    if not latest:
        raise HTTPException(status_code=404, detail="Workflow consolidado nao encontrado")
    return latest


@app.get("/api/reports")
def reports() -> dict:
    return {"reports": store.available_reports()}


@app.get("/api/reports/{name:path}")
def report_file(name: str) -> dict:
    try:
        return store.report_text(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Relatorio nao encontrado: {name}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/teams/{team}")
def team_report(team: str, model: str = Query(default="balanced")) -> dict:
    report = store.team_report(team, model=model)
    if not report["team"]:
        raise HTTPException(status_code=404, detail=f"Time nao encontrado nos relatorios: {team}")
    return report


@app.get("/api/commands")
def commands() -> dict:
    return {"actions": available_actions()}


@app.post("/api/commands/run")
def run_command(payload: RunCommandPayload) -> dict:
    try:
        return run_dashboard_command(CommandRequest(**payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs")
def submit_job(payload: RunCommandPayload) -> dict:
    try:
        return jobs.submit(CommandRequest(**payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"jobs": jobs.list()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return jobs.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job nao encontrado: {job_id}") from exc


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    try:
        return jobs.retry(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job nao encontrado: {job_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        return jobs.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Job nao encontrado: {job_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
