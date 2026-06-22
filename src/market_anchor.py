"""
market_anchor.py — Âncora de mercado para probabilidade de campeão.

Implementa o modo title_anchor: aplica peso de mercado na prob. de campeão
com limite máximo de divergência, preservando o modelo original para auditoria.
"""
from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ANCHOR_ALERT_THRESHOLD_PP = 3.0

# Labels legíveis para cada anchor_reason — usados no TXT e expostos ao frontend
ANCHOR_REASON_LABELS: dict[str, str] = {
    "capped_above_market":      "Modelo muito acima do mercado (cap aplicado)",
    "capped_below_market":      "Modelo muito abaixo do mercado (cap aplicado)",
    "above_market_in_band":     "Modelo acima do mercado (dentro da banda)",
    "below_market_in_band":     "Modelo abaixo do mercado (dentro da banda)",
    "within_market_band":       "Alinhado com o mercado",
    "missing_market_odds":      "Sem odds de mercado",
    "insufficient_market_coverage": "Cobertura de mercado insuficiente",
}

DEFAULT_ANCHOR_CONFIG: dict[str, Any] = {
    "enabled": True,
    "market_weight": 0.50,
    "model_weight": 0.50,
    "max_positive_delta_pp": 5.0,
    "max_negative_delta_pp": 5.0,
    "min_market_coverage_teams": 12,
    "renormalize_after_anchor": True,
}

ANCHOR_FIELDS = [
    "team",
    "group",
    "model_winner_pct",
    "market_winner_pct",
    "anchor_winner_pct",
    "delta_model_vs_market_pp",
    "delta_anchor_vs_market_pp",
    "adjustment_applied_pp",
    "anchor_reason",
    "market_rank",
    "model_rank",
    "anchor_rank",
]


def load_anchor_config(weights_path: str | Path = "data/model_weights.json") -> dict[str, Any]:
    """Lê config de âncora de model_weights.json ou retorna o padrão."""
    path = Path(weights_path)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            anchor = payload.get("market_title_anchor")
            if isinstance(anchor, dict):
                merged = {**DEFAULT_ANCHOR_CONFIG, **anchor}
                return merged
        except (json.JSONDecodeError, OSError):
            pass
    return {**DEFAULT_ANCHOR_CONFIG}


def normalize_market_probabilities(
    market_probs_raw: dict[str, float],
) -> dict[str, float]:
    """Normaliza probabilidades implícitas de mercado removendo overround."""
    total = sum(market_probs_raw.values())
    if total <= 0:
        return {}
    return {team: prob / total for team, prob in market_probs_raw.items()}


def apply_title_anchor(
    model_rows: list[dict[str, Any]],
    market_probs_raw: dict[str, float],
    config: dict[str, Any] | None = None,
    group_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Aplica âncora de mercado nas probabilidades de campeão.

    Parâmetros
    ----------
    model_rows:
        Linhas do modelo com campos 'team' e 'winner_pct'.
    market_probs_raw:
        Probabilidades implícitas brutas do mercado (ainda com overround).
        Ex: {France: 0.2, Spain: 0.1428...}
    config:
        Parâmetros da âncora (ver DEFAULT_ANCHOR_CONFIG).
    group_map:
        Mapa {team: group} para enriquecer saída.

    Retorna
    -------
    Lista de dicts com todos os campos ANCHOR_FIELDS.
    """
    cfg = {**DEFAULT_ANCHOR_CONFIG, **(config or {})}
    group_map = group_map or {}

    market_weight = float(cfg["market_weight"])
    model_weight = float(cfg["model_weight"])
    max_pos = float(cfg["max_positive_delta_pp"])
    max_neg = float(cfg["max_negative_delta_pp"])
    min_coverage = int(cfg["min_market_coverage_teams"])
    renorm = bool(cfg["renormalize_after_anchor"])

    # Normaliza o mercado
    market_probs = normalize_market_probabilities(market_probs_raw)

    if len(market_probs) < min_coverage:
        # Cobertura insuficiente: retorna modelo sem ajuste
        return _no_anchor_rows(model_rows, market_probs, group_map, reason="insufficient_market_coverage")

    # Ranking do modelo
    model_sorted = sorted(model_rows, key=lambda r: float(r.get("winner_pct") or 0), reverse=True)
    model_rank_map = {row["team"]: idx + 1 for idx, row in enumerate(model_sorted)}

    # Ranking do mercado
    market_sorted = sorted(market_probs.items(), key=lambda x: x[1], reverse=True)
    market_rank_map = {team: idx + 1 for idx, (team, _) in enumerate(market_sorted)}

    anchor_rows: list[dict[str, Any]] = []
    anchor_winner_pct_map: dict[str, float] = {}

    for row in model_rows:
        team = row["team"]
        model_pct = float(row.get("winner_pct") or 0)
        group = group_map.get(team) or row.get("group") or ""

        if team not in market_probs:
            # Sem odds de mercado: mantém modelo
            anchor_rows.append({
                "team": team,
                "group": group,
                "model_winner_pct": round(model_pct, 4),
                "market_winner_pct": None,
                "anchor_winner_pct": round(model_pct, 4),
                "delta_model_vs_market_pp": None,
                "delta_anchor_vs_market_pp": None,
                "adjustment_applied_pp": 0.0,
                "anchor_reason": "missing_market_odds",
                "market_rank": None,
                "model_rank": model_rank_map.get(team),
                "anchor_rank": None,  # preenchido após renorm
            })
            anchor_winner_pct_map[team] = model_pct
            continue

        market_pct = market_probs[team] * 100
        delta_model = model_pct - market_pct

        # Média ponderada
        anchor_raw = model_pct * model_weight + market_pct * market_weight

        # Limites máximos de divergência em relação ao mercado
        max_allowed = market_pct + max_pos
        min_allowed = max(market_pct - max_neg, 0.0)

        if anchor_raw > max_allowed:
            anchor_pct = max_allowed
            reason = "capped_above_market"
        elif anchor_raw < min_allowed:
            anchor_pct = min_allowed
            reason = "capped_below_market"
        else:
            anchor_pct = anchor_raw
            abs_delta = abs(delta_model)
            if abs_delta < 1.0:
                reason = "within_market_band"
            elif delta_model > 0:
                reason = "above_market_in_band"
            else:
                reason = "below_market_in_band"

        adjustment = anchor_pct - model_pct
        anchor_rows.append({
            "team": team,
            "group": group,
            "model_winner_pct": round(model_pct, 4),
            "market_winner_pct": round(market_pct, 4),
            "anchor_winner_pct": round(anchor_pct, 4),
            "delta_model_vs_market_pp": round(delta_model, 4),
            "delta_anchor_vs_market_pp": round(anchor_pct - market_pct, 4),
            "adjustment_applied_pp": round(adjustment, 4),
            "anchor_reason": reason,
            "market_rank": market_rank_map.get(team),
            "model_rank": model_rank_map.get(team),
            "anchor_rank": None,  # preenchido após renorm
        })
        anchor_winner_pct_map[team] = anchor_pct

    # Renormalização
    if renorm:
        anchor_winner_pct_map = _renormalize(anchor_winner_pct_map, model_rows)
        for row in anchor_rows:
            team = row["team"]
            row["anchor_winner_pct"] = round(anchor_winner_pct_map.get(team, row["anchor_winner_pct"]), 4)
            if row["market_winner_pct"] is not None:
                row["delta_anchor_vs_market_pp"] = round(
                    row["anchor_winner_pct"] - row["market_winner_pct"], 4
                )
            row["adjustment_applied_pp"] = round(
                row["anchor_winner_pct"] - row["model_winner_pct"], 4
            )

    # Ranking final anchor
    anchor_sorted = sorted(anchor_rows, key=lambda r: float(r["anchor_winner_pct"] or 0), reverse=True)
    anchor_rank_map = {r["team"]: idx + 1 for idx, r in enumerate(anchor_sorted)}
    for row in anchor_rows:
        row["anchor_rank"] = anchor_rank_map.get(row["team"])

    return sorted(anchor_rows, key=lambda r: float(r["anchor_winner_pct"] or 0), reverse=True)


def _renormalize(
    pct_map: dict[str, float],
    original_rows: list[dict[str, Any]],
) -> dict[str, float]:
    """
    Renormaliza para que a soma de todas as seleções fique coerente.
    Mantém a soma das probabilidades original.
    """
    total_model = sum(float(r.get("winner_pct") or 0) for r in original_rows)
    total_anchor = sum(pct_map.values())
    if total_anchor <= 0:
        return pct_map
    scale = total_model / total_anchor
    return {team: pct * scale for team, pct in pct_map.items()}


def _no_anchor_rows(
    model_rows: list[dict[str, Any]],
    market_probs: dict[str, float],
    group_map: dict[str, str],
    reason: str,
) -> list[dict[str, Any]]:
    model_sorted = sorted(model_rows, key=lambda r: float(r.get("winner_pct") or 0), reverse=True)
    model_rank_map = {row["team"]: idx + 1 for idx, row in enumerate(model_sorted)}
    market_sorted = sorted(market_probs.items(), key=lambda x: x[1], reverse=True)
    market_rank_map = {team: idx + 1 for idx, (team, _) in enumerate(market_sorted)}
    rows = []
    for idx, row in enumerate(model_sorted):
        team = row["team"]
        model_pct = float(row.get("winner_pct") or 0)
        market_raw = market_probs.get(team)
        market_pct = market_raw * 100 if market_raw is not None else None
        rows.append({
            "team": team,
            "group": group_map.get(team) or row.get("group") or "",
            "model_winner_pct": round(model_pct, 4),
            "market_winner_pct": round(market_pct, 4) if market_pct is not None else None,
            "anchor_winner_pct": round(model_pct, 4),
            "delta_model_vs_market_pp": round(model_pct - market_pct, 4) if market_pct is not None else None,
            "delta_anchor_vs_market_pp": round(0.0, 4) if market_pct is not None else None,
            "adjustment_applied_pp": 0.0,
            "anchor_reason": reason,
            "market_rank": market_rank_map.get(team),
            "model_rank": model_rank_map.get(team),
            "anchor_rank": idx + 1,
        })
    return rows


def build_anchor_summary(anchor_rows: list[dict[str, Any]], market_probs_raw: dict[str, float]) -> dict[str, Any]:
    """Gera metadados sobre a operação de âncora."""
    with_odds = [r for r in anchor_rows if r.get("market_winner_pct") is not None]
    without_odds = [r for r in anchor_rows if r.get("market_winner_pct") is None]

    total_raw = sum(market_probs_raw.values())
    overround_pct = total_raw * 100 if total_raw else None

    deltas = [r["delta_model_vs_market_pp"] for r in with_odds if r.get("delta_model_vs_market_pp") is not None]
    biggest_above = max((r for r in with_odds if (r.get("delta_model_vs_market_pp") or 0) > 0),
                        key=lambda r: r["delta_model_vs_market_pp"], default=None)
    biggest_below = min((r for r in with_odds if (r.get("delta_model_vs_market_pp") or 0) < 0),
                        key=lambda r: r["delta_model_vs_market_pp"], default=None)

    alerts = [
        r for r in with_odds
        if abs(r.get("delta_model_vs_market_pp") or 0) >= ANCHOR_ALERT_THRESHOLD_PP
    ]

    return {
        "teams_with_odds": len(with_odds),
        "teams_without_odds": len(without_odds),
        "overround_pct": round(overround_pct, 2) if overround_pct else None,
        "biggest_above_market": {
            "team": biggest_above["team"],
            "delta_pp": round(biggest_above["delta_model_vs_market_pp"], 2),
        } if biggest_above else None,
        "biggest_below_market": {
            "team": biggest_below["team"],
            "delta_pp": round(biggest_below["delta_model_vs_market_pp"], 2),
        } if biggest_below else None,
        "alerts_count": len(alerts),
        "alerts": [
            {
                "team": r["team"],
                "delta_pp": round(r["delta_model_vs_market_pp"], 2),
                "direction": "above" if r["delta_model_vs_market_pp"] > 0 else "below",
            }
            for r in sorted(alerts, key=lambda r: abs(r["delta_model_vs_market_pp"]), reverse=True)
        ],
    }


def write_title_anchor_outputs(
    anchor_rows: list[dict[str, Any]],
    market_probs_raw: dict[str, float],
    market_mode: str = "title_anchor",
    output_dir: str | Path = "output",
) -> dict[str, Any]:
    """Escreve CSV, JSON e TXT do anchor."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    summary = build_anchor_summary(anchor_rows, market_probs_raw)

    # CSV
    csv_path = out / "market_title_anchor.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ANCHOR_FIELDS)
        writer.writeheader()
        writer.writerows(anchor_rows)

    # JSON
    json_path = out / "market_title_anchor.json"
    payload = {
        "market_mode": market_mode,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "summary": summary,
        "rows": anchor_rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # TXT
    txt_path = out / "market_title_anchor_report.txt"
    lines = _build_anchor_report_lines(anchor_rows, summary, market_mode)
    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    return {"csv": str(csv_path), "json": str(json_path), "txt": str(txt_path), "summary": summary}


def _build_anchor_report_lines(
    anchor_rows: list[dict[str, Any]],
    summary: dict[str, Any],
    market_mode: str,
) -> list[str]:
    lines = [
        "Market Title Anchor Report",
        "",
        f"market_mode: {market_mode}",
        f"Gerado em: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "=== Resumo ===",
        f"Seleções com odds:    {summary['teams_with_odds']}",
        f"Seleções sem odds:    {summary['teams_without_odds']}",
    ]
    if summary.get("overround_pct") is not None:
        lines.append(f"Overround:            {summary['overround_pct']:.2f}%")
    if summary.get("biggest_above_market"):
        t = summary["biggest_above_market"]
        lines.append(f"Maior acima do merc:  {t['team']} {t['delta_pp']:+.2f} p.p.")
    if summary.get("biggest_below_market"):
        t = summary["biggest_below_market"]
        lines.append(f"Maior abaixo do merc: {t['team']} {t['delta_pp']:+.2f} p.p.")
    lines.append(f"Alertas (>= 3 p.p.):  {summary['alerts_count']}")

    lines += ["", "=== Top 15 — Modelo Mercado (anchor_winner_pct) ===",
              f"{'Seleção':<22} {'Modelo':>8} {'Mercado':>8} {'Ancorado':>9} {'Δ Mod-Merc':>11}  Diagnóstico"]
    for row in anchor_rows[:15]:
        model_s = f"{row['model_winner_pct']:.2f}%"
        market_s = f"{row['market_winner_pct']:.2f}%" if row['market_winner_pct'] is not None else "n/d"
        anchor_s = f"{row['anchor_winner_pct']:.2f}%"
        delta_s = f"{row['delta_model_vs_market_pp']:+.2f} p.p." if row['delta_model_vs_market_pp'] is not None else "n/d"
        reason_raw = row.get("anchor_reason", "")
        reason_label = ANCHOR_REASON_LABELS.get(reason_raw, reason_raw)
        lines.append(f"{row['team']:<22} {model_s:>8} {market_s:>8} {anchor_s:>9} {delta_s:>11}  {reason_label}")

    if summary.get("alerts"):
        lines += ["", "=== Alertas (|Δ| >= 3 p.p.) ==="]
        for alert in summary["alerts"]:
            direction = "acima" if alert["direction"] == "above" else "abaixo"
            lines.append(f"ALERTA: {alert['team']} está {alert['delta_pp']:+.2f} p.p. {direction} do mercado.")

    return lines


def write_market_alerts(
    anchor_rows: list[dict[str, Any]],
    output_dir: str | Path = "output",
    threshold_pp: float = ANCHOR_ALERT_THRESHOLD_PP,
) -> dict[str, Any]:
    """Escreve market_alerts.json e market_alerts.txt."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    alerts = []
    for row in anchor_rows:
        delta = row.get("delta_model_vs_market_pp")
        if delta is None or abs(delta) < threshold_pp:
            continue
        alerts.append({
            "team": row["team"],
            "group": row.get("group", ""),
            "model_winner_pct": row["model_winner_pct"],
            "market_winner_pct": row["market_winner_pct"],
            "anchor_winner_pct": row["anchor_winner_pct"],
            "delta_pp": round(delta, 4),
            "direction": "above" if delta > 0 else "below",
            "severity": "high" if abs(delta) >= 8 else "medium" if abs(delta) >= 5 else "low",
        })
    alerts.sort(key=lambda a: abs(a["delta_pp"]), reverse=True)

    payload = {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "threshold_pp": threshold_pp,
        "alert_count": len(alerts),
        "alerts": alerts,
    }

    json_path = out / "market_alerts.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["Market Alerts", "", f"Threshold: {threshold_pp:.1f} p.p.", f"Total alertas: {len(alerts)}", ""]
    for alert in alerts:
        direction = "acima" if alert["direction"] == "above" else "abaixo"
        lines.append(
            f"ALERTA: {alert['team']} está {alert['delta_pp']:+.2f} p.p. {direction} do mercado. "
            f"(modelo={alert['model_winner_pct']:.2f}% | mercado={alert['market_winner_pct']:.2f}% | ancorado={alert['anchor_winner_pct']:.2f}%)"
        )

    txt_path = out / "market_alerts.txt"
    txt_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    return {"json": str(json_path), "txt": str(txt_path), "alerts": alerts}
