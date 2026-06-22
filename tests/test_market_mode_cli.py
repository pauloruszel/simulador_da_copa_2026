"""
Testes para --market-mode no CLI e comportamento padrão do workflow odds.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.cli_args import parse_args


def test_market_mode_benchmark():
    args = parse_args(["--workflow", "odds", "--all-teams", "--market-mode", "benchmark"])
    assert args.market_mode == "benchmark"


def test_market_mode_title_anchor():
    args = parse_args(["--workflow", "odds", "--all-teams", "--market-mode", "title_anchor"])
    assert args.market_mode == "title_anchor"


def test_market_mode_rating_adjustment():
    args = parse_args(["--workflow", "odds", "--all-teams", "--market-mode", "rating_adjustment"])
    assert args.market_mode == "rating_adjustment"


def test_workflow_odds_without_market_mode_defaults_to_title_anchor():
    args = parse_args(["--workflow", "odds", "--all-teams"])
    assert args.market_mode == "title_anchor"


def test_workflow_full_without_market_mode_stays_none():
    args = parse_args(["--workflow", "full", "--all-teams"])
    # --workflow full não deve forçar market_mode
    assert args.market_mode is None


def test_market_comparison_limit():
    args = parse_args(["--market-comparison", "--market-comparison-limit", "30"])
    assert args.market_comparison_limit == 30


def test_market_comparison_no_limit():
    args = parse_args(["--market-comparison"])
    assert args.market_comparison_limit is None


def test_market_mode_invalid_raises():
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "main.py", "--workflow", "odds", "--market-mode", "invalid_value"],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "invalid" in result.stderr.lower() or "error" in result.stderr.lower() or "choice" in result.stderr.lower()
