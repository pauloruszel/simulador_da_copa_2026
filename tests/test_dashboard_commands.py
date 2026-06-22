from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

import backend.api as dashboard_api
from backend.command_runner import CommandRequest, _args_for, run_dashboard_command


def test_dashboard_command_args_are_allowlisted():
    assert _args_for(CommandRequest("source_health_check")) == ["--source-health-check"]
    assert _args_for(CommandRequest("workflow_team", team="Brasil", simulations=1000, seed=7)) == [
        "--workflow",
        "full",
        "--team",
        "Brasil",
        "--global-report",
        "--simulations",
        "1000",
        "--seed",
        "7",
    ]
    assert _args_for(CommandRequest("fetch_market_odds")) == ["--fetch-market-odds-only"]
    assert _args_for(CommandRequest("import_market_odds")) == ["--import-market-odds"]
    assert _args_for(CommandRequest("market_comparison")) == ["--market-comparison"]
    assert _args_for(CommandRequest("odds_fetch_periodic")) == ["--fetch-market-odds-only", "--market-odds-runs", "4", "--market-odds-interval-minutes", "30"]
    assert _args_for(CommandRequest("odds_workflow", simulations=1000, seed=7)) == [
        "--workflow",
        "odds",
        "--all-teams",
        "--market-mode",
        "title_anchor",
        "--simulations",
        "1000",
        "--seed",
        "7",
    ]


def test_dashboard_command_rejects_unknown_action():
    with pytest.raises(ValueError):
        _args_for(CommandRequest("rm_everything"))


def test_dashboard_command_writes_latest_log(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(*args, **kwargs):
        return FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_dashboard_command(CommandRequest("source_health_check"))

    assert result["ok"] is True
    assert result["stdout"] == "ok"


def test_dashboard_command_api_contract(monkeypatch):
    def fake_run(request):
        return {"ok": True, "action": request.action, "stdout": "ok", "stderr": "", "returncode": 0}

    monkeypatch.setattr(dashboard_api, "run_dashboard_command", fake_run)
    client = TestClient(dashboard_api.app)

    actions = client.get("/api/commands")
    result = client.post("/api/commands/run", json={"action": "source_health_check"})

    assert actions.status_code == 200
    assert {item["action"] for item in actions.json()["actions"]} >= {"fetch_market_odds", "market_comparison", "odds_workflow"}
    assert result.status_code == 200
    assert result.json()["action"] == "source_health_check"
