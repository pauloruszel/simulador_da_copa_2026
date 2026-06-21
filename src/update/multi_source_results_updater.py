from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.external.base_client import UnsupportedDataTypeError
from src.external.fifa_official_client import FifaOfficialClient
from src.external.news_crosscheck_client import NewsCrosscheckClient
from src.external.openfootball_client import OpenFootballClient
from src.external.wikipedia_scraper import WikipediaWorldCupScraper
from src.storage.json_store import JsonStore

from .match_data_resolver import match_external_to_local, resolve_match_updates, validate_resolved_matches


class MultiSourceResultsUpdater:
    def __init__(self, store: JsonStore | None = None) -> None:
        self.store = store or JsonStore()
        self.config = self.store.read("data/source_priority.json", {"sources": [], "field_priority": {}})
        self.source_configs = {source["name"]: source for source in self.config.get("sources", [])}
        self.report: dict[str, Any] = {}

    def update(self, dry_run: bool = False, allow_future_results: bool = False) -> dict[str, Any]:
        local = self.store.read("data/matches.json", [])
        fetch_report, source_matches = self._fetch_all()
        if not any(source_matches.values()):
            self.report = self._empty_report(fetch_report, dry_run)
            self._write_reports(self.report)
            return self.report
        resolved = resolve_match_updates(
            local,
            source_matches,
            self.source_configs,
            self.config.get("field_priority", {}),
            allow_future_results=allow_future_results,
        )
        validate_resolved_matches(resolved["matches"], expected_total=len(local))
        changed = resolved["matches"] != local
        snapshot = None
        if changed and not dry_run:
            snapshot = self._snapshot_matches(local)
            self.store.write("data/matches.json", resolved["matches"])
        self.report = {
            "dry_run": dry_run,
            "snapshot": str(snapshot) if snapshot else None,
            "sources": fetch_report,
            "total_by_source": {name: len(matches) for name, matches in source_matches.items()},
            "matches_read_by_source": {name: len(matches) for name, matches in source_matches.items()},
            "candidate_rows": resolved["candidate_rows"],
            "candidate_matches": resolved["candidate_matches"],
            "updated": len(resolved["changed"]),
            "changed_real": len(resolved["changed"]),
            "metadata_only": len(resolved["metadata_only"]),
            "non_final_score_detected": len(resolved.get("non_final_score_matches", [])),
            "unchanged": resolved["unchanged"],
            "skipped": resolved["skipped"],
            "ignored_placeholders": resolved["ignored_placeholders"],
            "changed_matches": resolved["changed"],
            "metadata_only_matches": resolved["metadata_only"],
            "non_final_score_matches": resolved.get("non_final_score_matches", []),
            "conflicts": resolved["conflicts"],
            "warnings": resolved["warnings"],
            "fields_by_source": resolved["fields_by_source"],
            "manual_review": resolved["conflicts"],
            "allow_future_results": allow_future_results,
        }
        self._write_reports(self.report)
        self._write_group_integrity_report(resolved["matches"], resolved["warnings"])
        return self.report

    def audit_group(self, group: str) -> dict[str, Any]:
        group = group.strip().upper()
        matches = [match for match in self.store.read("data/matches.json", []) if match.get("group") == group]
        report = {"group": group, "matches": matches}
        self._write_group_audit(report)
        return report

    def audit_match(self, match_id: str) -> dict[str, Any]:
        match_id = str(match_id).strip().upper()
        local_matches = self.store.read("data/matches.json", [])
        local = next((m for m in local_matches if str(m.get("id", "")).upper() == match_id), None)
        fetch_report, source_matches = self._fetch_all()
        source_rows = []
        if local:
            local_idx = local_matches.index(local)
            for source, rows in source_matches.items():
                for row in rows:
                    try:
                        idx = match_external_to_local(local_matches, row)
                    except Exception:
                        idx = None
                    if idx == local_idx:
                        source_rows.append(row | {"source": source})
        report = {"match_id": match_id, "local": local, "sources": fetch_report, "source_rows": source_rows}
        self._write_match_audit(report)
        return report

    def health_check(self) -> dict[str, Any]:
        rows = []
        for source in self._enabled_sources():
            client = self._client(source["name"])
            try:
                matches = client.fetch_matches()
                status = "ok" if matches else "empty"
                message = "Fonte respondeu." if matches else "Fonte respondeu, mas nao retornou partidas normalizadas."
                rows.append({
                    "source": source["name"],
                    "status": status,
                    "matches": len(matches),
                    "message": message,
                })
            except Exception as exc:
                rows.append({
                    "source": source["name"],
                    "status": "error",
                    "matches": 0,
                    "message": str(exc),
                })
        self._write_health_report(rows)
        return {"sources": rows}

    def _fetch_all(self) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        fetch_report = []
        source_matches = {}
        for source in self._enabled_sources():
            name = source["name"]
            client = self._client(name)
            try:
                matches = client.fetch_matches()
                source_matches[name] = matches
                status = "ok" if matches else "empty"
                message = "ok" if matches else "Fonte respondeu, mas nao retornou partidas normalizadas."
                fetch_report.append({"source": name, "status": status, "matches": len(matches), "message": message})
            except UnsupportedDataTypeError as exc:
                source_matches[name] = []
                fetch_report.append({"source": name, "status": "skipped", "matches": 0, "message": str(exc)})
            except Exception as exc:
                source_matches[name] = []
                fetch_report.append({"source": name, "status": "error", "matches": 0, "message": str(exc)})
        return fetch_report, source_matches

    def _enabled_sources(self) -> list[dict[str, Any]]:
        return sorted(
            [source for source in self.config.get("sources", []) if source.get("enabled")],
            key=lambda source: source.get("priority", 99),
        )

    def _client(self, name: str):
        if name == "fifa_official":
            return FifaOfficialClient()
        if name == "openfootball_json":
            return OpenFootballClient()
        if name == "wikipedia":
            return WikipediaWorldCupScraper(raw_dir="data/raw/wikipedia")
        if name == "news_crosscheck":
            return NewsCrosscheckClient()
        raise UnsupportedDataTypeError(f"Fonte desconhecida: {name}")

    def _snapshot_matches(self, local: list[dict[str, Any]]) -> Path:
        out = Path(self.store.root) / "data/snapshots"
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
        path = out / f"matches_{stamp}.json"
        path.write_text(json.dumps(local, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def _empty_report(self, fetch_report: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
        return {
            "dry_run": dry_run,
            "snapshot": None,
            "sources": fetch_report,
            "total_by_source": {},
            "matches_read_by_source": {},
            "candidate_rows": 0,
            "candidate_matches": 0,
            "updated": 0,
            "changed_real": 0,
            "metadata_only": 0,
            "non_final_score_detected": 0,
            "unchanged": 0,
            "skipped": 0,
            "ignored_placeholders": [],
            "changed_matches": [],
            "metadata_only_matches": [],
            "non_final_score_matches": [],
            "conflicts": [],
            "warnings": [],
            "fields_by_source": {},
            "manual_review": [],
            "allow_future_results": False,
        }

    def _write_reports(self, report: dict[str, Any]) -> None:
        out = Path(self.store.root) / "output"
        out.mkdir(parents=True, exist_ok=True)
        (out / "multisource_update_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        lines = [
            "Multi-source Results Update",
            f"Modo: {'dry-run' if report.get('dry_run') else 'aplicar alteracoes'}",
            f"allow_future_results: {report.get('allow_future_results', False)}",
            f"partidas_lidas_por_fonte: {report.get('matches_read_by_source', {})}",
            f"partidas_candidatas_ao_merge: {report.get('candidate_matches', 0)} jogos / {report.get('candidate_rows', 0)} registros de fontes",
            f"partidas_alteradas_de_fato: {report.get('changed_real', 0)}",
            f"partidas_com_live_score_detectado: {report.get('non_final_score_detected', 0)}",
            f"partidas_sem_mudanca: {report.get('unchanged', 0)}",
            f"partidas_somente_metadados: {report.get('metadata_only', 0)}",
            f"partidas_ignoradas: {report.get('skipped', 0)}",
            f"partidas_com_conflito: {len(report.get('conflicts', []))}",
            f"Partidas ignoradas por placeholder de mata-mata: {len(report.get('ignored_placeholders', []))}",
            f"Conflitos: {len(report.get('conflicts', []))}",
            f"Warnings: {len(report.get('warnings', []))}",
            "",
            "Resumo de campos criticos:",
            f"- score_final_updated: {_field_total(report, 'score_final_updated')}",
            f"- live_score_detected: {_field_total(report, 'live_score_detected')}",
            f"- live_score_not_applied: {_field_total(report, 'live_score_not_applied')}",
            f"- status_updated: {_field_total(report, 'status')}",
            f"- timezone_corrected/date_updated: {_field_total(report, 'date')}",
            "",
            "Fontes consultadas:",
        ]
        for source in report.get("sources", []):
            lines.append(f"- {source['source']}: {source['status']} ({source['matches']} partidas) - {source['message']}")
        lines += ["", "Jogos alterados:"]
        lines += [f"- {item}" for item in report.get("changed_matches", [])] or ["- nenhum"]
        lines += ["", "Jogos com placar nao-final detectado e nao aplicado:"]
        lines += [f"- {item}" for item in report.get("non_final_score_matches", [])] or ["- nenhum"]
        lines += ["", "Jogos somente com metadados/verificacao atualizados:"]
        lines += [f"- {item}" for item in report.get("metadata_only_matches", [])] or ["- nenhum"]
        lines += ["", "Campos atualizados por fonte:"]
        for source, fields in report.get("fields_by_source", {}).items():
            lines.append(f"- {source}:")
            for field in ("score_final_updated", "score", "live_score_detected", "live_score_not_applied", "status", "date", "venue", "provider_id", "metadata"):
                lines.append(f"  - {field}: {fields.get(field, 0)}")
        if not report.get("fields_by_source"):
            lines.append("- nenhum")
        lines += ["", "Warnings:"]
        lines += [
            f"- {item['match_id']} {item['home']} x {item['away']} ({item['source']}): {item['message']}"
            for item in report.get("warnings", [])
        ] or ["- nenhum"]
        lines += ["", "Ignoradas por placeholder de mata-mata:"]
        lines += [
            f"- {item['match_id']} {item['home']} x {item['away']} ({item['source']})"
            for item in report.get("ignored_placeholders", [])
        ] or ["- nenhum"]
        lines += ["", "Jogos que exigem revisao manual:"]
        lines += [f"- {c['match_id']} {c['home']} x {c['away']}: {c['reason']}" for c in report.get("manual_review", [])] or ["- nenhum"]
        (out / "multisource_update_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._write_conflicts_csv(report.get("conflicts", []), out)

    def _write_group_integrity_report(self, matches: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> None:
        out = Path(self.store.root) / "output"
        out.mkdir(parents=True, exist_ok=True)
        by_group: dict[str, list[dict[str, Any]]] = {}
        for match in matches:
            group = match.get("group")
            if isinstance(group, str) and len(group) == 1 and group.isalpha():
                by_group.setdefault(group, []).append(match)
        lines = ["Group Integrity Report", ""]
        warning_ids = {item.get("match_id") for item in warnings}
        for group in sorted(by_group):
            rows = by_group[group]
            finished = sum(1 for match in rows if match.get("status") == "finished")
            scheduled = sum(1 for match in rows if match.get("status") == "scheduled")
            live = sum(1 for match in rows if match.get("status") in {"live", "halftime"})
            lines.append(f"Grupo {group}: finished={finished}, scheduled={scheduled}, live={live}")
            table = _group_table(rows)
            for row in table:
                lines.append(
                    f"  {row['team']}: {row['points']} pts, SG {row['gd']:+}, GP {row['gf']}, J {row['played']}"
                )
            if finished == len(rows) and rows:
                lines.append("  Alerta: grupo encerrado por resultados salvos.")
            if any(match.get("id") in warning_ids for match in rows):
                lines.append("  Alerta: fonte trouxe placar futuro ignorado neste grupo.")
            lines.append("  Jogos:")
            for match in sorted(rows, key=lambda item: item.get("id", "")):
                score = _score_text(match)
                lines.append(f"  - {match.get('id')}: {match.get('home')} x {match.get('away')} | {match.get('status')} | {score} | {match.get('date', '')}")
            lines.append("")
        if warnings:
            lines.append("Alertas de jogos futuros com placar:")
            for item in warnings:
                lines.append(f"- {item['match_id']} {item['home']} x {item['away']} ({item['source']}) em {item['date']}")
        (out / "group_integrity_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_group_audit(self, report: dict[str, Any]) -> None:
        out = Path(self.store.root) / "output"
        out.mkdir(parents=True, exist_ok=True)
        group = report["group"]
        lines = [f"Audit Group {group}", ""]
        for match in sorted(report["matches"], key=lambda item: item.get("id", "")):
            score_source = _score_source(match)
            warnings = []
            if _has_future_score(match):
                warnings.append("placar em jogo futuro")
            lines.append(
                f"{match.get('id')}: {match.get('home')} x {match.get('away')} | "
                f"{match.get('status')} | {_score_text(match)} | score_source={score_source} | "
                f"last_verified_at={match.get('last_verified_at', '')}"
            )
            if warnings:
                lines.append(f"  warnings: {', '.join(warnings)}")
        (out / f"audit_group_{group}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_match_audit(self, report: dict[str, Any]) -> None:
        out = Path(self.store.root) / "output"
        out.mkdir(parents=True, exist_ok=True)
        match_id = report.get("match_id", "")
        local = report.get("local") or {}
        lines = [f"Audit Match {match_id}", "", "Local:"]
        if local:
            lines += [
                f"  id: {local.get('id')}",
                f"  jogo: {local.get('home')} x {local.get('away')}",
                f"  status: {local.get('status')}",
                f"  score: {_score_text(local)}",
                f"  live_score: {_live_score_text(local)}",
                f"  date: {local.get('date', '')}",
                f"  venue: {local.get('venue', '')}",
                f"  resolved_confidence: {local.get('resolved_confidence', '')}",
                f"  last_verified_at: {local.get('last_verified_at', '')}",
            ]
        else:
            lines.append("  nao encontrado")
        lines += ["", "Fontes:"]
        for row in report.get("source_rows", []):
            normalized_status = row.get("status")
            has_external_score = row.get("home_score") is not None and row.get("away_score") is not None
            final_score_applied = normalized_status == "finished" and has_external_score
            if has_external_score and not final_score_applied:
                decision = "placar externo nao-final detectado e nao aplicado"
                reason = "status nao-final ou unknown"
                external_score = _score_text(row)
            elif final_score_applied:
                decision = "placar final candidato"
                reason = "status final confirmado"
                external_score = _score_text(row)
            else:
                decision = "sem placar final aplicado"
                reason = "fonte sem placar final"
                external_score = "-"
            lines += [
                f"- {row.get('source')}",
                f"  status_raw: {row.get('status_raw', '')}",
                f"  status_normalizado: {normalized_status or ''}",
                f"  placar_bruto/final: {_score_text(row)}",
                f"  placar_externo_detectado: {external_score}",
                f"  placar_final_aplicado: {'sim' if final_score_applied else 'nao'}",
                f"  motivo: {reason}",
                f"  live_score: {_live_score_text(row)}",
                f"  date: {row.get('date', '')}",
                f"  venue: {row.get('venue', '')}",
                f"  decisao: {decision}",
            ]
        if not report.get("source_rows"):
            lines.append("- nenhuma fonte correspondente")
        (out / f"audit_match_{match_id}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_conflicts_csv(self, conflicts: list[dict[str, Any]], out: Path) -> None:
        fields = ["match_id", "home", "away", "field", "local", "external", "sources", "reason"]
        with (out / "source_conflicts.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(conflicts)

    def _write_health_report(self, rows: list[dict[str, Any]]) -> None:
        out = Path(self.store.root) / "output"
        out.mkdir(parents=True, exist_ok=True)
        lines = ["Source Health Check", ""]
        for row in rows:
            lines.append(f"- {row['source']}: {row['status']} ({row['matches']} partidas) - {row['message']}")
        (out / "source_health_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _field_total(report: dict[str, Any], field: str) -> int:
    return sum(int(fields.get(field, 0)) for fields in report.get("fields_by_source", {}).values())


def _score_text(match: dict[str, Any]) -> str:
    if match.get("home_score") is None or match.get("away_score") is None:
        return "-"
    return f"{match['home_score']}-{match['away_score']}"


def _live_score_text(match: dict[str, Any]) -> str:
    if match.get("live_home_score") is None or match.get("live_away_score") is None:
        return "-"
    status = match.get("live_status") or match.get("status") or "live"
    return f"{match['live_home_score']}-{match['live_away_score']} ({status})"


def _score_source(match: dict[str, Any]) -> str:
    for source in match.get("sources", []):
        if "score" in source.get("fields", []):
            return source.get("name", "")
    return ""


def _has_future_score(match: dict[str, Any]) -> bool:
    if match.get("home_score") is None or match.get("away_score") is None:
        return False
    try:
        match_date = datetime.fromisoformat(str(match.get("date", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    if match_date.tzinfo is None:
        match_date = match_date.replace(tzinfo=UTC)
    return match_date.astimezone(UTC) > datetime.now(UTC)


def _group_table(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table: dict[str, dict[str, int | str]] = {}
    for match in matches:
        for team in (match.get("home"), match.get("away")):
            if team:
                table.setdefault(str(team), {"team": str(team), "played": 0, "points": 0, "gf": 0, "ga": 0, "gd": 0})
        if match.get("status") != "finished" or match.get("home_score") is None or match.get("away_score") is None:
            continue
        home, away = str(match.get("home")), str(match.get("away"))
        hs, aw = int(match["home_score"]), int(match["away_score"])
        table[home]["played"] += 1
        table[away]["played"] += 1
        table[home]["gf"] += hs
        table[home]["ga"] += aw
        table[away]["gf"] += aw
        table[away]["ga"] += hs
        if hs > aw:
            table[home]["points"] += 3
        elif aw > hs:
            table[away]["points"] += 3
        else:
            table[home]["points"] += 1
            table[away]["points"] += 1
    for row in table.values():
        row["gd"] = int(row["gf"]) - int(row["ga"])
    return sorted(table.values(), key=lambda row: (int(row["points"]), int(row["gd"]), int(row["gf"])), reverse=True)
