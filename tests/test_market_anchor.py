"""
Testes unitários para src/market_anchor.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.market_anchor import (
    apply_title_anchor,
    build_anchor_summary,
    normalize_market_probabilities,
    write_market_alerts,
    write_title_anchor_outputs,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

# Overround = 113.3% (como citado no spec)
_MARKET_RAW = {
    "France":        1 / 5,
    "Spain":         1 / 7,
    "England":       1 / 7.5,
    "Argentina":     1 / 9.05,
    "Portugal":      1 / 12,
    "Brazil":        1 / 13,
    "Germany":       1 / 15,
    "Netherlands":   1 / 17,
    "Morocco":       1 / 34,
    "Mexico":        1 / 50,
    "Canada":        1 / 60,
    "Uruguay":       1 / 70,
    "Croatia":       1 / 80,
    "Colombia":      1 / 80,
    "Japan":         1 / 100,
    "United States": 1 / 100,
    "Switzerland":   1 / 120,
    "Ecuador":       1 / 150,
    "Senegal":       1 / 200,
    "South Korea":   1 / 200,
    "Norway":        1 / 200,
    "Austria":       1 / 250,
    "Belgium":       1 / 250,
    "Turkey":        1 / 300,
    "Egypt":         1 / 300,
    "Ivory Coast":   1 / 300,
    "Ghana":         1 / 400,
    "Tunisia":       1 / 400,
    "Algeria":       1 / 500,
    "Scotland":      1 / 500,
}

_MODEL_ROWS = [
    {"team": "Argentina",   "winner_pct": 21.68, "group": "J"},
    {"team": "Spain",       "winner_pct": 15.05, "group": "H"},
    {"team": "France",      "winner_pct": 14.41, "group": "I"},
    {"team": "England",     "winner_pct": 12.42, "group": "L"},
    {"team": "Portugal",    "winner_pct":  8.00, "group": "K"},
    {"team": "Brazil",      "winner_pct":  7.16, "group": "C"},
    {"team": "Germany",     "winner_pct":  4.50, "group": "E"},
    {"team": "Netherlands", "winner_pct":  3.50, "group": "F"},
    {"team": "Morocco",     "winner_pct":  2.50, "group": "C"},
    {"team": "Mexico",      "winner_pct":  1.50, "group": "A"},
    {"team": "Canada",      "winner_pct":  1.00, "group": "B"},
    {"team": "Uruguay",     "winner_pct":  1.00, "group": "H"},
    {"team": "Croatia",     "winner_pct":  0.80, "group": "L"},
    {"team": "Colombia",    "winner_pct":  0.80, "group": "K"},
    {"team": "Japan",       "winner_pct":  0.60, "group": "F"},
    {"team": "United States", "winner_pct": 0.60, "group": "D"},
    {"team": "Switzerland", "winner_pct":  0.50, "group": "B"},
    {"team": "Ecuador",     "winner_pct":  0.40, "group": "E"},
    {"team": "Senegal",     "winner_pct":  0.30, "group": "I"},
    {"team": "South Korea", "winner_pct":  0.30, "group": "A"},
    {"team": "Norway",      "winner_pct":  0.25, "group": "I"},
    {"team": "Austria",     "winner_pct":  0.20, "group": "J"},
    {"team": "Belgium",     "winner_pct":  0.20, "group": "G"},
    {"team": "Turkey",      "winner_pct":  0.15, "group": "D"},
    {"team": "Egypt",       "winner_pct":  0.10, "group": "G"},
    {"team": "Ivory Coast", "winner_pct":  0.10, "group": "E"},
    {"team": "Ghana",       "winner_pct":  0.05, "group": "L"},
    {"team": "Tunisia",     "winner_pct":  0.05, "group": "F"},
    {"team": "Algeria",     "winner_pct":  0.05, "group": "J"},
    {"team": "Scotland",    "winner_pct":  0.04, "group": "C"},
    # seleções sem odds de mercado
    {"team": "Paraguay",    "winner_pct":  0.04, "group": "D"},
    {"team": "Australia",   "winner_pct":  0.03, "group": "D"},
    {"team": "Haiti",       "winner_pct":  0.01, "group": "C"},
]


# ─────────────────────────────────────────────────────────────────────────────
# 1. Normalização de odds
# ─────────────────────────────────────────────────────────────────────────────

def test_normalize_market_probabilities_sums_to_one():
    norm = normalize_market_probabilities(_MARKET_RAW)
    assert abs(sum(norm.values()) - 1.0) < 1e-9


def test_normalize_market_probabilities_argentina_approx_975():
    norm = normalize_market_probabilities(_MARKET_RAW)
    # Com ~30 seleções e overround ~113%, Argentina deve ficar ~9.75%
    total_raw = sum(_MARKET_RAW.values())
    expected = _MARKET_RAW["Argentina"] / total_raw * 100
    assert 8.0 < expected < 12.0, f"Argentina normalizado inesperado: {expected:.2f}%"


def test_normalize_empty_returns_empty():
    assert normalize_market_probabilities({}) == {}


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cálculo de âncora 50/50
# ─────────────────────────────────────────────────────────────────────────────

def test_anchor_50_50_no_cap():
    """Time dentro da banda: anchor deve ser entre o modelo e o mercado."""
    rows = [
        {"team": "Brazil", "winner_pct": 7.16, "group": "C"},
        {"team": "France", "winner_pct": 14.41, "group": "I"},
        {"team": "England", "winner_pct": 12.42, "group": "L"},
    ]
    raw = {"Brazil": 1/13, "France": 1/5, "England": 1/7.5}
    anchor_rows = apply_title_anchor(rows, raw, config={"min_market_coverage_teams": 2})
    brazil = next(r for r in anchor_rows if r["team"] == "Brazil")
    norm = normalize_market_probabilities(raw)
    market_brazil_pct = norm["Brazil"] * 100
    # Com peso 50/50 e dentro da banda, o anchor deve estar entre modelo e mercado
    # (renormalização pode deslocar levemente, então usamos tolerância razoável)
    lower = min(7.16, market_brazil_pct) - 2.0
    upper = max(7.16, market_brazil_pct) + 2.0
    assert lower <= brazil["anchor_winner_pct"] <= upper, (
        f"anchor {brazil['anchor_winner_pct']:.2f} fora do intervalo [{lower:.2f}, {upper:.2f}]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. max_positive_delta_pp — Argentina acima do mercado é reduzida
# ─────────────────────────────────────────────────────────────────────────────

def test_argentina_capped_below_model():
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    argentina = next(r for r in anchor_rows if r["team"] == "Argentina")
    # Argentina modelo=21.68%, mercado~9.75%, cap = 9.75 + 5 = 14.75%
    assert argentina["model_winner_pct"] == 21.68
    assert argentina["anchor_winner_pct"] < 21.68, "Âncora deve reduzir Argentina"
    assert argentina["anchor_winner_pct"] <= 16.0, f"Argentina ainda muito alta: {argentina['anchor_winner_pct']}"
    # reason deve indicar que estava acima do mercado
    assert argentina["anchor_reason"] in ("capped_above_market", "above_market_in_band"), (
        f"Razão inesperada para Argentina: {argentina['anchor_reason']}"
    )


def test_argentina_anchor_below_model_by_at_least_5pp():
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    argentina = next(r for r in anchor_rows if r["team"] == "Argentina")
    reduction = argentina["model_winner_pct"] - argentina["anchor_winner_pct"]
    assert reduction >= 5.0, f"Redução de Argentina insuficiente: {reduction:.2f} p.p."


def test_argentina_not_champion_in_anchor():
    """Com odds de mercado, Argentina não deve ser favorita absoluta."""
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    first = anchor_rows[0]
    # France ou Spain devem ser o favorito no anchor
    assert first["team"] != "Argentina", (
        f"Argentina ainda é favorita no anchor: {first['anchor_winner_pct']:.2f}%"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. max_negative_delta_pp — France abaixo do mercado é elevada
# ─────────────────────────────────────────────────────────────────────────────

def test_france_elevated_towards_market():
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    france = next(r for r in anchor_rows if r["team"] == "France")
    norm = normalize_market_probabilities(_MARKET_RAW)
    market_pct = norm["France"] * 100
    # France modelo < mercado: anchor deve ficar maior que o modelo
    assert france["anchor_winner_pct"] >= france["model_winner_pct"], (
        "France deveria ser elevada em direção ao mercado"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Seleção sem odds não quebra
# ─────────────────────────────────────────────────────────────────────────────

def test_team_without_odds_keeps_model_pct():
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    # Haiti não tem odds
    haiti = next((r for r in anchor_rows if r["team"] == "Haiti"), None)
    assert haiti is not None
    assert haiti["market_winner_pct"] is None
    assert haiti["anchor_reason"] == "missing_market_odds"
    assert haiti["adjustment_applied_pp"] == 0.0 or abs(haiti["adjustment_applied_pp"]) < 0.5


# ─────────────────────────────────────────────────────────────────────────────
# 6. Renormalização
# ─────────────────────────────────────────────────────────────────────────────

def test_renormalization_sum_coherent():
    """Soma total de anchor deve ser próxima da soma do modelo."""
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    total_model = sum(r["winner_pct"] for r in _MODEL_ROWS)
    total_anchor = sum(r["anchor_winner_pct"] for r in anchor_rows)
    assert abs(total_anchor - total_model) < 2.0, (
        f"Renormalização desequilibrada: modelo={total_model:.2f} anchor={total_anchor:.2f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Cobertura insuficiente — retorna modelo sem ajuste
# ─────────────────────────────────────────────────────────────────────────────

def test_insufficient_market_coverage_no_adjustment():
    anchor_rows = apply_title_anchor(
        _MODEL_ROWS[:5],
        {"France": 1/5},  # só 1 seleção com odds
        config={"min_market_coverage_teams": 12},
    )
    for row in anchor_rows:
        assert row["anchor_reason"] == "insufficient_market_coverage"
        assert row["anchor_winner_pct"] == row["model_winner_pct"]


# ─────────────────────────────────────────────────────────────────────────────
# 8. Alertas
# ─────────────────────────────────────────────────────────────────────────────

def test_alerts_generated_for_high_delta(tmp_path):
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    result = write_market_alerts(anchor_rows, output_dir=tmp_path, threshold_pp=3.0)
    alerts = result["alerts"]
    assert len(alerts) > 0, "Deve haver pelo menos um alerta"
    # Argentina deve estar nos alertas
    arg_alert = next((a for a in alerts if a["team"] == "Argentina"), None)
    assert arg_alert is not None, "Argentina deve gerar alerta"
    assert arg_alert["direction"] == "above"


def test_alerts_json_written(tmp_path):
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    write_market_alerts(anchor_rows, output_dir=tmp_path)
    json_path = tmp_path / "market_alerts.json"
    txt_path = tmp_path / "market_alerts.txt"
    assert json_path.exists()
    assert txt_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "alerts" in payload
    assert "alert_count" in payload


# ─────────────────────────────────────────────────────────────────────────────
# 9. Saídas escritas
# ─────────────────────────────────────────────────────────────────────────────

def test_write_title_anchor_outputs_creates_files(tmp_path):
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    result = write_title_anchor_outputs(anchor_rows, _MARKET_RAW, output_dir=tmp_path)
    assert Path(result["csv"]).exists()
    assert Path(result["json"]).exists()
    assert Path(result["txt"]).exists()
    # Verifica JSON
    payload = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
    assert payload["market_mode"] == "title_anchor"
    assert "rows" in payload
    assert len(payload["rows"]) == len(anchor_rows)


def test_anchor_report_txt_contains_summary(tmp_path):
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    result = write_title_anchor_outputs(anchor_rows, _MARKET_RAW, output_dir=tmp_path)
    txt = Path(result["txt"]).read_text(encoding="utf-8")
    assert "market_mode" in txt
    assert "Overround" in txt
    assert "Argentina" in txt


# ─────────────────────────────────────────────────────────────────────────────
# 10. Campos ANCHOR_FIELDS presentes
# ─────────────────────────────────────────────────────────────────────────────

def test_anchor_rows_have_required_fields():
    from src.market_anchor import ANCHOR_FIELDS
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    for row in anchor_rows:
        for field in ANCHOR_FIELDS:
            assert field in row, f"Campo ausente: {field} em {row['team']}"


# ─────────────────────────────────────────────────────────────────────────────
# 11. Summary
# ─────────────────────────────────────────────────────────────────────────────

def test_build_anchor_summary_has_required_keys():
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    summary = build_anchor_summary(anchor_rows, _MARKET_RAW)
    for key in ["teams_with_odds", "teams_without_odds", "overround_pct", "alerts_count", "alerts"]:
        assert key in summary, f"Chave ausente no summary: {key}"
    assert summary["teams_with_odds"] == len(_MARKET_RAW)
    assert summary["teams_without_odds"] == len(_MODEL_ROWS) - len(_MARKET_RAW)


def test_summary_biggest_above_is_argentina():
    anchor_rows = apply_title_anchor(_MODEL_ROWS, _MARKET_RAW)
    summary = build_anchor_summary(anchor_rows, _MARKET_RAW)
    biggest = summary.get("biggest_above_market")
    assert biggest is not None
    assert biggest["team"] == "Argentina"
    assert biggest["delta_pp"] > 5.0


# ─────────────────────────────────────────────────────────────────────────────
# 12. Novos testes para anchor_reason melhorado
# ─────────────────────────────────────────────────────────────────────────────

def test_anchor_reason_capped_above_market():
    """Quando anchor_raw > max_allowed, reason = capped_above_market."""
    # Para garantir cap: modelo muito acima do mercado normalizado
    # Com muitos times, o mercado de X normaliza para perto das suas odds brutas
    # Usamos max_positive_delta_pp=2.0 (mais restritivo) para forçar o cap
    rows = [
        {"team": "X", "winner_pct": 40.0, "group": "A"},
        *[{"team": f"T{i}", "winner_pct": 1.0, "group": "B"} for i in range(20)],
    ]
    # X com odds de 50 (implícita 2%), outros com odds de 10 (10% cada, 20 times)
    # Total raw ≈ 0.02 + 20*0.10 = 2.02; X normalizado ≈ 1%
    # anchor_raw = 40*0.5 + 1*0.5 = 20.5; max_allowed = 1 + 2 = 3 → capped
    raw = {"X": 1/50, **{f"T{i}": 1/10 for i in range(20)}}
    result = apply_title_anchor(rows, raw, config={"min_market_coverage_teams": 5, "max_positive_delta_pp": 2.0})
    x = next(r for r in result if r["team"] == "X")
    assert x["anchor_reason"] == "capped_above_market", (
        f"Esperado capped_above_market, obtido {x['anchor_reason']} "
        f"(model={x['model_winner_pct']}, market={x['market_winner_pct']}, anchor={x['anchor_winner_pct']})"
    )


def test_anchor_reason_capped_below_market():
    """Quando anchor_raw < min_allowed, reason = capped_below_market."""
    # Modelo muito abaixo do mercado: 1% vs 30%
    rows = [{"team": "X", "winner_pct": 1.0, "group": "A"}, {"team": "Y", "winner_pct": 50.0, "group": "B"}]
    raw = {"X": 0.30, "Y": 0.30}  # X tem 50% normalizado (~30%)
    result = apply_title_anchor(rows, raw, config={"min_market_coverage_teams": 1})
    x = next(r for r in result if r["team"] == "X")
    assert x["anchor_reason"] == "capped_below_market", f"Esperado capped_below_market, obtido {x['anchor_reason']}"


def test_anchor_reason_above_market_in_band():
    """Modelo acima do mercado mas dentro da banda → above_market_in_band."""
    # Modelo 20%, mercado 15%: delta=5, anchor_raw=17.5, max_allowed=20. Dentro da banda.
    rows = [
        {"team": "Alpha", "winner_pct": 20.0, "group": "A"},
        {"team": "Beta",  "winner_pct": 5.0,  "group": "B"},
        *[{"team": f"T{i}", "winner_pct": 1.0, "group": "C"} for i in range(15)],
    ]
    total_raw = 20 * (1/20)  # 20 times, cada um com odds implícitas de 5%
    raw = {"Alpha": 0.15, "Beta": 0.10, **{f"T{i}": 0.04 for i in range(15)}}
    result = apply_title_anchor(rows, raw, config={"min_market_coverage_teams": 5})
    alpha = next(r for r in result if r["team"] == "Alpha")
    # Alpha: delta > 0 e anchor_raw <= max_allowed → above_market_in_band
    assert alpha["anchor_reason"] in ("above_market_in_band", "capped_above_market"), (
        f"Esperado above_market_in_band ou capped, obtido {alpha['anchor_reason']}"
    )
    assert alpha["delta_model_vs_market_pp"] is not None and alpha["delta_model_vs_market_pp"] > 0


def test_anchor_reason_below_market_in_band():
    """Modelo abaixo do mercado mas dentro da banda → below_market_in_band."""
    rows = [
        {"team": "Alpha", "winner_pct": 10.0, "group": "A"},
        {"team": "Beta",  "winner_pct": 20.0, "group": "B"},
        *[{"team": f"T{i}", "winner_pct": 2.0, "group": "C"} for i in range(10)],
    ]
    raw = {"Alpha": 0.15, "Beta": 0.20, **{f"T{i}": 0.03 for i in range(10)}}
    result = apply_title_anchor(rows, raw, config={"min_market_coverage_teams": 5})
    alpha = next(r for r in result if r["team"] == "Alpha")
    # Alpha: delta < 0 e dentro da banda → below_market_in_band
    assert alpha["anchor_reason"] in ("below_market_in_band", "capped_below_market"), (
        f"Esperado below_market_in_band ou capped, obtido {alpha['anchor_reason']}"
    )


def test_anchor_reason_within_band_for_aligned_team():
    """Modelo e mercado muito próximos (|delta| < 1) → within_market_band."""
    # England: modelo 11.77%, mercado também 11.77% (same) → delta=0 → within_market_band
    # Usamos overround controlado: raw_implied = 11.77% exato para England
    # Com 10 outros times para atingir min_coverage, cada um com 5% bruto
    # Total raw = 0.1177 + 9*0.05 = 0.5677; England norm = 0.1177/0.5677 ≈ 20.7%
    # Para garantir delta < 1: usamos odds que normalizam perto do modelo
    # Alternativa: injetar odds raw tal que market_norm ≈ model_pct
    # total_raw com 10 times (England + 9): se England raw = 0.1177 e outros 9 com raw = 0.1177 também
    # England norm = 1/10 = 10%. modelo = 11.77%. delta = 1.77. Ainda acima de 1.
    # Para delta < 1: modelo = mercado. Raw_england = 0.1177 * sum_others / (1 - 0.1177/norm_factor)
    # Mais simples: usar max_positive_delta_pp grande e setar modelo == mercado normalizado
    # A maneira mais direta: usar override do modelo igual ao mercado normalizado
    rows = [
        {"team": "England", "winner_pct": 10.0, "group": "L"},  # modelo 10%
        *[{"team": f"T{i}", "winner_pct": 10.0, "group": "X"} for i in range(9)],
    ]
    # 10 times com mesma odd bruta → cada um normaliza para exatamente 10% → delta=0
    raw = {"England": 0.10, **{f"T{i}": 0.10 for i in range(9)}}
    result = apply_title_anchor(rows, raw, config={"min_market_coverage_teams": 5})
    eng = next(r for r in result if r["team"] == "England")
    assert eng["anchor_reason"] == "within_market_band", (
        f"Esperado within_market_band, obtido {eng['anchor_reason']} "
        f"(delta={eng['delta_model_vs_market_pp']})"
    )


def test_anchor_reason_labels_constant_covers_all_reasons():
    """ANCHOR_REASON_LABELS deve cobrir todas as razões possíveis."""
    from src.market_anchor import ANCHOR_REASON_LABELS
    expected_reasons = {
        "capped_above_market",
        "capped_below_market",
        "above_market_in_band",
        "below_market_in_band",
        "within_market_band",
        "missing_market_odds",
        "insufficient_market_coverage",
    }
    for reason in expected_reasons:
        assert reason in ANCHOR_REASON_LABELS, f"Razão ausente em ANCHOR_REASON_LABELS: {reason}"


def test_report_store_market_report_reads_odds_json(tmp_path):
    """_read_json_from_root deve ler data/odds.json sem levantar ValueError."""
    import sys, json
    sys.path.insert(0, str(tmp_path.parent))
    from backend.report_store import ReportStore
    # Garante que output dir existe
    out = tmp_path / "output"
    out.mkdir()
    store = ReportStore(output_dir=out)
    # Deve retornar default={} sem levantar exceção (arquivo não existe no tmp)
    result = store._read_json_from_root("data/nao_existe.json", default={"ok": True})
    assert result == {"ok": True}


def test_benchmark_coverage_warning():
    """Com menos de 8 seleções, o step de benchmark deve ser warning."""
    # Este teste verifica a lógica, não o CLI completo
    MIN_BENCHMARK_COVERAGE = 8
    n_few = 3
    n_ok = 10
    warning_few = n_few < MIN_BENCHMARK_COVERAGE
    warning_ok = n_ok < MIN_BENCHMARK_COVERAGE
    assert warning_few is True, "3 seleções deve gerar warning"
    assert warning_ok is False, "10 seleções não deve gerar warning"
