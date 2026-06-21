from __future__ import annotations

import argparse
from collections.abc import Sequence

from src.team_names import resolve_team_name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simulador Monte Carlo da Copa do Mundo FIFA 2026")
    parser.add_argument("--workflow", choices=["full"], default=None, help="Executa um fluxo orquestrado na ordem ideal.")
    parser.add_argument("--skip-update", action="store_true", help="No workflow, pula a atualizacao multi-source real.")
    parser.add_argument("--skip-tuning", action="store_true", help="No workflow, pula o tune-weights.")
    parser.add_argument("--skip-backtest", action="store_true", help="No workflow, pula o backtest.")
    parser.add_argument("--no-run-tuned", action="store_true", help="No workflow, nao roda a simulacao tuned com output/best_model_weights.json.")
    parser.add_argument("--continue-on-conflict", action="store_true", help="No workflow, continua mesmo se o dry-run encontrar conflitos.")
    parser.add_argument("--global-report", action="store_true", help="No workflow full, gera panorama geral da Copa alem da analise do time.")
    parser.add_argument("--all-teams", action="store_true", help="Alias de --global-report para gerar panorama geral de todas as selecoes.")
    parser.add_argument("--simulations", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--team", default="Brazil")
    parser.add_argument("--offline", action="store_true", help="Usa apenas arquivos locais.")
    parser.add_argument("--update-data", action="store_true", help="Atualiza dados antes de simular.")
    parser.add_argument("--update-data-only", action="store_true", help="Atualiza dados e nao roda simulacao.")
    parser.add_argument("--update-results", action="store_true", help="Atualiza apenas resultados.")
    parser.add_argument("--update-odds", action="store_true", help="Atualiza apenas odds.")
    parser.add_argument("--update-rankings", action="store_true", help="Atualiza apenas rankings.")
    parser.add_argument("--scrape-results", action="store_true", help="Raspa fixtures/resultados de fontes publicas antes de simular.")
    parser.add_argument("--scrape-results-only", action="store_true", help="Raspa fixtures/resultados e nao roda simulacao.")
    parser.add_argument("--dry-run-scrape", action="store_true", help="Busca e compara resultados raspados sem salvar matches.json.")
    parser.add_argument("--update-results-multisource", action="store_true")
    parser.add_argument("--update-results-multisource-only", action="store_true")
    parser.add_argument("--dry-run-multisource", action="store_true")
    parser.add_argument("--allow-future-results", action="store_true")
    parser.add_argument("--source-health-check", action="store_true")
    parser.add_argument("--audit-group", default=None)
    parser.add_argument("--audit-match", default=None)
    parser.add_argument("--recalibrate-ratings", action="store_true", help="Recalibra ratings com resultados reais ja salvos.")
    parser.add_argument("--use-adjusted-ratings", action="store_true", help="Usa data/adjusted_ratings.json na simulacao.")
    parser.add_argument("--rating-source", choices=["base", "adjusted", "calibrated"], default="base")
    parser.add_argument("--model-preset", default=None)
    parser.add_argument("--weights-file", default=None)
    parser.add_argument("--compare-weight-files", nargs="+", default=None)
    parser.add_argument("--analyze-weights", action="store_true")
    parser.add_argument("--sensitivity-analysis", action="store_true")
    parser.add_argument("--compare-presets", action="store_true")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--tune-weights", action="store_true")
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.team = resolve_team_name(args.team)
    except ValueError as exc:
        parser.error(str(exc))
    if args.scrape_results_only and args.offline:
        parser.error("--scrape-results-only precisa de internet; remova --offline.")
    if args.all_teams:
        args.global_report = True
    return args
