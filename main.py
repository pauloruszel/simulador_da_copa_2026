from __future__ import annotations

import csv
import json
from pathlib import Path

from src.calibration.backtesting import evaluate_finished_matches, tune_weights_grid, write_backtest_report
from src.reports import build_summary
from src.simulator import run
from src.update.data_updater import DataUpdater
from src.update.multi_source_results_updater import MultiSourceResultsUpdater
from src.calibration.team_strength import build_calibrated_ratings, load_model_weights, load_weights_file, save_calibrated_ratings
from src.calibration.tournament_form import recalibrate_ratings_from_results
from src.cli_args import parse_args
from src.data_provider import LocalJsonDataProvider, apply_scenario
from src.storage.json_store import JsonStore


def main() -> None:
    args = parse_args()
    if args.workflow:
        run_workflow(args)
        return
    update_requested = (
        args.update_data
        or args.update_data_only
        or args.update_results
        or args.update_odds
        or args.update_rankings
        or args.scrape_results
        or args.scrape_results_only
        or args.update_results_multisource
        or args.update_results_multisource_only
        or args.dry_run_multisource
        or args.source_health_check
        or bool(args.audit_group)
        or bool(args.audit_match)
        or args.recalibrate_ratings
        or args.analyze_weights
        or args.sensitivity_analysis
        or args.compare_presets
        or args.backtest
        or args.tune_weights
        or bool(args.compare_weight_files)
    )
    if args.source_health_check:
        result = MultiSourceResultsUpdater().health_check()
        print("[ok] source health check")
        for row in result["sources"]:
            print(f"  {row['source']}: {row['status']} ({row['matches']} partidas)")
        return
    if args.audit_group:
        result = MultiSourceResultsUpdater().audit_group(args.audit_group)
        print(f"[ok] audit group {result['group']}")
        for match in result["matches"]:
            score = "-"
            if match.get("home_score") is not None and match.get("away_score") is not None:
                score = f"{match['home_score']}-{match['away_score']}"
            source = ""
            for item in match.get("sources", []):
                if "score" in item.get("fields", []):
                    source = item.get("name", "")
                    break
            print(f"  {match.get('id')}: {match.get('home')} x {match.get('away')} | {match.get('status')} | {score} | {source}")
        print(f"  Relatorio: output/audit_group_{result['group']}.txt")
        return
    if args.audit_match:
        result = MultiSourceResultsUpdater().audit_match(args.audit_match)
        print(f"[ok] audit match {result['match_id']}")
        local = result.get("local") or {}
        if local:
            score = "-"
            if local.get("home_score") is not None and local.get("away_score") is not None:
                score = f"{local['home_score']}-{local['away_score']}"
            print(f"  Local: {local.get('home')} x {local.get('away')} | {local.get('status')} | {score} | {local.get('date', '')}")
        print(f"  Fontes correspondentes: {len(result.get('source_rows', []))}")
        print(f"  Relatorio: output/audit_match_{result['match_id']}.txt")
        return
    if args.update_results_multisource or args.update_results_multisource_only or args.dry_run_multisource:
        result = MultiSourceResultsUpdater().update(
            dry_run=args.dry_run_multisource,
            allow_future_results=args.allow_future_results,
        )
        print("[ok] multisource results")
        print(f"  Alteradas de fato: {result['changed_real']}")
        print(f"  Somente metadados: {result['metadata_only']}")
        print(f"  Sem mudanca: {result['unchanged']}")
        print(f"  Ignoradas: {result['skipped']}")
        print(f"  Conflitos: {len(result['conflicts'])}")
        print(f"  Warnings: {len(result.get('warnings', []))}")
        print("  Relatorio: output/multisource_update_report.txt")
        print("  Integridade dos grupos: output/group_integrity_report.txt")
        if args.update_results_multisource_only or args.dry_run_multisource:
            return
    if update_requested and not args.offline and not args.update_results_multisource:
        updater = DataUpdater()
        if args.scrape_results or args.scrape_results_only:
            updater.scrape_results(dry_run=args.dry_run_scrape)
        if args.update_data or args.update_data_only or args.update_results or args.update_odds or args.update_rankings:
            only_specific = args.update_results or args.update_odds or args.update_rankings
            updater.run(
                results=args.update_data or args.update_data_only or args.update_results or not only_specific,
                odds=args.update_data or args.update_data_only or args.update_odds or not only_specific,
                rankings=args.update_data or args.update_data_only or args.update_rankings or not only_specific,
            )
        for event in updater.log:
            print_update_event(event)
    if args.recalibrate_ratings:
        recalibrate_ratings(args.scenario)
        if not args.use_adjusted_ratings:
            return
    if args.analyze_weights:
        analyze_weights(args.model_preset, args.scenario, args.weights_file)
        return
    if args.backtest:
        run_backtest(args.model_preset)
        return
    if args.tune_weights:
        tune_weights(args.model_preset)
        return
    if args.compare_presets:
        compare_presets(args.team, args.simulations, args.seed)
        return
    if args.compare_weight_files:
        compare_weight_files(args.compare_weight_files, args.team, args.simulations, args.seed)
        return
    if args.sensitivity_analysis:
        sensitivity_analysis(args.team, args.simulations, args.seed)
        return
    if args.update_data_only or args.scrape_results_only:
        return
    if (args.update_results or args.update_odds or args.update_rankings) and not args.update_data:
        return
    rating_source = "adjusted" if args.use_adjusted_ratings else args.rating_source
    try:
        result = run(
            args.simulations,
            args.seed,
            args.scenario,
            args.team,
            args.use_adjusted_ratings,
            rating_source,
            args.model_preset,
            args.weights_file,
        )
    except ValueError as exc:
        raise SystemExit(f"Erro: {exc}") from exc
    print(build_summary(result, args.team))
    print("Arquivos gerados:")
    print("output/probabilities.csv")
    print("output/probabilities.json")
    print("output/summary.txt")
    print(f"output/team_paths_{args.team}.json")
    print("output/model_explanation.txt")
    if rating_source == "calibrated":
        print("output/rating_breakdown.csv")
        print("output/rating_breakdown.json")

def print_update_event(event: dict) -> None:
    print(f"[{event['status']}] {event['source']}:{event['category']}")
    print(f"  {event['message']}")
    details = event.get("details") or {}
    sample = details.get("sample") or []
    if sample:
        print("  Amostra:")
        for line in sample[:8]:
            print(f"  - {line}")


def recalibrate_ratings(scenario: str | None = None) -> None:
    provider = LocalJsonDataProvider()
    matches = apply_scenario(provider.load_matches(), scenario)
    result = recalibrate_ratings_from_results(provider.load_ratings(), matches)
    JsonStore().write("data/adjusted_ratings.json", result)
    print("[ok] tournament_form:ratings")
    print("  data/adjusted_ratings.json atualizado.")
    print("  Maiores altas:")
    for row in result["rows"][:8]:
        if row["delta"] <= 0:
            break
        print(f"  - {row['team']}: {row['base_rating']} -> {row['adjusted_rating']} ({row['delta']:+})")


def analyze_weights(model_preset: str | None = None, scenario: str | None = None, weights_file: str | None = None) -> None:
    provider = LocalJsonDataProvider()
    matches = apply_scenario(provider.load_matches(), scenario)
    weights, warnings = load_weights_file(weights_file, model_preset) if weights_file else (load_model_weights(model_preset), [])
    calibrated = build_calibrated_ratings(provider.load_ratings(), matches, weights)
    save_calibrated_ratings(calibrated)
    for warning in warnings:
        print(f"[warning] {warning}")
    print("Impacto dos pesos no rating final:")
    for row in sorted(calibrated["breakdown"].values(), key=lambda r: r["delta_total"], reverse=True)[:12]:
        print(
            f"{row['team']}: base {row['base_rating']} | forma {row['tournament_form_component']:+} | "
            f"adversarios {row['opponent_adjusted_component']:+} | casa {row['home_advantage_component']:+} | "
            f"final {row['final_rating']} ({row['delta_total']:+})"
        )


def run_backtest(model_preset: str | None = None) -> None:
    provider = LocalJsonDataProvider()
    weights = load_model_weights(model_preset)
    result = evaluate_finished_matches(provider.load_matches(), provider.load_ratings(), weights, calibrate_ratings=True)
    write_backtest_report(result)
    print("[ok] backtest")
    print(f"  Jogos avaliados: {result['matches_evaluated']}")
    if result["brier_mean"] is not None:
        print(f"  Modelo: Brier {result['brier_mean']:.3f}, Log Loss {result['log_loss_mean']:.3f}")
        for name, baseline in result["baselines"].items():
            print(f"  Baseline {name}: Brier {baseline['brier_mean']:.3f}, Log Loss {baseline['log_loss_mean']:.3f}")


def tune_weights(model_preset: str | None = None) -> None:
    provider = LocalJsonDataProvider()
    weights = load_model_weights(model_preset)
    result = tune_weights_grid(provider.load_matches(), provider.load_ratings(), weights)
    JsonStore().write("output/best_model_weights.json", result)
    print("[ok] tune_weights")
    print(f"  Combinacoes testadas: {result['tested']}")
    print(f"  Score original: {result['baseline']['brier_mean']:.3f}")
    print(f"  Melhor Brier Score: {result['best']['brier_mean']:.3f}")
    if result["improvement"] > 0:
        print(f"  Melhora: {result['improvement']:.3f}")
    else:
        print("  Nenhuma combinacao melhorou o score original.")
    print(
        "  Melhor config: "
        f"form_weight={result['best']['form_weight']}, "
        f"goal_difference_weight={result['best']['goal_difference_weight']}, "
        f"draw_correction_factor={result['best']['draw_correction_factor']}, "
        f"goal_advantage_scale={result['best']['goal_advantage_scale']}"
    )
    print("  Config salva em output/best_model_weights.json")


def compare_presets(team: str, simulations: int, seed: int | None) -> None:
    presets = JsonStore().read("data/model_presets.json", {})
    rows = []
    for preset in presets:
        result = run(simulations, seed, None, team, False, "calibrated", preset, write_output=False)
        row = next(r for r in result["rows"] if r["team"] == team)
        rows.append(_preset_row(preset, team, row, result))
    _write_preset_report(rows, team, "preset_comparison")
    print(f"[ok] preset comparison: output/preset_comparison_{team}.csv")


def sensitivity_analysis(team: str, simulations: int, seed: int | None) -> None:
    presets = ["conservative", "recent_form", "market_weighted", "high_upset", "favorite_heavy", "balanced"]
    rows = []
    for preset in presets:
        result = run(simulations, seed, None, team, False, "calibrated", preset, write_output=False)
        row = next(r for r in result["rows"] if r["team"] == team)
        rows.append(_preset_row(preset, team, row, result))
    _write_preset_report(rows, team, "sensitivity")
    print(f"[ok] sensitivity: output/sensitivity_{team}.csv")


def _preset_row(preset: str, team: str, row: dict, result: dict) -> dict:
    return {
        "model_variant": preset,
        f"{team.lower().replace(' ', '_')}_winner_pct": row["winner_pct"],
        f"{team.lower().replace(' ', '_')}_final_pct": row["final_pct"],
        f"{team.lower().replace(' ', '_')}_semifinal_pct": row["semifinal_pct"],
        f"{team.lower().replace(' ', '_')}_round32_opponent_most_common": row["most_common_round32_opponent"],
        "top_10": "; ".join(r["team"] for r in result["rows"][:10]),
    }


def _write_preset_report(rows: list[dict], team: str, prefix: str) -> None:
    out = Path("output")
    out.mkdir(exist_ok=True)
    csv_path = out / f"{prefix}_{team}.csv"
    txt_path = out / f"{prefix}_{team}.txt"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [f"{prefix} - {team}"]
    for row in rows:
        lines.append(json.dumps(row, ensure_ascii=False))
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare_weight_files(paths: list[str], team: str, simulations: int, seed: int | None) -> None:
    if len(paths) < 2:
        raise SystemExit("Erro: informe ao menos dois arquivos em --compare-weight-files")
    rows = []
    comparisons = []
    for path in paths:
        try:
            result = run(simulations, seed, None, team, False, "calibrated", None, path, write_output=False)
        except ValueError as exc:
            raise SystemExit(f"Erro: {exc}") from exc
        team_row = next(r for r in result["rows"] if r["team"] == team)
        breakdown = result.get("rating_breakdown", {}).get(team, {})
        row = {
            "weights_file": path,
            "winner_pct": team_row["winner_pct"],
            "final_pct": team_row["final_pct"],
            "semifinal_pct": team_row["semifinal_pct"],
            "quarterfinal_pct": team_row["quarterfinal_pct"],
            "round16_pct": team_row["round16_pct"],
            "round32_pct": team_row["round32_pct"],
            "group_winner_pct": team_row["group_winner_pct"],
            "group_runner_up_pct": team_row["group_runner_up_pct"],
            "best_third_pct": team_row["best_third_pct"],
            "group_eliminated_pct": team_row["group_eliminated_pct"],
            "winner_ci_low": team_row["winner_ci_low"],
            "winner_ci_high": team_row["winner_ci_high"],
            "round32_opponent_most_common": team_row["most_common_round32_opponent"],
            "calibrated_rating": breakdown.get("final_rating", ""),
            "rating_delta": breakdown.get("delta_total", ""),
            "top_10": "; ".join(r["team"] for r in result["rows"][:10]),
            "weight_differences": _weight_summary(result.get("model_config", {})),
        }
        rows.append(row)
        comparisons.append({"path": path, "result": result, "team_row": team_row, "breakdown": breakdown})
    _write_weight_file_report(rows, comparisons, team)
    print(f"[ok] weight files comparison: output/weights_comparison_{team}.csv")


def _write_weight_file_report(rows: list[dict], comparisons: list[dict], team: str) -> None:
    out = Path("output")
    out.mkdir(exist_ok=True)
    csv_path = out / f"weights_comparison_{team}.csv"
    txt_path = out / f"weights_comparison_{team}.txt"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [f"weights comparison - {team}", ""]
    for row in rows:
        lines.append(f"Arquivo: {row['weights_file']}")
        lines.append(
            f"  Titulo {row['winner_pct']:.2f}% | Final {row['final_pct']:.2f}% | "
            f"Semifinal {row['semifinal_pct']:.2f}% | Quartas {row['quarterfinal_pct']:.2f}% | "
            f"Oitavas {row['round16_pct']:.2f}% | R32 {row['round32_pct']:.2f}%"
        )
        lines.append(
            f"  Grupo: 1o {row['group_winner_pct']:.2f}% | 2o {row['group_runner_up_pct']:.2f}% | "
            f"3o classificado {row['best_third_pct']:.2f}% | eliminado {row['group_eliminated_pct']:.2f}%"
        )
        lines.append(f"  Rating calibrado: {row['calibrated_rating']} ({row['rating_delta']:+})")
        lines.append(f"  Top 10: {row['top_10']}")
        lines.append(f"  Pesos: {row['weight_differences']}")
        lines.append("")
    if len(comparisons) >= 2:
        lines.extend(_weight_file_analysis(comparisons[0], comparisons[1], team))
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _weight_file_analysis(a: dict, b: dict, team: str) -> list[str]:
    ar, br = a["team_row"], b["team_row"]
    lines = ["Analise automatica", ""]
    metrics = [
        ("Titulo", "winner_pct"),
        ("Final", "final_pct"),
        ("Semifinal", "semifinal_pct"),
        ("Quartas", "quarterfinal_pct"),
        ("Oitavas", "round16_pct"),
        ("Round of 32", "round32_pct"),
        ("1o do grupo", "group_winner_pct"),
        ("2o do grupo", "group_runner_up_pct"),
        ("Melhor terceiro", "best_third_pct"),
        ("Eliminacao no grupo", "group_eliminated_pct"),
    ]
    lines.append("Deltas principais (arquivo B - arquivo A):")
    for label, key in metrics:
        lines.append(f"- {label}: {_delta(br[key] - ar[key])} p.p.")
    title_delta = br["winner_pct"] - ar["winner_pct"]
    group_delta = br["group_winner_pct"] - ar["group_winner_pct"]
    lines.append("")
    lines.append(_movement_sentence("chance de titulo", title_delta))
    lines.append(_movement_sentence("chance de terminar em 1o do grupo", group_delta))
    ci_overlap = not (br["winner_ci_low"] > ar["winner_ci_high"] or br["winner_ci_high"] < ar["winner_ci_low"])
    lines.append(
        "A mudanca de titulo esta dentro do intervalo de confianca Monte Carlo."
        if ci_overlap else
        "A mudanca de titulo supera a sobreposicao simples dos intervalos de confianca Monte Carlo."
    )
    lines += ["", "Adversarios mais comuns no Round of 32:"]
    opp_a = _opp_map(a["result"], team)
    opp_b = _opp_map(b["result"], team)
    lines.append(f"Arquivo A ({a['path']}):")
    for name, pct in list(opp_a.items())[:5]:
        lines.append(f"- {name}: {pct:.2f}%")
    lines.append(f"Arquivo B ({b['path']}):")
    for name, pct in list(opp_b.items())[:5]:
        lines.append(f"- {name}: {pct:.2f}% ({_delta(pct - opp_a.get(name, 0.0))} p.p.)")
    lines.append("Diferencas principais:")
    opponent_names = sorted(set(opp_a) | set(opp_b), key=lambda name: abs(opp_b.get(name, 0.0) - opp_a.get(name, 0.0)), reverse=True)
    for name in opponent_names[:5]:
        lines.append(f"- {name}: {_delta(opp_b.get(name, 0.0) - opp_a.get(name, 0.0))} p.p.")
    strong = {"Netherlands", "Germany", "Belgium", "Croatia", "Portugal", "Spain", "France", "England", "Argentina", "Brazil", "Morocco"}
    strong_a = sum(pct for name, pct in opp_a.items() if name in strong)
    strong_b = sum(pct for name, pct in opp_b.items() if name in strong)
    avg_a = _weighted_opponent_rating(opp_a, a["result"].get("rating_breakdown", {}))
    avg_b = _weighted_opponent_rating(opp_b, b["result"].get("rating_breakdown", {}))
    rating_delta = avg_b - avg_a
    lines.append(f"Adversarios fortes: {strong_a:.2f}% -> {strong_b:.2f}% ({_delta(strong_b - strong_a)} p.p.)")
    lines.append(f"Rating medio ponderado dos adversarios: {avg_a:.0f} -> {avg_b:.0f} ({_delta(rating_delta)})")
    if strong_b > strong_a + 1 or rating_delta > 10:
        lines.append("O caminho no Round of 32 ficou mais dificil.")
    elif strong_b < strong_a - 1 or rating_delta < -10:
        lines.append("O caminho no Round of 32 ficou mais facil.")
    else:
        lines.append("O caminho no Round of 32 nao mudou de forma clara.")
    lines += ["", "Top 10 favoritos ao titulo:"]
    lines.append(f"Arquivo A: {'; '.join(row['team'] for row in a['result']['rows'][:10])}")
    lines.append(f"Arquivo B: {'; '.join(row['team'] for row in b['result']['rows'][:10])}")
    lines += ["", "Ratings calibrados:"]
    lines.append(
        f"{team}: {a['breakdown'].get('final_rating')} -> {b['breakdown'].get('final_rating')} "
        f"({_delta((b['breakdown'].get('final_rating') or 0) - (a['breakdown'].get('final_rating') or 0))})"
    )
    lines += ["", "Pesos principais:"]
    lines.append(f"Arquivo A: {_weight_summary(a['result'].get('model_config', {}))}")
    lines.append(f"Arquivo B: {_weight_summary(b['result'].get('model_config', {}))}")
    lines += ["", f"Diagnostico: {_diagnosis(title_delta, ci_overlap, a, b)}"]
    return lines


def _weight_summary(weights: dict) -> str:
    rating = weights.get("rating_model", {})
    poisson = weights.get("poisson", {})
    knockout = weights.get("knockout", {})
    return (
        f"form={rating.get('tournament_form_weight')}; "
        f"market={rating.get('market_odds_weight')}; "
        f"draw={poisson.get('draw_correction_factor')}; "
        f"scale={poisson.get('goal_advantage_scale')}; "
        f"ko_sens={knockout.get('sensitivity')}; "
        f"upset_floor={knockout.get('upset_floor')}; "
        f"favorite_ceiling={knockout.get('favorite_ceiling')}; "
        f"goal_diff={weights.get('form_adjustment', {}).get('goal_difference_weight')}"
    )


def _opp_map(result: dict, team: str) -> dict[str, float]:
    items = result.get("team_paths", {}).get(team, {}).get("round32_opponents", [])
    return {item["name"]: item["pct"] for item in items}


def _weighted_opponent_rating(opponents: dict[str, float], breakdown: dict) -> float:
    total = sum(opponents.values())
    if not total:
        return 0.0
    return sum((breakdown.get(name, {}).get("final_rating", 0) or 0) * pct for name, pct in opponents.items()) / total


def _delta(value: float) -> str:
    return f"{value:+.2f}"


def _movement_sentence(label: str, delta: float) -> str:
    if abs(delta) < 0.25:
        return f"A {label} ficou praticamente estavel ({_delta(delta)} p.p.)."
    direction = "subiu" if delta > 0 else "caiu"
    return f"A {label} {direction} {_delta(delta)} p.p."


def _diagnosis(title_delta: float, ci_overlap: bool, a: dict, b: dict) -> str:
    if ci_overlap and abs(title_delta) < 1.0:
        return "mudanca dentro da margem de erro"
    if abs(title_delta) < 1.0:
        return "mudanca pequena"
    cfg_b = b["result"].get("model_config", {})
    form = cfg_b.get("rating_model", {}).get("tournament_form_weight", 0)
    goal = cfg_b.get("form_adjustment", {}).get("goal_difference_weight", 0)
    if form >= 0.35 and goal >= 8 and abs(title_delta) >= 2.0:
        return "possivel overfitting"
    return "mudanca relevante"


def run_workflow(args) -> None:
    if args.workflow != "full":
        raise SystemExit(f"Workflow nao suportado: {args.workflow}")
    report = _run_full_workflow(args)
    print("[ok] workflow full")
    for step in report["steps"]:
        print(f"  [{step['status']}] {step['name']}: {step['message']}")
    print(f"  Relatorio: {report['latest_report']}")


def _run_full_workflow(args) -> dict:
    team = args.team
    simulations = args.simulations or 200000
    seed = args.seed if args.seed is not None else 42
    updater = MultiSourceResultsUpdater()
    steps: list[dict] = []
    metrics: dict = {"team": team, "simulations": simulations, "seed": seed}
    outputs: list[str] = []

    def add_step(name: str, status: str, message: str, step_outputs: list[str] | None = None, step_metrics: dict | None = None) -> None:
        steps.append({
            "name": name,
            "status": status,
            "message": message,
            "outputs": step_outputs or [],
            "metrics": step_metrics or {},
        })
        outputs.extend(step_outputs or [])

    # 1. source-health-check
    try:
        health = updater.health_check()
        health_summary = ", ".join(f"{row['source']}={row['status']}({row['matches']})" for row in health.get("sources", []))
        add_step("source-health-check", "ok", health_summary, ["output/source_health_report.txt"], {"sources": health.get("sources", [])})
        metrics["source_health"] = health.get("sources", [])
    except Exception as exc:
        add_step("source-health-check", "error", str(exc), ["output/source_health_report.txt"])
        return _write_workflow_report("full", steps, metrics, outputs)

    # 2. dry-run-multisource
    try:
        dry = updater.update(dry_run=True, allow_future_results=args.allow_future_results)
        conflict_count = len(dry.get("conflicts", []))
        warning_count = len(dry.get("warnings", []))
        message = (
            f"alteradas={dry.get('changed_real', 0)}, live_score={dry.get('non_final_score_detected', 0)}, "
            f"metadata={dry.get('metadata_only', 0)}, conflitos={conflict_count}, warnings={warning_count}"
        )
        status = "warning" if warning_count else "ok"
        if conflict_count:
            status = "error" if not args.continue_on_conflict else "warning"
        add_step("dry-run-multisource", status, message, ["output/multisource_update_report.txt", "output/group_integrity_report.txt"], dry)
        metrics["dry_run"] = {
            "changed_real": dry.get("changed_real", 0),
            "non_final_score_detected": dry.get("non_final_score_detected", 0),
            "metadata_only": dry.get("metadata_only", 0),
            "conflicts": conflict_count,
            "warnings": warning_count,
        }
        if conflict_count and not args.continue_on_conflict:
            add_step("workflow-stop", "error", "conflito critico detectado; use --continue-on-conflict para continuar")
            return _write_workflow_report("full", steps, metrics, outputs)
    except Exception as exc:
        add_step("dry-run-multisource", "error", str(exc), ["output/multisource_update_report.txt", "output/group_integrity_report.txt"])
        return _write_workflow_report("full", steps, metrics, outputs)

    # 3. update-results-multisource-only
    if args.skip_update:
        add_step("update-results-multisource-only", "skipped", "--skip-update informado")
    else:
        try:
            update = updater.update(dry_run=False, allow_future_results=args.allow_future_results)
            message = (
                f"alteradas={update.get('changed_real', 0)}, live_score={update.get('non_final_score_detected', 0)}, "
                f"metadata={update.get('metadata_only', 0)}, conflitos={len(update.get('conflicts', []))}, warnings={len(update.get('warnings', []))}"
            )
            add_step("update-results-multisource-only", "ok", message, ["output/multisource_update_report.txt", "output/group_integrity_report.txt"], update)
            metrics["update"] = {
                "changed_real": update.get("changed_real", 0),
                "non_final_score_detected": update.get("non_final_score_detected", 0),
                "metadata_only": update.get("metadata_only", 0),
                "conflicts": len(update.get("conflicts", [])),
                "warnings": len(update.get("warnings", [])),
            }
        except Exception as exc:
            add_step("update-results-multisource-only", "error", str(exc), ["output/multisource_update_report.txt", "output/group_integrity_report.txt"])
            return _write_workflow_report("full", steps, metrics, outputs)

    # 4. auditoria de grupo/time
    try:
        group = _group_for_team(team)
        audit = updater.audit_group(group)
        add_step("audit-group", "ok", f"grupo {group} auditado para {team}", [f"output/audit_group_{group}.txt"], {"group": group, "matches": len(audit.get("matches", []))})
        metrics["team_group"] = group
    except Exception as exc:
        add_step("audit-group", "warning", str(exc))

    # 5. backtest
    if args.skip_backtest:
        add_step("backtest", "skipped", "--skip-backtest informado")
    else:
        try:
            provider = LocalJsonDataProvider()
            weights = load_model_weights(args.model_preset)
            backtest = evaluate_finished_matches(provider.load_matches(), provider.load_ratings(), weights, calibrate_ratings=True)
            write_backtest_report(backtest)
            msg = f"jogos={backtest['matches_evaluated']}"
            if backtest.get("brier_mean") is not None:
                msg += f", Brier={backtest['brier_mean']:.3f}, LogLoss={backtest['log_loss_mean']:.3f}"
            add_step("backtest", "ok", msg, ["output/backtest_report.txt", "output/backtest_results.csv", "output/backtest_errors_top.csv"], backtest)
            baselines = backtest.get("baselines", {}) or {}
            metrics["backtest"] = {
                "matches": backtest.get("matches_evaluated"),
                "brier": backtest.get("brier_mean"),
                "log_loss": backtest.get("log_loss_mean"),
                "uniform_brier": baselines.get("uniform", {}).get("brier_mean"),
                "uniform_log_loss": baselines.get("uniform", {}).get("log_loss_mean"),
                "rating_brier": baselines.get("rating", {}).get("brier_mean"),
                "rating_log_loss": baselines.get("rating", {}).get("log_loss_mean"),
            }
        except Exception as exc:
            add_step("backtest", "error", str(exc), ["output/backtest_report.txt", "output/backtest_results.csv", "output/backtest_errors_top.csv"])
            return _write_workflow_report("full", steps, metrics, outputs)

    # 6. tune-weights
    best_weights = Path("output/best_model_weights.json")
    if args.skip_tuning:
        add_step("tune-weights", "skipped", "--skip-tuning informado")
    else:
        try:
            provider = LocalJsonDataProvider()
            weights = load_model_weights(args.model_preset)
            tuned = tune_weights_grid(provider.load_matches(), provider.load_ratings(), weights)
            JsonStore().write("output/best_model_weights.json", tuned)
            msg = f"testadas={tuned['tested']}, original={tuned['baseline']['brier_mean']:.3f}, melhor={tuned['best']['brier_mean']:.3f}, melhora={tuned['improvement']:.3f}"
            add_step("tune-weights", "ok", msg, ["output/best_model_weights.json"], tuned)
            metrics["tuning"] = {"tested": tuned.get("tested"), "baseline_brier": tuned.get("baseline", {}).get("brier_mean"), "best_brier": tuned.get("best", {}).get("brier_mean"), "improvement": tuned.get("improvement")}
        except Exception as exc:
            add_step("tune-weights", "error", str(exc), ["output/best_model_weights.json"])
            return _write_workflow_report("full", steps, metrics, outputs)

    # 7. simulacao balanced
    balanced_result = None
    try:
        balanced = run(simulations, seed, args.scenario, team, False, "calibrated", "balanced", None)
        balanced_result = balanced
        team_row = next(r for r in balanced["rows"] if r["team"] == team)
        msg = _simulation_step_message(team, team_row)
        add_step("simulation-balanced", "ok", msg, _simulation_outputs(team, include_calibrated=True), {"team_row": team_row})
        metrics["balanced"] = _team_metrics(team_row)
        metrics["balanced_path"] = _team_path_metrics(balanced, team)
    except Exception as exc:
        add_step("simulation-balanced", "error", str(exc), _simulation_outputs(team, include_calibrated=True))
        return _write_workflow_report("full", steps, metrics, outputs)

    # 8. simulacao ajustada
    tuned_result = None
    if args.no_run_tuned:
        add_step("simulation-tuned", "skipped", "--no-run-tuned informado")
    elif not best_weights.exists():
        add_step("simulation-tuned", "skipped", "output/best_model_weights.json nao encontrado")
    else:
        try:
            tuned_result = run(simulations, seed, args.scenario, team, False, "calibrated", None, str(best_weights))
            tuned_row = next(r for r in tuned_result["rows"] if r["team"] == team)
            msg = _simulation_step_message(team, tuned_row)
            add_step("simulation-tuned", "ok", msg, _simulation_outputs(team, include_calibrated=True), {"team_row": tuned_row, "weights_file": str(best_weights)})
            metrics["tuned"] = _team_metrics(tuned_row)
            metrics["tuned_path"] = _team_path_metrics(tuned_result, team)
        except Exception as exc:
            add_step("simulation-tuned", "error", str(exc), _simulation_outputs(team, include_calibrated=True))
            return _write_workflow_report("full", steps, metrics, outputs)

    # 9. panorama geral opcional
    if args.global_report:
        try:
            report_outputs, global_metrics = _write_global_report(balanced_result, tuned_result, metrics)
            leader = global_metrics.get("top_title_balanced", [{}])[0].get("team", "n/d") if global_metrics.get("top_title_balanced") else "n/d"
            add_step("global-report", "ok", f"panorama geral gerado; favorito Modelo Padrão={leader}", report_outputs, global_metrics)
            metrics["global_report"] = global_metrics
        except Exception as exc:
            add_step("global-report", "warning", str(exc), _global_report_outputs())

    # 10. compare-weight-files
    if args.no_run_tuned or not best_weights.exists():
        add_step("compare-weight-files", "skipped", "sem simulação ajustada/arquivo de pesos")
    else:
        try:
            compare_weight_files(["data/model_weights.json", str(best_weights)], team, simulations, seed)
            add_step("compare-weight-files", "ok", f"comparacao gerada para {team}", [f"output/weights_comparison_{team}.csv", f"output/weights_comparison_{team}.txt"])
            metrics["compare_weight_files"] = {"csv": f"output/weights_comparison_{team}.csv", "txt": f"output/weights_comparison_{team}.txt"}
        except Exception as exc:
            add_step("compare-weight-files", "warning", str(exc), [f"output/weights_comparison_{team}.csv", f"output/weights_comparison_{team}.txt"])

    # 11. relatorio consolidado
    return _write_workflow_report("full", steps, metrics, outputs)


def _group_for_team(team: str) -> str:
    groups = JsonStore().read("data/groups.json", {})
    for group, teams in groups.items():
        if team in teams:
            return group
    raise ValueError(f"Time nao encontrado em data/groups.json: {team}")


def _simulation_outputs(team: str, include_calibrated: bool = False) -> list[str]:
    outputs = [
        "output/probabilities.csv",
        "output/probabilities.json",
        "output/summary.txt",
        f"output/team_paths_{team}.json",
        "output/model_explanation.txt",
    ]
    if include_calibrated:
        outputs.extend(["output/rating_breakdown.csv", "output/rating_breakdown.json"])
    return outputs


def _team_metrics(team_row: dict) -> dict:
    keys = [
        "winner_pct", "final_pct", "semifinal_pct", "quarterfinal_pct", "round16_pct", "round32_pct",
        "group_winner_pct", "group_runner_up_pct", "best_third_pct", "group_eliminated_pct",
        "winner_ci_low", "winner_ci_high", "most_common_round32_opponent",
    ]
    return {key: team_row.get(key) for key in keys}


def _team_path_metrics(result: dict, team: str) -> dict:
    path = result.get("team_paths", {}).get(team, {}) or {}
    return {
        "round32_opponents": path.get("round32_opponents", [])[:5],
        "round32_matches": path.get("round32_matches", [])[:5],
        "elimination_stages": path.get("elimination_stages", [])[:5],
    }


from src.workflow_reports import (
    _executive_summary_lines,
    _global_report_outputs,
    _global_risk_lines,
    _group_leadership_outlook_rows,
    _group_outlook_rows,
    _group_qualification_outlook_rows,
    _model_sensitivity_rows,
    _pct,
    _simulation_step_message,
    _write_global_report,
    _write_workflow_report,
)


if __name__ == "__main__":
    main()
