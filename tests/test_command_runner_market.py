"""
Testes para os novos botões de market_mode no command_runner.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.command_runner import CommandRequest, available_actions, _args_for


def test_odds_workflow_anchor_args():
    req = CommandRequest(action="odds_workflow_anchor", simulations=200000, seed=42)
    args = _args_for(req)
    assert "--workflow" in args
    assert "odds" in args
    assert "--market-mode" in args
    assert "title_anchor" in args
    assert "--all-teams" in args


def test_odds_workflow_benchmark_args():
    req = CommandRequest(action="odds_workflow_benchmark", simulations=200000, seed=42)
    args = _args_for(req)
    assert "--market-mode" in args
    assert "benchmark" in args


def test_odds_workflow_experimental_args():
    req = CommandRequest(action="odds_workflow_experimental")
    args = _args_for(req)
    assert "--market-mode" in args
    assert "rating_adjustment" in args


def test_odds_workflow_legacy_uses_title_anchor():
    req = CommandRequest(action="odds_workflow")
    args = _args_for(req)
    assert "--market-mode" in args
    assert "title_anchor" in args


def test_odds_workflow_legacy_respects_market_mode():
    req = CommandRequest(action="odds_workflow", market_mode="benchmark")
    args = _args_for(req)
    assert "--market-mode" in args
    assert "benchmark" in args


def test_available_actions_contains_new_buttons():
    actions = {item["action"] for item in available_actions()}
    assert "odds_workflow_anchor" in actions
    assert "odds_workflow_benchmark" in actions
    assert "odds_workflow_experimental" in actions
    assert "market_comparison" in actions


def test_invalid_action_raises():
    req = CommandRequest(action="invalid_action_xyz")
    try:
        _args_for(req)
        assert False, "Deveria ter lançado ValueError"
    except ValueError:
        pass
