from __future__ import annotations

import csv
import json
from pathlib import Path

FIELDS = [
    "team","group","group_winner_pct","group_runner_up_pct","best_third_pct","group_eliminated_pct",
    "round32_pct","round16_pct","quarterfinal_pct","semifinal_pct","final_pct","winner_pct",
    "winner_ci_low","winner_ci_high","final_ci_low","final_ci_high","semifinal_ci_low","semifinal_ci_high",
    "most_common_round32_match","most_common_round32_opponent","most_common_elimination_stage",
]


def fmt_pct(v: float) -> str:
    return f"{v:.2f}%"


def write_reports(result: dict, output_dir: str | Path = "output", team: str = "Brazil") -> list[Path]:
    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    rows = result["rows"]
    csv_path = out / "probabilities.csv"
    json_path = out / "probabilities.json"
    summary_path = out / "summary.txt"
    team_paths_path = out / f"team_paths_{team}.json"
    explanation_path = out / "model_explanation.txt"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    with json_path.open("w", encoding="utf-8") as f:
        json.dump({"meta": {k: result[k] for k in ("simulations", "seed", "third_mapping_approximate_pct")}, "teams": rows}, f, indent=2)
    summary = build_summary(result, team)
    summary_path.write_text(summary, encoding="utf-8")
    explanation_path.write_text(build_model_explanation(result, team), encoding="utf-8")
    team_paths = result.get("team_paths", {}).get(team, {})
    with team_paths_path.open("w", encoding="utf-8") as f:
        json.dump({"team": team, "simulations": result["simulations"], **team_paths}, f, indent=2)
    return [csv_path, json_path, summary_path, team_paths_path, explanation_path]


def build_summary(result: dict, team: str = "Brazil") -> str:
    rows = result["rows"]
    by_team = {r["team"]: r for r in rows}
    lines = [
        "Simulador Copa do Mundo FIFA 2026",
        f"Simulacoes: {result['simulations']:,}".replace(",", "."),
        "Modelo: Monte Carlo",
        "Chaveamento: Oficial FIFA",
        f"Seed: {result['seed']}",
        "",
        "Top 10 favoritos ao titulo:",
    ]
    for i, r in enumerate(rows[:10], 1):
        lines.append(f"{i}. {r['team']} - {fmt_pct(r['winner_pct'])}")
    lines += ["", "Top 10 chances de final:"]
    for i, r in enumerate(sorted(rows, key=lambda x: x["final_pct"], reverse=True)[:10], 1):
        lines.append(f"{i}. {r['team']} - {fmt_pct(r['final_pct'])}")
    lines += ["", "Top 10 chances de semifinal:"]
    for i, r in enumerate(sorted(rows, key=lambda x: x["semifinal_pct"], reverse=True)[:10], 1):
        lines.append(f"{i}. {r['team']} - {fmt_pct(r['semifinal_pct'])}")
    if team in by_team:
        r = by_team[team]
        lines += [
            "", f"{team}:",
            f"Classificar ao Round of 32: {fmt_pct(r['round32_pct'])}",
            f"Terminar em 1o do grupo: {fmt_pct(r['group_winner_pct'])}",
            f"Terminar em 2o do grupo: {fmt_pct(r['group_runner_up_pct'])}",
            f"Classificar como melhor terceiro: {fmt_pct(r['best_third_pct'])}",
            f"Eliminacao na fase de grupos: {fmt_pct(r['group_eliminated_pct'])}",
            f"Chegar as oitavas: {fmt_pct(r['round16_pct'])}",
            f"Chegar as quartas: {fmt_pct(r['quarterfinal_pct'])}",
            f"Chegar a semifinal: {fmt_pct(r['semifinal_pct'])}",
            f"Chegar a final: {fmt_pct(r['final_pct'])}",
            f"Ser campeao: {fmt_pct(r['winner_pct'])} [IC 95%: {fmt_pct(r['winner_ci_low'])} - {fmt_pct(r['winner_ci_high'])}]",
            "Caminho mais comum no Round of 32:",
            f"Match {r['most_common_round32_match']} - {team} x {r['most_common_round32_opponent']}",
        ]
        opponents = result.get("team_paths", {}).get(team, {}).get("round32_opponents", [])[:5]
        if opponents:
            lines.append("Adversarios mais comuns no Round of 32:")
            for item in opponents:
                lines.append(f"- {item['name']}: {fmt_pct(item['pct'])}")
    if result["third_mapping_approximate_pct"] > 0:
        lines += [
            "",
            "Atencao: tabela oficial de terceiros incompleta. Parte do mata-mata usou fallback aproximado.",
            f"Uso de fallback: {fmt_pct(result['third_mapping_approximate_pct'])}",
        ]
    return "\n".join(lines) + "\n"


def build_model_explanation(result: dict, team: str = "Brazil") -> str:
    config = result.get("model_config", {})
    knockout = config.get("knockout", {})
    rating = result.get("rating_breakdown", {}).get(team, {})
    lines = [
        "Explicacao do Modelo",
        f"Preset: {result.get('model_preset')}",
        f"Weights file: {result.get('weights_file')}",
        f"Rating source: {result.get('rating_source', 'base')}",
        f"Simulacoes: {result.get('simulations')}",
        f"Knockout sensitivity: {knockout.get('sensitivity')}",
        f"Upset floor: {knockout.get('upset_floor')}",
        f"Favorite ceiling: {knockout.get('favorite_ceiling')}",
    ]
    if rating:
        lines += [
            "",
            f"{team}:",
            f"Rating base: {rating['base_rating']}",
            f"Rating calibrado: {rating['final_rating']}",
            f"Delta total: {rating['delta_total']:+}",
            f"Explicacao: {rating['explanation']}",
        ]
    if result.get("weight_warnings"):
        lines += ["", "Avisos de pesos:"]
        lines += [f"- {warning}" for warning in result["weight_warnings"]]
    lines += [
        "",
        "Limitacoes:",
        "- Ratings e pesos sao aproximados.",
        "- Odds e rankings externos so entram quando os arquivos normalizados estiverem preenchidos.",
        "- Intervalos de confianca cobrem apenas erro Monte Carlo, nao erro estrutural do modelo.",
    ]
    return "\n".join(lines) + "\n"
