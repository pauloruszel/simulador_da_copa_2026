from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandRequest:
    action: str
    team: str = "Brasil"
    simulations: int = 50000
    seed: int | None = 42
    market_mode: str | None = None


def available_actions() -> list[dict[str, str]]:
    return [
        {"action": "source_health_check",         "label": "Checar fontes"},
        {"action": "dry_run_multisource",          "label": "Dry-run multi-source"},
        {"action": "update_results",               "label": "Atualizar resultados"},
        {"action": "fetch_market_odds",            "label": "Atualizar odds"},
        {"action": "import_market_odds",           "label": "Importar CSV de odds"},
        {"action": "market_comparison",            "label": "Comparar modelo x mercado"},
        {"action": "odds_fetch_periodic",          "label": "Coletar odds periódico"},
        {"action": "backtest",                     "label": "Backtest"},
        {"action": "tune_weights",                 "label": "Otimizar pesos"},
        {"action": "workflow_team",                "label": "Workflow do time"},
        {"action": "workflow_global",              "label": "Workflow global"},
        # Botões de odds com market_mode explícito
        {"action": "odds_workflow_anchor",         "label": "Workflow com odds — Corrigir campeão pelo mercado"},
        {"action": "odds_workflow_benchmark",      "label": "Workflow com odds — Benchmark"},
        {"action": "odds_workflow_experimental",   "label": "Workflow com odds — Ajuste experimental de rating"},
        # Alias legado (usa title_anchor por padrão)
        {"action": "odds_workflow",                "label": "Workflow com odds"},
    ]


def run_dashboard_command(
    request: CommandRequest,
    timeout_seconds: int | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    workdir = Path(root) if root is not None else Path.cwd()
    args = _args_for(request)
    started_at = _now()
    result = subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=workdir,
        text=True,
        capture_output=True,
        timeout=timeout_seconds if timeout_seconds is not None else _timeout_for(request),
        check=False,
    )
    payload = {
        "action": request.action,
        "command": " ".join(["python", "main.py", *args]),
        "returncode": result.returncode,
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "started_at": started_at,
        "finished_at": _now(),
    }
    _write_latest(payload, workdir)
    return payload


def _args_for(request: CommandRequest) -> list[str]:
    seed_args = ["--seed", str(request.seed)] if request.seed is not None else []
    common_sim = ["--simulations", str(request.simulations), *seed_args]

    match request.action:
        case "source_health_check":
            return ["--source-health-check"]
        case "dry_run_multisource":
            return ["--dry-run-multisource"]
        case "update_results":
            return ["--update-results-multisource-only"]
        case "fetch_market_odds":
            return ["--fetch-market-odds-only"]
        case "odds_fetch_periodic":
            return ["--fetch-market-odds-only", "--market-odds-runs", "4", "--market-odds-interval-minutes", "30"]
        case "import_market_odds":
            return ["--import-market-odds"]
        case "market_comparison":
            return ["--market-comparison"]
        case "backtest":
            return ["--backtest"]
        case "tune_weights":
            return ["--tune-weights"]
        case "workflow_team":
            return ["--workflow", "full", "--team", request.team, "--global-report", *common_sim]
        case "workflow_global":
            return ["--workflow", "full", "--all-teams", *common_sim]
        # ── novos botões de odds ───────────────────────────────────────────
        case "odds_workflow_anchor":
            return ["--workflow", "odds", "--all-teams", "--market-mode", "title_anchor", *common_sim]
        case "odds_workflow_benchmark":
            return ["--workflow", "odds", "--all-teams", "--market-mode", "benchmark", *common_sim]
        case "odds_workflow_experimental":
            return ["--workflow", "odds", "--all-teams", "--market-mode", "rating_adjustment", *common_sim]
        # ── alias legado: usa title_anchor por padrão ─────────────────────
        case "odds_workflow":
            mode = request.market_mode or "title_anchor"
            return ["--workflow", "odds", "--all-teams", "--market-mode", mode, *common_sim]
        case _:
            allowed = ", ".join(item["action"] for item in available_actions())
            raise ValueError(f"Acao nao permitida: {request.action}. Permitidas: {allowed}")


def _timeout_for(request: CommandRequest) -> int:
    if request.action == "odds_fetch_periodic":
        return 4 * 30 * 60 + 300
    if request.action in {"odds_workflow", "odds_workflow_anchor", "odds_workflow_benchmark", "odds_workflow_experimental"}:
        return 1800
    return 900


def _write_latest(payload: dict[str, Any], root: Path) -> None:
    command_log_dir = root / "output" / "dashboard_commands"
    command_log_dir.mkdir(parents=True, exist_ok=True)
    (command_log_dir / "latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()
