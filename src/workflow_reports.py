from __future__ import annotations

import csv
import json
from pathlib import Path


def _pct(value) -> str:
    if value is None:
        return "n/d"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "n/d"


def _fmt_metric(value, decimals: int = 3) -> str:
    if value is None:
        return "n/d"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "n/d"


def _scenario_label(model: str) -> str:
    labels = {
        "balanced": "Cenário Base",
        "tuned": "Cenário Calibrado",
    }
    return labels.get(model, model)


def _simulation_step_message(team: str, team_row: dict) -> str:
    return (
        f"{team}: campeao={team_row['winner_pct']:.2f}%, final={team_row['final_pct']:.2f}%, "
        f"quartas={team_row.get('quarterfinal_pct', 0):.2f}%, semi={team_row['semifinal_pct']:.2f}%, "
        f"final={team_row['final_pct']:.2f}%, campeao={team_row['winner_pct']:.2f}%, "
        f"mata_mata={team_row['round32_pct']:.2f}%, adversario_mata_mata={team_row.get('most_common_round32_opponent', '')}"
    )


def _workflow_recommendation(steps: list[dict], metrics: dict) -> str:
    if any(step["status"] == "error" for step in steps):
        return "nao recomendado confiar: houve erro no workflow"
    dry = metrics.get("dry_run", {})
    update = metrics.get("update", {})
    conflicts = max(dry.get("conflicts", 0) or 0, update.get("conflicts", 0) or 0)
    changed_real = max(dry.get("changed_real", 0) or 0, update.get("changed_real", 0) or 0)
    warnings = max(dry.get("warnings", 0) or 0, update.get("warnings", 0) or 0)
    if conflicts:
        return "dados com alerta: ha conflitos de fontes"
    if warnings and not changed_real:
        return "dados confiaveis com alerta leve: ha placar live/nao-final ignorado com seguranca"
    if warnings:
        return "dados com alerta: revisar warnings do multi-source"
    return "dados confiaveis"


def _workflow_status(steps: list[dict], metrics: dict) -> str:
    if any(step.get("status") == "error" for step in steps):
        return "ERRO"
    dry = metrics.get("dry_run", {}) or {}
    update = metrics.get("update", {}) or {}
    conflicts = max(dry.get("conflicts", 0) or 0, update.get("conflicts", 0) or 0)
    warnings = max(dry.get("warnings", 0) or 0, update.get("warnings", 0) or 0)
    live_score = max(dry.get("non_final_score_detected", 0) or 0, update.get("non_final_score_detected", 0) or 0)
    if conflicts or warnings or live_score or any(step.get("status") == "warning" for step in steps):
        return "ATENCAO"
    return "OK"


def _best_backtest_model(metrics: dict) -> str:
    backtest = metrics.get("backtest", {}) or {}
    candidates = [
        ("modelo atual", backtest.get("brier"), backtest.get("log_loss")),
        ("baseline rating", backtest.get("rating_brier"), backtest.get("rating_log_loss")),
        ("baseline uniforme", backtest.get("uniform_brier"), backtest.get("uniform_log_loss")),
    ]
    candidates = [item for item in candidates if item[1] is not None]
    if not candidates:
        return "n/d"
    name, brier, log_loss = min(candidates, key=lambda item: item[1])
    return f"{name} (Brier {_fmt_metric(brier)}, Log Loss {_fmt_metric(log_loss)})"


def _model_probabilities_line(label: str, data: dict | None) -> str:
    data = data or {}
    if not data:
        return f"- {label}: n/d"
    return (
        f"- {label}: mata-mata {_pct(data.get('round32_pct'))}, oitavas {_pct(data.get('round16_pct'))}, "
        f"quartas {_pct(data.get('quarterfinal_pct'))}, semi {_pct(data.get('semifinal_pct'))}, "
        f"final {_pct(data.get('final_pct'))}, campeao {_pct(data.get('winner_pct'))}"
    )


def _main_round32_opponent(metrics: dict) -> str:
    balanced = metrics.get("balanced", {}) or {}
    tuned = metrics.get("tuned", {}) or {}
    opponent = balanced.get("most_common_round32_opponent") or tuned.get("most_common_round32_opponent")
    if not opponent:
        return "n/d"
    return str(opponent)


def _format_top_items(items: list[dict], limit: int = 5) -> str:
    if not items:
        return "n/d"
    parts = []
    for item in items[:limit]:
        name = item.get("name") or item.get("match") or "n/d"
        pct = item.get("pct")
        if pct is None:
            parts.append(str(name))
        else:
            parts.append(f"{name} ({_pct(pct)})")
    return "; ".join(parts)


def _path_risks(metrics: dict) -> list[str]:
    risks: list[str] = []
    balanced_path = metrics.get("balanced_path", {}) or {}
    tuned_path = metrics.get("tuned_path", {}) or {}
    opponents = balanced_path.get("round32_opponents") or tuned_path.get("round32_opponents") or []
    elimination = balanced_path.get("elimination_stages") or tuned_path.get("elimination_stages") or []
    if opponents:
        risks.append(f"Adversarios mais provaveis na primeira fase do mata-mata: {_format_top_items(opponents, 5)}")
    if elimination:
        risks.append(f"Estagios de eliminacao mais frequentes: {_format_top_items(elimination, 5)}")
    balanced = metrics.get("balanced", {}) or {}
    tuned = metrics.get("tuned", {}) or {}
    if balanced.get("quarterfinal_pct") is not None and balanced.get("semifinal_pct") is not None:
        drop = float(balanced.get("quarterfinal_pct") or 0) - float(balanced.get("semifinal_pct") or 0)
        risks.append(f"Maior funil estimado: quartas -> semi no {_scenario_label('balanced')}, queda de {_pct(drop)}")
    if tuned.get("quarterfinal_pct") is not None and tuned.get("semifinal_pct") is not None:
        drop = float(tuned.get("quarterfinal_pct") or 0) - float(tuned.get("semifinal_pct") or 0)
        risks.append(f"Maior funil estimado: quartas -> semi no {_scenario_label('tuned')}, queda de {_pct(drop)}")
    if not risks:
        risks.append("n/d")
    return risks



def _global_report_outputs() -> list[str]:
    return [
        "output/latest_global_report.txt",
        "output/global_title_ranking.csv",
        "output/global_stage_probabilities.csv",
        "output/global_group_outlook.csv",
        "output/global_group_leadership_outlook.csv",
        "output/global_group_qualification_outlook.csv",
        "output/global_model_sensitivity.csv",
        "output/global_risk_report.txt",
    ]


def _top_rows(result: dict | None, key: str, limit: int = 10) -> list[dict]:
    rows = (result or {}).get("rows", []) or []
    sorted_rows = sorted(rows, key=lambda row: float(row.get(key) or 0), reverse=True)[:limit]
    return [
        {
            "team": row.get("team"),
            "group": row.get("group"),
            "pct": row.get(key),
            "winner_pct": row.get("winner_pct"),
            "final_pct": row.get("final_pct"),
            "semifinal_pct": row.get("semifinal_pct"),
            "quarterfinal_pct": row.get("quarterfinal_pct"),
            "round16_pct": row.get("round16_pct"),
            "round32_pct": row.get("round32_pct"),
        }
        for row in sorted_rows
    ]


def _global_title_metrics(result: dict | None, model: str, limit: int = 15) -> list[dict]:
    rows = (result or {}).get("rows", []) or []
    top = sorted(rows, key=lambda row: float(row.get("winner_pct") or 0), reverse=True)[:limit]
    return [
        {
            "rank": idx,
            "model": model,
            "team": row.get("team"),
            "group": row.get("group"),
            "winner_pct": row.get("winner_pct"),
            "final_pct": row.get("final_pct"),
            "semifinal_pct": row.get("semifinal_pct"),
            "quarterfinal_pct": row.get("quarterfinal_pct"),
            "round16_pct": row.get("round16_pct"),
            "round32_pct": row.get("round32_pct"),
            "most_common_round32_opponent": row.get("most_common_round32_opponent"),
            "most_common_elimination_stage": row.get("most_common_elimination_stage"),
        }
        for idx, row in enumerate(top, 1)
    ]


def _stage_probability_rows(result: dict | None, model: str) -> list[dict]:
    rows = (result or {}).get("rows", []) or []
    return [
        {
            "model": model,
            "team": row.get("team"),
            "group": row.get("group"),
            "group_winner_pct": row.get("group_winner_pct"),
            "group_runner_up_pct": row.get("group_runner_up_pct"),
            "best_third_pct": row.get("best_third_pct"),
            "group_eliminated_pct": row.get("group_eliminated_pct"),
            "round32_pct": row.get("round32_pct"),
            "round16_pct": row.get("round16_pct"),
            "quarterfinal_pct": row.get("quarterfinal_pct"),
            "semifinal_pct": row.get("semifinal_pct"),
            "final_pct": row.get("final_pct"),
            "winner_pct": row.get("winner_pct"),
            "most_common_round32_opponent": row.get("most_common_round32_opponent"),
            "most_common_elimination_stage": row.get("most_common_elimination_stage"),
        }
        for row in rows
    ]


def _group_outlook_rows(result: dict | None, model: str) -> list[dict]:
    rows = (result or {}).get("rows", []) or []
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row.get("group")), []).append(row)
    outlook: list[dict] = []
    for group, group_rows in sorted(groups.items()):
        by_winner = sorted(group_rows, key=lambda row: float(row.get("group_winner_pct") or 0), reverse=True)
        by_qualification = sorted(group_rows, key=lambda row: float(row.get("round32_pct") or 0), reverse=True)
        winner_gap = 0.0
        qualification_gap = 0.0
        if len(by_winner) >= 2:
            winner_gap = float(by_winner[0].get("group_winner_pct") or 0) - float(by_winner[1].get("group_winner_pct") or 0)
        if len(by_qualification) >= 3:
            qualification_gap = float(by_qualification[1].get("round32_pct") or 0) - float(by_qualification[2].get("round32_pct") or 0)
        uncertainty_score = max(0.0, 100.0 - winner_gap) * 0.4 + max(0.0, 100.0 - qualification_gap) * 0.6
        outlook.append({
            "model": model,
            "group": group,
            "favorite_to_win_group": by_winner[0].get("team") if by_winner else "",
            "favorite_group_winner_pct": by_winner[0].get("group_winner_pct") if by_winner else None,
            "winner_gap_pct": winner_gap,
            "qualification_gap_2v3_pct": qualification_gap,
            "uncertainty_score": uncertainty_score,
            "teams_by_round32_pct": "; ".join(f"{row.get('team')} ({_pct(row.get('round32_pct'))})" for row in by_qualification),
        })
    return sorted(outlook, key=lambda row: float(row.get("uncertainty_score") or 0), reverse=True)


def _group_leadership_outlook_rows(result: dict | None, model: str) -> list[dict]:
    groups = _rows_by_group(result)
    out: list[dict] = []
    for group, group_rows in sorted(groups.items()):
        ranked = sorted(group_rows, key=lambda row: float(row.get("group_winner_pct") or 0), reverse=True)
        if not ranked:
            continue
        first = ranked[0]
        second = ranked[1] if len(ranked) > 1 else {}
        gap = float(first.get("group_winner_pct") or 0) - float(second.get("group_winner_pct") or 0)
        out.append({
            "model": model,
            "group": group,
            "favorite_to_win_group": first.get("team"),
            "favorite_group_winner_pct": first.get("group_winner_pct"),
            "second_group_winner_candidate": second.get("team", ""),
            "second_group_winner_pct": second.get("group_winner_pct"),
            "leadership_gap_pct": gap,
            "leadership_uncertainty_score": max(0.0, 100.0 - gap),
            "teams_by_group_winner_pct": "; ".join(f"{row.get('team')} ({_pct(row.get('group_winner_pct'))})" for row in ranked),
        })
    return sorted(out, key=lambda row: float(row.get("leadership_gap_pct") or 0))


def _group_qualification_outlook_rows(result: dict | None, model: str) -> list[dict]:
    groups = _rows_by_group(result)
    out: list[dict] = []
    for group, group_rows in sorted(groups.items()):
        ranked = sorted(group_rows, key=lambda row: float(row.get("round32_pct") or 0), reverse=True)
        if len(ranked) < 3:
            continue
        second, third = ranked[1], ranked[2]
        gap = float(second.get("round32_pct") or 0) - float(third.get("round32_pct") or 0)
        out.append({
            "model": model,
            "group": group,
            "second_round32_candidate": second.get("team"),
            "second_round32_pct": second.get("round32_pct"),
            "third_round32_candidate": third.get("team"),
            "third_round32_pct": third.get("round32_pct"),
            "qualification_gap_2v3_pct": gap,
            "qualification_uncertainty_score": max(0.0, 100.0 - gap),
            "teams_by_round32_pct": "; ".join(f"{row.get('team')} ({_pct(row.get('round32_pct'))})" for row in ranked),
        })
    return sorted(out, key=lambda row: float(row.get("qualification_gap_2v3_pct") or 0))


def _model_sensitivity_rows(balanced_result: dict | None, tuned_result: dict | None) -> list[dict]:
    if not balanced_result or not tuned_result:
        return []
    tuned_by_team = {row.get("team"): row for row in tuned_result.get("rows", []) or []}
    rows = []
    for base in balanced_result.get("rows", []) or []:
        team = base.get("team")
        tuned = tuned_by_team.get(team)
        if not tuned:
            continue
        delta_winner = float(tuned.get("winner_pct") or 0) - float(base.get("winner_pct") or 0)
        rows.append({
            "team": team,
            "group": base.get("group"),
            "balanced_winner_pct": base.get("winner_pct"),
            "tuned_winner_pct": tuned.get("winner_pct"),
            "delta_winner_pct": delta_winner,
            "delta_final_pct": float(tuned.get("final_pct") or 0) - float(base.get("final_pct") or 0),
            "delta_semifinal_pct": float(tuned.get("semifinal_pct") or 0) - float(base.get("semifinal_pct") or 0),
            "delta_round32_pct": float(tuned.get("round32_pct") or 0) - float(base.get("round32_pct") or 0),
            "delta_group_eliminated_pct": float(tuned.get("group_eliminated_pct") or 0) - float(base.get("group_eliminated_pct") or 0),
            "abs_delta_winner_pct": abs(delta_winner),
        })
    return sorted(rows, key=lambda row: float(row["abs_delta_winner_pct"]), reverse=True)


def _rows_by_group(result: dict | None) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in (result or {}).get("rows", []) or []:
        groups.setdefault(str(row.get("group")), []).append(row)
    return groups


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _format_ranking(title: str, items: list[dict], key: str = "pct", limit: int = 10) -> list[str]:
    lines = [title]
    if not items:
        lines.append("- n/d")
        return lines
    for idx, item in enumerate(items[:limit], 1):
        pct = item.get(key)
        if pct is None and key == "pct":
            pct = item.get("winner_pct")
        lines.append(f"{idx}. {item.get('team')} ({item.get('group')}) - {_pct(pct)}")
    return lines


def _global_risk_lines(global_metrics: dict) -> list[str]:
    risks: list[str] = []
    leadership = global_metrics.get("most_uncertain_leadership_groups_balanced") or []
    if leadership:
        risks.append("Liderancas mais indefinidas: " + "; ".join(
            f"Grupo {row.get('group')} (gap {_pct(row.get('leadership_gap_pct'))})"
            for row in leadership[:3]
        ))
    qualification = global_metrics.get("most_uncertain_qualification_groups_balanced") or []
    if qualification:
        risks.append("Classificacoes mais indefinidas: " + "; ".join(
            f"Grupo {row.get('group')} (2v3 {_pct(row.get('qualification_gap_2v3_pct'))})"
            for row in qualification[:3]
        ))
    top_title = global_metrics.get("top_title_balanced") or []
    if top_title:
        top5_sum = sum(float(item.get("pct") or item.get("winner_pct") or 0) for item in top_title[:5])
        risks.append(f"Concentracao dos 5 maiores favoritos ao titulo: {_pct(top5_sum)}")
    top_r32 = global_metrics.get("top_round32_risks_balanced") or []
    if top_r32:
        risks.append("Favoritos com maior risco antes do mata-mata: " + "; ".join(
            f"{item.get('team')} elim. grupo {_pct(item.get('group_eliminated_pct'))}"
            for item in top_r32[:5]
        ))
    if not risks:
        risks.append("Sem riscos globais destacados nos dados atuais.")
    return risks


def _format_sensitivity_lines(items: list[dict], limit: int = 3) -> list[str]:
    if not items:
        return ["- n/d"]
    lines = []
    for idx, row in enumerate(items[:limit], 1):
        lines.append(
            f"{idx}. {row.get('team')} ({row.get('group')}) - título {_pct(row.get('delta_winner_pct'))}, "
            f"final {_pct(row.get('delta_final_pct'))}, semi {_pct(row.get('delta_semifinal_pct'))}, "
            f"mata-mata {_pct(row.get('delta_round32_pct'))}, elim. grupo {_pct(row.get('delta_group_eliminated_pct'))}"
        )
    return lines


def _sensitivity_short(row: dict) -> str:
    return f"{row.get('team')} ({_pct(row.get('delta_winner_pct'))} título)"


def _write_global_report(balanced_result: dict | None, tuned_result: dict | None, metrics: dict) -> tuple[list[str], dict]:
    if not balanced_result:
        raise ValueError("resultado balanced indisponivel para panorama geral")
    out = Path("output")
    out.mkdir(exist_ok=True)
    outputs = _global_report_outputs()
    title_path = out / "global_title_ranking.csv"
    stage_path = out / "global_stage_probabilities.csv"
    group_path = out / "global_group_outlook.csv"
    leadership_path = out / "global_group_leadership_outlook.csv"
    qualification_path = out / "global_group_qualification_outlook.csv"
    sensitivity_path = out / "global_model_sensitivity.csv"
    risk_path = out / "global_risk_report.txt"
    latest_path = out / "latest_global_report.txt"

    title_rows = _global_title_metrics(balanced_result, "balanced", 20)
    if tuned_result:
        title_rows += _global_title_metrics(tuned_result, "tuned", 20)
    _write_csv(title_path, title_rows, [
        "rank", "model", "team", "group", "winner_pct", "final_pct", "semifinal_pct",
        "quarterfinal_pct", "round16_pct", "round32_pct", "most_common_round32_opponent", "most_common_elimination_stage",
    ])

    stage_rows = _stage_probability_rows(balanced_result, "balanced")
    if tuned_result:
        stage_rows += _stage_probability_rows(tuned_result, "tuned")
    _write_csv(stage_path, stage_rows, [
        "model", "team", "group", "group_winner_pct", "group_runner_up_pct", "best_third_pct",
        "group_eliminated_pct", "round32_pct", "round16_pct", "quarterfinal_pct", "semifinal_pct",
        "final_pct", "winner_pct", "most_common_round32_opponent", "most_common_elimination_stage",
    ])

    group_rows = _group_outlook_rows(balanced_result, "balanced")
    if tuned_result:
        group_rows += _group_outlook_rows(tuned_result, "tuned")
    _write_csv(group_path, group_rows, [
        "model", "group", "favorite_to_win_group", "favorite_group_winner_pct", "winner_gap_pct",
        "qualification_gap_2v3_pct", "uncertainty_score", "teams_by_round32_pct",
    ])

    leadership_rows = _group_leadership_outlook_rows(balanced_result, "balanced")
    if tuned_result:
        leadership_rows += _group_leadership_outlook_rows(tuned_result, "tuned")
    _write_csv(leadership_path, leadership_rows, [
        "model", "group", "favorite_to_win_group", "favorite_group_winner_pct",
        "second_group_winner_candidate", "second_group_winner_pct", "leadership_gap_pct",
        "leadership_uncertainty_score", "teams_by_group_winner_pct",
    ])

    qualification_rows = _group_qualification_outlook_rows(balanced_result, "balanced")
    if tuned_result:
        qualification_rows += _group_qualification_outlook_rows(tuned_result, "tuned")
    _write_csv(qualification_path, qualification_rows, [
        "model", "group", "second_round32_candidate", "second_round32_pct",
        "third_round32_candidate", "third_round32_pct", "qualification_gap_2v3_pct",
        "qualification_uncertainty_score", "teams_by_round32_pct",
    ])

    sensitivity_rows = _model_sensitivity_rows(balanced_result, tuned_result)
    _write_csv(sensitivity_path, sensitivity_rows, [
        "team", "group", "balanced_winner_pct", "tuned_winner_pct", "delta_winner_pct",
        "delta_final_pct", "delta_semifinal_pct", "delta_round32_pct",
        "delta_group_eliminated_pct", "abs_delta_winner_pct",
    ])

    balanced_rows = balanced_result.get("rows", []) or []
    top_round32_risks = sorted(
        [row for row in balanced_rows if float(row.get("winner_pct") or 0) >= 1.0],
        key=lambda row: float(row.get("group_eliminated_pct") or 0),
        reverse=True,
    )[:10]
    global_metrics = {
        "top_title_balanced": _top_rows(balanced_result, "winner_pct", 10),
        "top_title_tuned": _top_rows(tuned_result, "winner_pct", 10) if tuned_result else [],
        "top_final_balanced": _top_rows(balanced_result, "final_pct", 10),
        "top_semifinal_balanced": _top_rows(balanced_result, "semifinal_pct", 10),
        "top_quarterfinal_balanced": _top_rows(balanced_result, "quarterfinal_pct", 10),
        "top_round16_balanced": _top_rows(balanced_result, "round16_pct", 10),
        "top_round32_balanced": _top_rows(balanced_result, "round32_pct", 10),
        "most_uncertain_groups_balanced": _group_outlook_rows(balanced_result, "balanced")[:5],
        "most_uncertain_leadership_groups_balanced": _group_leadership_outlook_rows(balanced_result, "balanced")[:5],
        "most_uncertain_qualification_groups_balanced": _group_qualification_outlook_rows(balanced_result, "balanced")[:5],
        "model_sensitivity_top_gains": sorted(sensitivity_rows, key=lambda row: float(row.get("delta_winner_pct") or 0), reverse=True)[:5],
        "model_sensitivity_top_drops": sorted(sensitivity_rows, key=lambda row: float(row.get("delta_winner_pct") or 0))[:5],
        "model_sensitivity_abs": sensitivity_rows[:5],
        "top_round32_risks_balanced": [
            {"team": row.get("team"), "group": row.get("group"), "winner_pct": row.get("winner_pct"), "group_eliminated_pct": row.get("group_eliminated_pct")}
            for row in top_round32_risks
        ],
        "files": outputs,
    }

    risk_lines = ["Relatorio de riscos globais", ""] + [f"- {line}" for line in _global_risk_lines(global_metrics)]
    risk_path.write_text("\n".join(risk_lines) + "\n", encoding="utf-8")

    lines = [
        "Panorama geral da Copa 2026",
        f"Simulacoes: {metrics.get('simulations')}",
        f"Seed: {metrics.get('seed')}",
        "",
        "Cenários do relatório:",
        "Cenário Base: projeção principal do simulador.",
        "Cenário Calibrado: projeção ajustada com base no desempenho do modelo no backtest.",
        "",
    ]
    lines += _format_ranking("Top favoritos ao titulo - Cenário Base", global_metrics["top_title_balanced"], limit=10)
    if global_metrics["top_title_tuned"]:
        lines += [""] + _format_ranking("Top favoritos ao titulo - Cenário Calibrado", global_metrics["top_title_tuned"], limit=10)
    lines += [""] + _format_ranking("Top chances de classificação ao mata-mata - Cenário Base", global_metrics["top_round32_balanced"], limit=10)
    lines += [""] + _format_ranking("Top chances de chegar às oitavas - Cenário Base", global_metrics["top_round16_balanced"], limit=10)
    lines += [""] + _format_ranking("Top chances de chegar às quartas - Cenário Base", global_metrics["top_quarterfinal_balanced"], limit=10)
    lines += [""] + _format_ranking("Top chances de semifinal - Cenário Base", global_metrics["top_semifinal_balanced"], limit=10)
    lines += [""] + _format_ranking("Top chances de final - Cenário Base", global_metrics["top_final_balanced"], limit=10)
    lines += ["", "Grupos mais indefinidos para liderança - Cenário Base"]
    for idx, row in enumerate(global_metrics["most_uncertain_leadership_groups_balanced"][:5], 1):
        second = row.get("second_group_winner_candidate")
        lines.append(
            f"{idx}. Grupo {row['group']} - {row['favorite_to_win_group']} {_pct(row['favorite_group_winner_pct'])}, "
            f"{second} {_pct(row.get('second_group_winner_pct'))}, gap liderança {_pct(row['leadership_gap_pct'])}"
        )
    lines += ["", "Grupos mais indefinidos para classificação - Cenário Base"]
    for idx, row in enumerate(global_metrics["most_uncertain_qualification_groups_balanced"][:5], 1):
        lines.append(
            f"{idx}. Grupo {row['group']} - {row['second_round32_candidate']} {_pct(row['second_round32_pct'])}, "
            f"{row['third_round32_candidate']} {_pct(row['third_round32_pct'])}, gap classificação {_pct(row['qualification_gap_2v3_pct'])}"
        )
    lines += ["", "Seleções mais sensíveis à calibração"]
    lines += ["Maiores altas no Cenário Calibrado vs Cenário Base:"]
    lines += _format_sensitivity_lines(global_metrics["model_sensitivity_top_gains"])
    lines += ["Maiores quedas no Cenário Calibrado vs Cenário Base:"]
    lines += _format_sensitivity_lines(global_metrics["model_sensitivity_top_drops"])
    lines += ["Maiores variações absolutas:"]
    lines += _format_sensitivity_lines(global_metrics["model_sensitivity_abs"])
    lines += ["", "Maiores riscos globais:"]
    lines += [f"- {line}" for line in _global_risk_lines(global_metrics)]
    lines += ["", "Arquivos gerados:"]
    lines += [f"- {path}" for path in outputs]
    latest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return outputs, global_metrics

def _executive_summary_lines(steps: list[dict], metrics: dict, outputs: list[str], recommendation: str) -> list[str]:
    status = _workflow_status(steps, metrics)
    team = metrics.get("team") or "n/d"
    lines = [
        "Secao executiva",
        f"Status geral: {status}",
        f"Melhor modelo pelo backtest: {_best_backtest_model(metrics)}",
        "Cenário Base: projeção principal do simulador.",
        "Cenário Calibrado: projeção ajustada com base no desempenho do modelo no backtest.",
    ]
    global_report = metrics.get("global_report") or {}
    if global_report:
        lines += [
            "",
            "Secao executiva global",
            "Top favoritos ao titulo - Cenário Base:",
        ]
        for idx, item in enumerate((global_report.get("top_title_balanced") or [])[:10], 1):
            lines.append(f"{idx}. {item.get('team')} ({item.get('group')}) - {_pct(item.get('pct'))}")
        if global_report.get("top_title_tuned"):
            lines.append("Top favoritos ao titulo - Cenário Calibrado:")
            for idx, item in enumerate((global_report.get("top_title_tuned") or [])[:10], 1):
                lines.append(f"{idx}. {item.get('team')} ({item.get('group')}) - {_pct(item.get('pct'))}")
        if global_report.get("top_round32_balanced"):
            lines.append("Top chances de classificação ao mata-mata - Cenário Base:")
            for idx, item in enumerate((global_report.get("top_round32_balanced") or [])[:5], 1):
                lines.append(f"{idx}. {item.get('team')} ({item.get('group')}) - {_pct(item.get('pct'))}")
        if global_report.get("top_round16_balanced"):
            lines.append("Top chances de chegar às oitavas - Cenário Base:")
            for idx, item in enumerate((global_report.get("top_round16_balanced") or [])[:5], 1):
                lines.append(f"{idx}. {item.get('team')} ({item.get('group')}) - {_pct(item.get('pct'))}")
        if global_report.get("top_quarterfinal_balanced"):
            lines.append("Top chances de chegar às quartas - Cenário Base:")
            for idx, item in enumerate((global_report.get("top_quarterfinal_balanced") or [])[:5], 1):
                lines.append(f"{idx}. {item.get('team')} ({item.get('group')}) - {_pct(item.get('pct'))}")
        lines.append("Grupos mais indefinidos para liderança:")
        for row in (global_report.get("most_uncertain_leadership_groups_balanced") or [])[:5]:
            lines.append(
                f"- Grupo {row.get('group')}: {row.get('favorite_to_win_group')} {_pct(row.get('favorite_group_winner_pct'))}, "
                f"{row.get('second_group_winner_candidate')} {_pct(row.get('second_group_winner_pct'))}, "
                f"gap liderança {_pct(row.get('leadership_gap_pct'))}"
            )
        lines.append("Grupos mais indefinidos para classificação:")
        for row in (global_report.get("most_uncertain_qualification_groups_balanced") or [])[:5]:
            lines.append(
                f"- Grupo {row.get('group')}: {row.get('second_round32_candidate')} {_pct(row.get('second_round32_pct'))}, "
                f"{row.get('third_round32_candidate')} {_pct(row.get('third_round32_pct'))}, "
                f"gap classificação {_pct(row.get('qualification_gap_2v3_pct'))}"
            )
        lines.append("Seleções mais sensíveis à calibração:")
        gains = global_report.get("model_sensitivity_top_gains") or []
        drops = global_report.get("model_sensitivity_top_drops") or []
        abs_items = global_report.get("model_sensitivity_abs") or []
        lines.append(f"- Maior alta no Cenário Calibrado: {_sensitivity_short(gains[0]) if gains else 'n/d'}")
        lines.append(f"- Maior queda no Cenário Calibrado: {_sensitivity_short(drops[0]) if drops else 'n/d'}")
        lines.append(f"- Maior variação absoluta: {_sensitivity_short(abs_items[0]) if abs_items else 'n/d'}")
        lines.append("Maiores riscos globais:")
        for risk in _global_risk_lines(global_report):
            lines.append(f"- {risk}")
    lines += [
        "",
        "Secao executiva do time",
        f"Time analisado: {team}",
        "Probabilidades principais:",
        _model_probabilities_line("Cenário Base", metrics.get("balanced")),
        _model_probabilities_line("Cenário Calibrado", metrics.get("tuned")),
        f"Adversario provavel na primeira fase do mata-mata: {_main_round32_opponent(metrics)}",
        "Maiores riscos do caminho:",
    ]
    for risk in _path_risks(metrics):
        lines.append(f"- {risk}")
    unique_outputs = sorted(set(outputs))
    lines.append("Arquivos gerados:")
    if unique_outputs:
        for output in unique_outputs:
            lines.append(f"- {output}")
    else:
        lines.append("- nenhum arquivo registrado")
    lines.append(f"Recomendacao executiva: {recommendation}")
    return lines


def _write_workflow_report(workflow: str, steps: list[dict], metrics: dict, outputs: list[str]) -> dict:
    out = Path("output/workflows")
    out.mkdir(parents=True, exist_ok=True)
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    report_path = out / f"{stamp}_{workflow}_report.txt"
    latest_path = out / f"latest_{workflow}_report.txt"
    latest_generic = out / "latest_report.txt"
    recommendation = _workflow_recommendation(steps, metrics)
    lines = [
        f"Workflow: {workflow}",
        f"Team: {metrics.get('team')}",
        f"Simulacoes: {metrics.get('simulations')}",
        f"Seed: {metrics.get('seed')}",
        "",
    ]
    report_outputs = outputs + [str(report_path), str(latest_path), str(latest_generic)]
    lines.extend(_executive_summary_lines(steps, metrics, report_outputs, recommendation))
    lines += ["", "Etapas:"]
    for step in steps:
        lines.append(f"[{step['status']}] {step['name']} - {step['message']}")
        for output in step.get("outputs", []):
            lines.append(f"  output: {output}")
    lines += ["", "Metricas principais:"]
    for key in ("dry_run", "update", "backtest", "tuning", "balanced", "tuned", "global_report"):
        if key in metrics:
            lines.append(f"{key}: {json.dumps(metrics[key], ensure_ascii=False)}")
    lines += ["", f"Recomendacao final: {recommendation}"]
    text = "\n".join(lines) + "\n"
    report_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    latest_generic.write_text(text, encoding="utf-8")
    report_json = {
        "workflow": workflow,
        "status": _workflow_status(steps, metrics),
        "best_backtest_model": _best_backtest_model(metrics),
        "steps": steps,
        "metrics": metrics,
        "outputs": sorted(set(outputs + [str(report_path), str(latest_path), str(latest_generic)])),
        "recommendation": recommendation,
        "report": str(report_path),
        "latest_report": str(latest_path),
    }
    (out / f"{stamp}_{workflow}_report.json").write_text(json.dumps(report_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / f"latest_{workflow}_report.json").write_text(json.dumps(report_json, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report_json

