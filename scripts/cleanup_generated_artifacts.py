#!/usr/bin/env python3
"""
Limpa artefatos gerados/temporarios do simulador_da_copa_2026 sem apagar dados essenciais.

Uso recomendado, primeiro em dry-run:
  python scripts/cleanup_generated_artifacts.py --profile lean

Aplicar limpeza segura mantendo os itens mais recentes:
  python scripts/cleanup_generated_artifacts.py --profile lean --apply

Limpeza mais agressiva de relatorios raiz em output/:
  python scripts/cleanup_generated_artifacts.py --profile aggressive --apply

O script sempre preserva:
- data/matches.json e demais arquivos base em data/;
- output/workflows/latest_full_report.json;
- output/workflows/latest_full_report.txt;
- output/workflows/latest_report.txt;
- .gitkeep.
"""
from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Candidate:
    path: Path
    kind: str  # file | dir
    reason: str
    size: int


# Arquivos da investigacao antiga da API/site FIFA. O cliente atual usa data/raw/fifa/*.json.
OBSOLETE_FIFA_OUTPUT_PATTERNS = [
    "output/fifa_chunk_*.js",
    "output/fifa_chunk_*.chunk.js",
    "output/fifa_*bundle*.js",
    "output/fifa__static_js_main*.js",
    "output/fifa__smt-base-bridge*",
    "output/fifa_scores_fixtures_probe.html",
    "output/fifa_api_*.json",
]

CACHE_DIR_PATTERNS = [
    "**/__pycache__",
    ".pytest_cache",
    ".test_tmp",
    ".pytest_workspace",
    ".tmp",
    "pytest-cache-files-*",
]

CACHE_FILE_PATTERNS = [
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pyc.*",
]

TEST_OUTPUT_PATTERNS = [
    "output/test_*",
    "output/test_reports",
    "output/test_update_v2",
    "output/test_calibration_v3",
]

# Relatorios raiz que podem ser regenerados pelo workflow.
# latest/workflows ficam protegidos em regra separada.
GENERATED_ROOT_REPORT_PATTERNS = [
    "output/*.csv",
    "output/*.json",
    "output/*.txt",
]

RAW_GROUPS = {
    "raw FIFA antigo": ["data/raw/fifa/fifa_official_*.json"],
    "raw OpenFootball antigo": ["data/raw/openfootball/openfootball_*.json"],
    "raw Wikipedia antigo": [
        "data/raw/wikipedia/wikipedia_worldcup_*.html",
        "data/raw/wikipedia_worldcup_*.html",
    ],
}

SNAPSHOT_GROUPS = {
    "snapshot antigo de data/matches": ["data/snapshots/matches_*.json"],
    "snapshot antigo de output": ["output/snapshots/*.json"],
}

SNAPSHOT_DIR_PATTERNS = [
    "data/snapshots/20*T*",
]

WORKFLOW_REPORT_PATTERNS = [
    "output/workflows/*_full_report.json",
    "output/workflows/*_full_report.txt",
]

PROTECTED_NAMES = {".gitkeep"}
PROTECTED_PREFIXES = {
    # dados base
    "data/groups.json",
    "data/matches.json",
    "data/ratings.json",
    "data/adjusted_ratings.json",
    "data/calibrated_ratings.json",
    "data/third_place_mapping.json",
    "data/knockout_bracket.json",
    "data/model_weights.json",
    "data/model_presets.json",
    "data/source_priority.json",
    "data/team_aliases.json",
    "data/external_sources.json",
    # ponteiros de relatorio sempre preservados
    "output/workflows/latest_full_report.json",
    "output/workflows/latest_full_report.txt",
    "output/workflows/latest_report.txt",
}

# Arquivos raiz de output que representam o estado atual e geralmente valem manter.
CURRENT_OUTPUT_REPORTS = {
    "output/latest_global_report.txt",
    "output/global_title_ranking.csv",
    "output/global_stage_probabilities.csv",
    "output/global_group_outlook.csv",
    "output/global_group_leadership_outlook.csv",
    "output/global_group_qualification_outlook.csv",
    "output/global_model_sensitivity.csv",
    "output/global_risk_report.txt",
    "output/source_health_report.txt",
    "output/multisource_update_report.txt",
    "output/multisource_update_report.json",
    "output/group_integrity_report.txt",
    "output/probabilities.csv",
    "output/probabilities.json",
    "output/summary.txt",
    "output/model_explanation.txt",
    "output/rating_breakdown.csv",
    "output/rating_breakdown.json",
    "output/backtest_report.txt",
    "output/backtest_results.csv",
    "output/backtest_errors_top.csv",
    "output/best_model_weights.json",
}


@dataclass
class SizeEntry:
    path: Path
    kind: str
    size: int


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{size} B"


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file() or child.is_symlink():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def relpath(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def is_protected(root: Path, path: Path) -> bool:
    if path.name in PROTECTED_NAMES:
        return True
    rel = relpath(root, path)
    return rel in PROTECTED_PREFIXES


def collect_by_patterns(root: Path, patterns: Iterable[str], reason: str, only_dirs: bool | None = None) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            path = path.resolve()
            if path in seen or not path.exists() or is_protected(root, path):
                continue
            if only_dirs is True and not path.is_dir():
                continue
            if only_dirs is False and not path.is_file():
                continue
            seen.add(path)
            out.append(Candidate(path, "dir" if path.is_dir() else "file", reason, path_size(path)))
    return out


def keep_latest_by_mtime(candidates: list[Candidate], keep: int) -> list[Candidate]:
    if keep < 0:
        raise ValueError("keep deve ser >= 0")
    if keep == 0:
        return candidates
    existing = [c for c in candidates if c.path.exists()]
    existing.sort(key=lambda c: c.path.stat().st_mtime, reverse=True)
    keep_set = {c.path for c in existing[:keep]}
    return [c for c in candidates if c.path not in keep_set]


def collect_group_retention(root: Path, groups: dict[str, list[str]], keep: int) -> list[Candidate]:
    candidates: list[Candidate] = []
    for reason, patterns in groups.items():
        group_candidates = collect_by_patterns(root, patterns, reason, only_dirs=False)
        candidates += keep_latest_by_mtime(group_candidates, keep)
    return candidates


def workflow_stem(path: Path) -> str:
    name = path.name
    for suffix in ("_full_report.json", "_full_report.txt"):
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return path.stem


def collect_old_snapshot_dirs(root: Path, keep: int) -> list[Candidate]:
    dirs: list[Candidate] = []
    for pattern in SNAPSHOT_DIR_PATTERNS:
        for path in root.glob(pattern):
            if path.is_dir() and not is_protected(root, path):
                dirs.append(Candidate(path.resolve(), "dir", "diretorio de snapshot antigo", path_size(path)))
    return keep_latest_by_mtime(dirs, keep)


def collect_old_workflows(root: Path, keep: int) -> list[Candidate]:
    files: list[Path] = []
    for pattern in WORKFLOW_REPORT_PATTERNS:
        files.extend(path for path in root.glob(pattern) if path.is_file() and not is_protected(root, path))

    by_stem: dict[str, list[Path]] = {}
    for path in files:
        by_stem.setdefault(workflow_stem(path), []).append(path)

    # timestamp ISO-like no nome: ordenar por stem desc funciona para datas yyyy-mm-dd_hh-mm-ss.
    stems = sorted(by_stem, reverse=True)
    keep_stems = set(stems[:keep]) if keep > 0 else set()

    out: list[Candidate] = []
    for stem, paths in by_stem.items():
        if stem in keep_stems:
            continue
        for path in paths:
            out.append(Candidate(path.resolve(), "file", "workflow historico antigo", path_size(path)))
    return out


def collect_root_reports(root: Path, keep_current: bool) -> list[Candidate]:
    candidates = collect_by_patterns(root, GENERATED_ROOT_REPORT_PATTERNS, "relatorio raiz gerado em output/", only_dirs=False)
    if not keep_current:
        return candidates
    return [c for c in candidates if relpath(root, c.path) not in CURRENT_OUTPUT_REPORTS]


def dedupe(candidates: list[Candidate]) -> list[Candidate]:
    by_path: dict[Path, Candidate] = {}
    # Diretórios primeiro; se pai será removido, não listar filhos.
    for c in sorted(candidates, key=lambda item: (item.kind != "dir", len(item.path.parts))):
        if any(parent in by_path and by_path[parent].kind == "dir" for parent in c.path.parents):
            continue
        existing = by_path.get(c.path)
        if existing is None or (existing.kind != "dir" and c.kind == "dir"):
            by_path[c.path] = c
    return sorted(by_path.values(), key=lambda c: (c.kind != "dir", str(c.path)))


def collect_candidates(args: argparse.Namespace) -> list[Candidate]:
    root = args.root.resolve()
    candidates: list[Candidate] = []

    clean_cache = args.clean_cache
    clean_raw = args.clean_raw
    clean_snapshots = args.clean_snapshots
    clean_workflows = args.clean_workflows
    clean_root_reports = args.clean_root_reports
    clean_frontend_dist = args.clean_frontend_dist

    if args.profile in {"lean", "aggressive"}:
        clean_cache = True
        clean_raw = True
        clean_snapshots = True
        clean_workflows = True
    if args.profile == "aggressive":
        clean_root_reports = True
        clean_frontend_dist = True

    if clean_cache:
        candidates += collect_by_patterns(root, OBSOLETE_FIFA_OUTPUT_PATTERNS, "artefato antigo de investigacao FIFA/API", only_dirs=False)
        candidates += collect_by_patterns(root, CACHE_DIR_PATTERNS, "cache/diretorio temporario", only_dirs=True)
        candidates += collect_by_patterns(root, CACHE_FILE_PATTERNS, "cache Python compilado", only_dirs=False)
        candidates += collect_by_patterns(root, TEST_OUTPUT_PATTERNS, "saida temporaria de testes")

    if clean_raw:
        candidates += collect_group_retention(root, RAW_GROUPS, args.keep_raw)

    if clean_snapshots:
        candidates += collect_group_retention(root, SNAPSHOT_GROUPS, args.keep_snapshots)
        candidates += collect_old_snapshot_dirs(root, args.keep_snapshots)

    if clean_workflows:
        candidates += collect_old_workflows(root, args.keep_workflows)

    if clean_root_reports:
        candidates += collect_root_reports(root, keep_current=not args.delete_current_reports)

    if clean_frontend_dist:
        candidates += collect_by_patterns(root, ["frontend/dist"], "build frontend regeneravel", only_dirs=True)

    return dedupe(candidates)


def remove_candidate(candidate: Candidate) -> None:
    path = candidate.path
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.chmod(0o666)
        except OSError:
            pass
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def collect_size_entries(root: Path, top: int) -> list[SizeEntry]:
    entries: list[SizeEntry] = []
    for child in root.rglob("*"):
        if child.is_file():
            entries.append(SizeEntry(child, "file", path_size(child)))
    return sorted(entries, key=lambda e: e.size, reverse=True)[:top]


def print_size_report(root: Path, top: int) -> None:
    print("[ANALISE] Maiores arquivos")
    for entry in collect_size_entries(root, top):
        print(f"- {human_size(entry.size):>10s}  {relpath(root, entry.path)}")

    print("\n[ANALISE] Tamanho por diretorio de primeiro nivel")
    dirs: dict[str, int] = {}
    for child in root.rglob("*"):
        if child.is_file():
            rel = relpath(root, child)
            top_dir = rel.split("/", 1)[0]
            dirs[top_dir] = dirs.get(top_dir, 0) + path_size(child)
    for name, size in sorted(dirs.items(), key=lambda item: item[1], reverse=True):
        print(f"- {human_size(size):>10s}  {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Limpa artefatos gerados sem remover dados essenciais do simulador.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Raiz do projeto. Default: diretório atual.")
    parser.add_argument("--apply", action="store_true", help="Aplica a remocao. Sem isso, executa apenas dry-run.")
    parser.add_argument("--profile", choices=["none", "lean", "aggressive"], default="none", help="Preset de limpeza. lean e o recomendado.")
    parser.add_argument("--analyze", action="store_true", help="Mostra maiores arquivos/diretorios antes da limpeza.")
    parser.add_argument("--top", type=int, default=25, help="Quantidade de arquivos no relatorio --analyze. Default: 25.")

    parser.add_argument("--clean-cache", action="store_true", help="Remove caches Python/testes e artefatos obsoletos.")
    parser.add_argument("--clean-raw", action="store_true", help="Remove raw HTML/JSON antigo em data/raw por fonte.")
    parser.add_argument("--clean-snapshots", action="store_true", help="Remove snapshots antigos.")
    parser.add_argument("--clean-workflows", action="store_true", help="Remove historico antigo de output/workflows mantendo os ultimos N runs.")
    parser.add_argument("--clean-root-reports", action="store_true", help="Remove relatorios raiz gerados em output/. Por padrao preserva relatorios atuais importantes.")
    parser.add_argument("--clean-frontend-dist", action="store_true", help="Remove frontend/dist, que pode ser regenerado com npm run build.")
    parser.add_argument("--delete-current-reports", action="store_true", help="Com --clean-root-reports, tambem remove relatorios atuais. Use com cuidado.")

    parser.add_argument("--keep", type=int, default=None, help="Atalho para definir keep de raw/snapshots/workflows ao mesmo tempo.")
    parser.add_argument("--keep-raw", type=int, default=3, help="Raw recentes a manter por fonte/padrao. Default: 3.")
    parser.add_argument("--keep-snapshots", type=int, default=5, help="Snapshots recentes a manter por grupo. Default: 5.")
    parser.add_argument("--keep-workflows", type=int, default=3, help="Runs historicos de workflow a manter, alem de latest_*. Default: 3.")
    args = parser.parse_args()

    root = args.root.resolve()
    if not (root / "main.py").exists() or not (root / "src").exists():
        raise SystemExit(f"ERRO: {root} não parece ser a raiz do projeto. Rode na pasta do projeto ou use --root.")

    if args.keep is not None:
        args.keep_raw = args.keep
        args.keep_snapshots = args.keep
        args.keep_workflows = args.keep

    if args.analyze:
        print_size_report(root, args.top)
        print()

    candidates = collect_candidates(args)
    total = sum(c.size for c in candidates)

    mode = "APLICANDO" if args.apply else "DRY-RUN"
    print(f"[{mode}] {len(candidates)} itens candidatos | economia estimada: {human_size(total)}")
    for c in candidates:
        print(f"- {c.kind:4s} {human_size(c.size):>10s}  {relpath(root, c.path)}  ({c.reason})")

    if not args.apply:
        print("\nNada foi removido. Para remover, rode novamente com --apply.")
        print("Recomendado: python scripts/cleanup_generated_artifacts.py --profile lean --apply")
        return 0

    for c in candidates:
        remove_candidate(c)
    print(f"\nRemocao concluida. Itens processados: {len(candidates)} | economia estimada: {human_size(total)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
