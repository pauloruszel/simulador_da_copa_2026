import json
from pathlib import Path

from backend.report_store import ReportStore


def test_report_store_builds_dashboard_summary():
    output = Path("output")
    (output / "probabilities.json").write_text(
        json.dumps(
            {
                "meta": {"simulations": 1000, "seed": 42},
                "teams": [
                    {"team": "Brazil", "group": "C", "winner_pct": 8.0, "final_pct": 15.0, "semifinal_pct": 30.0},
                    {"team": "Argentina", "group": "J", "winner_pct": 20.0, "final_pct": 31.0, "semifinal_pct": 45.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = ReportStore(output).dashboard_summary()

    assert summary["meta"]["simulations"] == 1000
    assert summary["top_title"][0]["team"] == "Argentina"
    assert "probabilities.json" in summary["report_files"]
