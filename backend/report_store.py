from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
NUMERIC_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


class ReportStore:
    def __init__(self, output_dir: str | Path = OUTPUT_DIR) -> None:
        self.output_dir = Path(output_dir)

    def dashboard_summary(self, model: str = "balanced") -> dict[str, Any]:
        model = self._normalize_model(model)
        teams = self._team_probabilities(model)
        top_title = sorted(teams, key=lambda row: float(row.get("winner_pct") or 0), reverse=True)[:10]
        latest = self.latest_workflow(default={})
        meta = self._dashboard_meta(model, latest)
        return {
            "model": model,
            "available_models": self.available_models(),
            "meta": meta,
            "top_title": top_title,
            "top_final": sorted(teams, key=lambda row: float(row.get("final_pct") or 0), reverse=True)[:10],
            "top_semifinal": sorted(teams, key=lambda row: float(row.get("semifinal_pct") or 0), reverse=True)[:10],
            "report_files": [item["name"] for item in self.available_reports()],
            "reports": self.available_reports(),
            "latest_workflow": latest,
            "status": self._run_status(latest),
        }

    def market_report(self) -> dict[str, Any]:
        """Dados para a aba Mercado: anchor rows, alerts, odds payload."""
        anchor_json = self.read_json("market_title_anchor.json", default={})
        alerts_json = self.read_json("market_alerts.json", default={})
        # odds.json fica em data/, fora de output/ — leitura direta via ROOT
        odds_json = self._read_json_from_root("data/odds.json", default={})
        comparison = self.read_csv("market_comparison.csv")
        rows_with = [r for r in comparison if r.get("market_winner_pct") is not None]
        rows_without = [r for r in comparison if r.get("market_winner_pct") is None]
        return {
            "anchor": anchor_json,
            "alerts": alerts_json,
            "odds_summary": {
                "teams": len((odds_json.get("outrights") or [])),
                "overround_pct": round((odds_json.get("overround") or 0) * 100, 2),
                "last_updated": odds_json.get("last_updated"),
            },
            "comparison": {
                "rows_with_odds": rows_with,
                "rows_without_odds": rows_without,
            },
        }

    def global_report(self) -> dict[str, Any]:
        return {
            "title_ranking": self.read_csv("global_title_ranking.csv"),
            "stage_probabilities": self.read_csv("global_stage_probabilities.csv"),
            "group_outlook": self.read_csv("global_group_outlook.csv"),
            "group_leadership": self.read_csv("global_group_leadership_outlook.csv"),
            "group_qualification": self.read_csv("global_group_qualification_outlook.csv"),
            "model_sensitivity": self.read_csv("global_model_sensitivity.csv"),
            "risk_report": self.read_text("global_risk_report.txt"),
            "latest_report": self.read_text("latest_global_report.txt"),
        }

    def full_dashboard(self, model: str = "balanced") -> dict[str, Any]:
        return {
            "dashboard": self.dashboard_summary(model=model),
            "global": self.global_report(),
            "workflow": self.latest_workflow(default={}),
            "reports": self.available_reports(),
        }

    def team_report(self, team: str, model: str = "balanced") -> dict[str, Any]:
        teams = self._team_probabilities(model)
        row = next((item for item in teams if str(item.get("team", "")).lower() == team.lower()), None)
        paths = self.read_json(f"team_paths_{team}.json", default={})
        if not paths and row:
            paths = self.read_json(f"team_paths_{row['team']}.json", default={})
        return {"team": row, "paths": paths, "model": self._normalize_model(model)}

    def available_reports(self) -> list[dict[str, Any]]:
        if not self.output_dir.exists():
            return []
        reports: list[dict[str, Any]] = []
        for path in sorted(self.output_dir.glob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            modified_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            age_minutes = max(0.0, (datetime.now(UTC) - modified_at).total_seconds() / 60)
            reports.append({
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified_at": modified_at.isoformat(),
                "age_minutes": round(age_minutes, 1),
                "is_stale": age_minutes > 360,
            })
        return reports

    def latest_workflow(self, default: Any = None) -> Any:
        return self.read_json("workflows/latest_full_report.json", default=default)

    def report_text(self, name: str) -> dict[str, Any]:
        path = self._safe_path(name)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(name)
        stat = path.stat()
        return {
            "name": name,
            "content": path.read_text(encoding="utf-8", errors="replace"),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        }

    def available_models(self) -> list[str]:
        rows = self.read_csv("global_stage_probabilities.csv")
        known_order = ["balanced", "tuned", "market_calibrated"]
        models_found = sorted({str(row.get("model")) for row in rows if row.get("model")})
        # retorna na ordem preferida, depois os extras
        ordered = [m for m in known_order if m in models_found]
        extras = [m for m in models_found if m not in known_order]
        return ordered + extras or ["balanced"]

    def read_json(self, name: str, default: Any = None) -> Any:
        path = self._safe_path(name)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_json_from_root(self, relative_path: str, default: Any = None) -> Any:
        """Lê um JSON relativo à raiz do projeto (fora de output/)."""
        path = (ROOT / relative_path).resolve()
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def read_csv(self, name: str) -> list[dict[str, Any]]:
        path = self._safe_path(name)
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as file:
            return [{key: self._typed_value(value) for key, value in row.items()} for row in csv.DictReader(file)]

    def read_text(self, name: str) -> str:
        path = self._safe_path(name)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _team_probabilities(self, model: str) -> list[dict[str, Any]]:
        rows = self.read_csv("global_stage_probabilities.csv")
        if rows:
            selected = [row for row in rows if row.get("model") == model]
            if selected:
                return selected
        probabilities = self.read_json("probabilities.json", default={})
        teams = probabilities.get("teams", []) if isinstance(probabilities, dict) else []
        return teams if isinstance(teams, list) else []

    def _dashboard_meta(self, model: str, latest: dict[str, Any]) -> dict[str, Any]:
        probabilities = self.read_json("probabilities.json", default={})
        meta = probabilities.get("meta", {}) if isinstance(probabilities, dict) else {}
        metrics = latest.get("metrics", {}) if isinstance(latest, dict) else {}
        if metrics:
            meta = {**meta, "simulations": metrics.get("simulations", meta.get("simulations")), "seed": metrics.get("seed", meta.get("seed"))}
        meta["model"] = model
        return meta

    def _run_status(self, latest: dict[str, Any]) -> dict[str, Any]:
        if not latest:
            return {"status": "indisponivel", "observations": ["Nenhum workflow consolidado encontrado."]}
        steps = latest.get("steps", []) or []
        metrics = latest.get("metrics", {}) or {}
        step_by_name = {step.get("name"): step for step in steps}
        observations: list[str] = []
        if step_by_name.get("backtest", {}).get("status") == "skipped":
            observations.append("Backtest não executado neste workflow; métricas de backtest podem aparecer como n/d.")
        if step_by_name.get("tune-weights", {}).get("status") == "skipped":
            observations.append("Tuning não executado neste workflow; pesos do Modelo Ajustado podem ter sido reutilizados.")
        simulations = metrics.get("simulations")
        if isinstance(simulations, (int, float)) and simulations < 100000:
            observations.append("Simulações abaixo de 100.000: bom para exploração, use 200.000 para relatório final.")
        if not observations:
            observations.append("Workflow sem observações críticas.")
        return {
            "status": latest.get("status", "n/d"),
            "recommendation": latest.get("recommendation", "n/d"),
            "best_backtest_model": latest.get("best_backtest_model", "n/d"),
            "observations": observations,
        }

    def _normalize_model(self, model: str) -> str:
        value = (model or "balanced").lower().strip()
        return value if value in {"balanced", "tuned", "market_calibrated"} else "balanced"

    def _safe_path(self, name: str) -> Path:
        path = (self.output_dir / name).resolve()
        root = self.output_dir.resolve()
        if root != path and root not in path.parents:
            raise ValueError(f"Arquivo fora de output/: {name}")
        return path

    @staticmethod
    def _typed_value(value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if stripped == "":
            return ""
        if NUMERIC_RE.match(stripped):
            if "." in stripped:
                return float(stripped)
            return int(stripped)
        return value
