from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.external.base_client import ExternalDataClient, UnsupportedDataTypeError
from src.external.api_football_client import ApiFootballClient
from src.external.elo_client import EloClient
from src.external.fifa_client import FifaClient
from src.external.football_data_client import FootballDataClient
from src.external.odds_client import OddsClient
from src.external.wikipedia_scraper import WikipediaWorldCupScraper
from src.storage.json_store import JsonStore
from src.storage.snapshots import create_data_snapshot

from .odds_updater import normalize_odds
from .rankings_updater import normalize_rankings
from .results_updater import apply_results_update, summarize_result_update_log


class DataUpdater:
    def __init__(self, store: JsonStore | None = None) -> None:
        self.store = store or JsonStore()
        self.sources = self.store.read("data/external_sources.json", {"sources": {}})
        self.log: list[dict[str, Any]] = []

    def run(self, results: bool = True, odds: bool = True, rankings: bool = True) -> list[dict[str, Any]]:
        create_data_snapshot(["data/matches.json", "data/ratings.json", "data/odds.json", "data/fifa_ranking.json"])
        if results:
            self.update_results()
        if odds:
            self.update_odds()
        if rankings:
            self.update_rankings()
        self._write_log()
        return self.log

    def scrape_results(self, dry_run: bool = False) -> list[dict[str, Any]]:
        if not dry_run:
            create_data_snapshot(["data/matches.json"])
        report_payloads = []
        for client in self._clients_for("scraping"):
            try:
                external = client.fetch_matches()
                local = self.store.read("data/matches.json", [])
                updated, lines = apply_results_update(local, external)
                if updated != local and not dry_run:
                    self.store.write("data/matches.json", updated)
                summary = summarize_result_update_log(lines)
                report_payloads.append({
                    "source": client.source_name,
                    "total": len(external),
                    "summary": summary,
                    "lines": lines,
                    "dry_run": dry_run,
                })
                self._event(
                    client.source_name,
                    "scrape_results",
                    "ok",
                    _format_scrape_message(len(external), summary, dry_run),
                    {"summary": summary, "sample": lines[:20]},
                )
            except UnsupportedDataTypeError as exc:
                self._event(client.source_name, "scrape_results", "skipped", str(exc))
            except Exception as exc:
                self._event(client.source_name, "scrape_results", "error", str(exc))
        self._write_scrape_report(report_payloads)
        self._write_log()
        return self.log

    def update_results(self) -> None:
        for client in self._clients_for("matches"):
            try:
                external = client.fetch_matches()
                local = self.store.read("data/matches.json", [])
                updated, lines = apply_results_update(local, external)
                if updated != local:
                    self.store.write("data/matches.json", updated)
                summary = summarize_result_update_log(lines)
                self._event(
                    client.source_name,
                    "results",
                    "ok",
                    _format_scrape_message(len(external), summary),
                    {"summary": summary, "sample": lines[:20]},
                )
            except UnsupportedDataTypeError as exc:
                self._event(client.source_name, "results", "skipped", str(exc))
            except Exception as exc:
                self._event(client.source_name, "results", "error", str(exc))

    def update_odds(self) -> None:
        for client in self._clients_for("odds"):
            try:
                local = self.store.read("data/matches.json", [])
                if hasattr(client, "fetch_odds_for_matches"):
                    odds = client.fetch_odds_for_matches(local)
                else:
                    odds = client.fetch_odds()
                payload = normalize_odds(odds, client.source_name)
                self.store.write("data/odds.json", payload)
                self._event(client.source_name, "odds", "ok", "Odds atualizadas.")
            except UnsupportedDataTypeError as exc:
                self._event(client.source_name, "odds", "skipped", str(exc))
            except Exception as exc:
                self._event(client.source_name, "odds", "error", str(exc))

    def update_rankings(self) -> None:
        for client in self._clients_for("rankings"):
            try:
                payload = normalize_rankings(client.fetch_rankings(), client.source_name)
                target = "data/fifa_ranking.json" if client.source_name == "fifa" else "data/elo_ratings.json"
                self.store.write(target, payload)
                self._event(client.source_name, "rankings", "ok", "Ranking atualizado.")
            except UnsupportedDataTypeError as exc:
                self._event(client.source_name, "rankings", "skipped", str(exc))
            except Exception as exc:
                self._event(client.source_name, "rankings", "error", str(exc))

    def _clients_for(self, category: str) -> list[ExternalDataClient]:
        clients = self._enabled_clients()
        if category == "matches":
            return [c for c in clients if c.source_name in {"fifa", "football_data", "api_football", "wikipedia"}]
        if category == "scraping":
            return [c for c in clients if c.source_name == "wikipedia"]
        if category == "odds":
            return [c for c in clients if c.source_name in {"odds", "api_football"}]
        if category == "rankings":
            return [c for c in clients if c.source_name in {"fifa", "elo"}]
        return []

    def _enabled_clients(self) -> list[ExternalDataClient]:
        out: list[ExternalDataClient] = []
        for name, cfg in self.sources.get("sources", {}).items():
            if not cfg.get("enabled"):
                continue
            if name == "fifa":
                out.append(FifaClient(cfg.get("base_url")))
            elif name == "api_football":
                out.append(ApiFootballClient(
                    cfg.get("base_url"),
                    cfg.get("api_key_env", "API_FOOTBALL_KEY"),
                    int(cfg.get("league", 1)),
                    int(cfg.get("season", 2026)),
                    int(cfg.get("max_odds_fixtures", 10)),
                ))
            elif name == "football_data":
                out.append(FootballDataClient(cfg.get("base_url"), cfg.get("api_key_env", "FOOTBALL_DATA_API_KEY")))
            elif name == "wikipedia":
                out.append(WikipediaWorldCupScraper(cfg.get("url", "https://en.wikipedia.org/wiki/2026_FIFA_World_Cup")))
            elif name == "odds":
                out.append(OddsClient(cfg.get("base_url"), cfg.get("api_key_env", "ODDS_API_KEY")))
            elif name == "elo":
                out.append(EloClient(cfg.get("base_url")))
        return out

    def _event(
        self,
        source: str,
        category: str,
        status: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "source": source,
            "category": category,
            "status": status,
            "message": message,
        }
        if details:
            event["details"] = details
        self.log.append(event)

    def _write_log(self) -> None:
        existing = self.store.read("data/update_log.json", [])
        self.store.write("data/update_log.json", existing + self.log)


    def _write_scrape_report(self, payloads: list[dict[str, Any]]) -> None:
        lines = ["Scrape Results Report", ""]
        if not payloads:
            lines.append("Nenhuma fonte de scraping executada.")
        for payload in payloads:
            summary = payload["summary"]
            changed = [line for line in payload["lines"] if line.startswith("Atualizado jogo")]
            warnings = [
                line for line in payload["lines"]
                if line.startswith("Partida ambigua") or line.startswith("Preservado dado manual")
            ]
            lines += [
                f"Fonte: {payload['source']}",
                f"Modo: {'dry-run' if payload.get('dry_run') else 'aplicar alteracoes'}",
                f"Total de partidas lidas: {payload['total']}",
                f"Partidas atualizadas: {summary['updated']}",
                f"Partidas sem mudanca: {summary['unchanged']}",
                f"Partidas ignoradas: {summary['skipped']}",
                "",
                "Jogos alterados:",
            ]
            lines += [f"- {line}" for line in changed] if changed else ["- nenhum"]
            lines += ["", "Warnings de ambiguidade:"]
            lines += [f"- {line}" for line in warnings] if warnings else ["- nenhum"]
            lines.append("")
        target = Path(self.store.root) / "output/scrape_results_report.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _format_scrape_message(total: int, summary: dict[str, int], dry_run: bool = False) -> str:
    prefix = "[dry-run] " if dry_run else ""
    return (
        f"{prefix}{total} partidas lidas; "
        f"{summary['updated']} atualizadas; "
        f"{summary['unchanged']} sem mudanca; "
        f"{summary['skipped']} ignoradas."
    )
