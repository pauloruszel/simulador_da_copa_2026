from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models import Match
from src.poisson_model import expected_goals
from src.calibration.team_strength import build_calibrated_ratings


DEFAULT_GROUP_STAGE_CALIBRATION = {
    "enabled": True,
    "draw_floor_group_stage": 0.20,
    "draw_floor_balanced_game": 0.26,
    "favorite_ceiling_group_stage": 0.84,
    "favorite_ceiling_strong_favorite": 0.76,
    "upset_floor_group_stage": 0.06,
    "probability_temperature": 1.05,
    "strong_favorite_rating_gap_threshold": 250,
}


RESULT_KEYS = ("home", "draw", "away")


def brier_score(predicted_probs: dict[str, float], actual_result: str) -> float:
    return sum((predicted_probs[k] - (1.0 if k == actual_result else 0.0)) ** 2 for k in RESULT_KEYS)


def brier_score_mean_class(predicted_probs: dict[str, float], actual_result: str) -> float:
    return brier_score(predicted_probs, actual_result) / 3


def log_loss_score(predicted_probs: dict[str, float], actual_result: str) -> float:
    return -math.log(max(1e-12, predicted_probs[actual_result]))


def match_result(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if home_score < away_score:
        return "away"
    return "draw"


def predict_match_1x2(home: str, away: str, ratings: dict[str, int], model_config: dict[str, Any]) -> dict[str, float]:
    raw = _predict_match_1x2_raw(home, away, ratings, model_config)
    rating_gap = ratings[home] - ratings[away]
    return calibrate_group_stage_probabilities(
        raw["home"],
        raw["draw"],
        raw["away"],
        rating_gap=rating_gap,
        game_type=_game_type(home, away, ratings),
        model_config=model_config,
    )


def calibrate_group_stage_probabilities(
    home_prob: float,
    draw_prob: float,
    away_prob: float,
    rating_gap: int | float,
    game_type: str,
    model_config: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Post-process 1X2 group-stage probabilities.

    The calibration is intentionally conservative: it raises draw/upset floors and
    caps overconfident favorites without changing the relative ranking more than
    necessary. This is used for group-stage 1X2 backtests and tuned probability
    reports, not for accepting final/live scores from data providers.
    """
    cfg = _group_stage_calibration_config(model_config)
    probs = _normalize_probs({"home": home_prob, "draw": draw_prob, "away": away_prob})
    if not cfg.get("enabled", True):
        return probs

    probs = _temperature_scale(probs, float(cfg.get("probability_temperature", 1.0)))

    favorite = "home" if probs["home"] >= probs["away"] else "away"
    underdog = "away" if favorite == "home" else "home"
    strong_threshold = abs(float(cfg.get("strong_favorite_rating_gap_threshold", 250)))
    is_strong = game_type == "favorito forte" or abs(float(rating_gap)) >= strong_threshold

    generic_ceiling = float(cfg.get("favorite_ceiling_group_stage", 1.0))
    strong_ceiling = float(cfg.get("favorite_ceiling_strong_favorite", generic_ceiling))
    favorite_ceiling = min(generic_ceiling, strong_ceiling) if is_strong else generic_ceiling
    favorite_ceiling = min(max(favorite_ceiling, 0.34), 0.98)

    if probs[favorite] > favorite_ceiling:
        excess = probs[favorite] - favorite_ceiling
        probs[favorite] = favorite_ceiling
        other_total = probs["draw"] + probs[underdog]
        if other_total <= 0:
            probs["draw"] += excess * 0.65
            probs[underdog] += excess * 0.35
        else:
            probs["draw"] += excess * (probs["draw"] / other_total)
            probs[underdog] += excess * (probs[underdog] / other_total)

    upset_floor = float(cfg.get("upset_floor_group_stage", 0.0))
    if upset_floor > 0:
        probs = _raise_floor(probs, underdog, upset_floor, preferred_donors=[favorite, "draw"])

    draw_floor = float(cfg.get("draw_floor_group_stage", 0.0))
    if game_type == "jogo equilibrado":
        draw_floor = max(draw_floor, float(cfg.get("draw_floor_balanced_game", draw_floor)))
    if draw_floor > 0:
        probs = _raise_floor(probs, "draw", draw_floor, preferred_donors=[favorite, underdog])

    if probs[favorite] > favorite_ceiling:
        excess = probs[favorite] - favorite_ceiling
        probs[favorite] = favorite_ceiling
        probs["draw"] += excess * 0.65
        probs[underdog] += excess * 0.35

    return _normalize_probs(probs)


def evaluate_finished_matches(
    matches: list[Match],
    ratings: dict[str, int],
    model_config: dict[str, Any],
    probability_source: str = "model",
    calibrate_ratings: bool = False,
) -> dict[str, Any]:
    rows = []
    finished_matches = [
        match for match in matches
        if match.status == "finished" and match.home_score is not None and match.away_score is not None
    ]
    for index, match in enumerate(finished_matches):
        if match.status != "finished" or match.home_score is None or match.away_score is None:
            continue
        eval_ratings = _walk_forward_ratings(match, index, finished_matches, ratings, model_config) if calibrate_ratings else ratings
        raw_probs = _predict_match_1x2_raw(match.home, match.away, eval_ratings, model_config)
        probs = calibrate_group_stage_probabilities(
            raw_probs["home"], raw_probs["draw"], raw_probs["away"],
            rating_gap=eval_ratings[match.home] - eval_ratings[match.away],
            game_type=_game_type(match.home, match.away, eval_ratings),
            model_config=model_config,
        )
        actual = match_result(match.home_score, match.away_score)
        favorite = max(probs, key=probs.get)
        row = {
            "match_id": match.id,
            "group": match.group,
            "home": match.home,
            "away": match.away,
            "score": f"{match.home_score}-{match.away_score}",
            "predicted": favorite,
            "actual": actual,
            "home_prob": probs["home"],
            "draw_prob": probs["draw"],
            "away_prob": probs["away"],
            "raw_home_prob": raw_probs["home"],
            "raw_draw_prob": raw_probs["draw"],
            "raw_away_prob": raw_probs["away"],
            "brier": brier_score(probs, actual),
            "brier_mean_class": brier_score_mean_class(probs, actual),
            "log_loss": log_loss_score(probs, actual),
            "raw_brier": brier_score(raw_probs, actual),
            "raw_log_loss": log_loss_score(raw_probs, actual),
            "favorite_correct": favorite == actual,
            "game_type": _game_type(match.home, match.away, eval_ratings),
            "result_type": _result_type(favorite, actual),
            "probability_source": probability_source,
        }
        rows.append(row)
    if not rows:
        return {"matches_evaluated": 0, "rows": [], "brier_mean": None, "log_loss_mean": None, "favorite_accuracy": None}
    return {
        "matches_evaluated": len(rows),
        "rows": rows,
        "brier_mean": sum(r["brier"] for r in rows) / len(rows),
        "log_loss_mean": sum(r["log_loss"] for r in rows) / len(rows),
        "raw_brier_mean": sum(r["raw_brier"] for r in rows) / len(rows),
        "raw_log_loss_mean": sum(r["raw_log_loss"] for r in rows) / len(rows),
        "favorite_accuracy": 100 * sum(r["favorite_correct"] for r in rows) / len(rows),
        "by_category": _category_summary(rows),
        "calibration_summary": _calibration_summary(rows),
        "top_errors": sorted(rows, key=lambda r: r["brier"], reverse=True)[:10],
        "recommendations": _automatic_recommendations(rows),
        "baselines": {
            "uniform": _evaluate_baseline(matches, ratings, model_config, "uniform"),
            "rating": _evaluate_baseline(matches, ratings, model_config, "rating"),
        },
        "brier_definition": "multiclass_sum_over_home_draw_away",
    }


def write_backtest_report(result: dict[str, Any], output_dir: str | Path = "output") -> None:
    out = Path(output_dir)
    out.mkdir(exist_ok=True)
    fields = [
        "match_id", "group", "home", "away", "score", "home_prob", "draw_prob", "away_prob",
        "raw_home_prob", "raw_draw_prob", "raw_away_prob", "predicted", "actual", "brier",
        "brier_mean_class", "log_loss", "raw_brier", "raw_log_loss", "favorite_correct",
        "game_type", "result_type", "probability_source",
    ]
    with (out / "backtest_results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(result["rows"])

    error_fields = [
        "match_id", "group", "home", "away", "score", "actual", "predicted", "brier", "log_loss",
        "home_prob", "draw_prob", "away_prob", "raw_brier", "raw_log_loss", "game_type", "result_type",
    ]
    with (out / "backtest_errors_top.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=error_fields)
        writer.writeheader()
        for row in result.get("top_errors", []):
            writer.writerow({key: row.get(key) for key in error_fields})

    lines = [
        "Backtest",
        f"Jogos avaliados: {result['matches_evaluated']}",
        "Calibracao: walk-forward; cada jogo usa apenas ratings calibrados com jogos anteriores.",
        "Brier Score: soma multiclasses em home/draw/away; brier_mean_class = Brier/3.",
        f"Brier Score medio: {result['brier_mean']:.3f}" if result["brier_mean"] is not None else "Brier Score medio: n/a",
        f"Log Loss medio: {result['log_loss_mean']:.3f}" if result["log_loss_mean"] is not None else "Log Loss medio: n/a",
        f"Acuracia do favorito: {result['favorite_accuracy']:.1f}%" if result["favorite_accuracy"] is not None else "Acuracia do favorito: n/a",
        "",
        "Comparacao antes/depois da calibracao de probabilidades:",
    ]
    if result.get("raw_brier_mean") is not None:
        delta_brier = result["raw_brier_mean"] - result["brier_mean"]
        delta_log = result["raw_log_loss_mean"] - result["log_loss_mean"]
        lines.append(f"- antes: Brier {result['raw_brier_mean']:.3f}, Log Loss {result['raw_log_loss_mean']:.3f}")
        lines.append(f"- depois: Brier {result['brier_mean']:.3f}, Log Loss {result['log_loss_mean']:.3f}")
        lines.append(f"- ganho: Brier {delta_brier:+.3f}, Log Loss {delta_log:+.3f}")
    else:
        lines.append("- n/a")
    lines.append("")
    lines.append("Baselines:")
    for name, baseline in result.get("baselines", {}).items():
        lines.append(
            f"- {name}: Brier {baseline['brier_mean']:.3f}, Log Loss {baseline['log_loss_mean']:.3f}, "
            f"Acuracia {baseline['favorite_accuracy']:.1f}%"
        )
    lines += ["", "Analise por categoria:"]
    for category, values in result.get("by_category", {}).items():
        lines.append(
            f"- {category}: jogos {values['matches']}, Brier {values['brier_mean']:.3f}, "
            f"Log Loss {values['log_loss_mean']:.3f}, Acuracia {values['favorite_accuracy']:.1f}%"
        )
    lines += ["", "Calibracao por empate e favorito forte:"]
    for category, values in result.get("calibration_summary", {}).items():
        lines.append(
            f"- {category}: jogos {values['matches']}, Brier antes {values['raw_brier_mean']:.3f}, "
            f"Brier depois {values['brier_mean']:.3f}, ganho {values['brier_improvement']:+.3f}, "
            f"LogLoss antes {values['raw_log_loss_mean']:.3f}, LogLoss depois {values['log_loss_mean']:.3f}"
        )
    lines += ["", "Top 10 maiores erros por Brier:"]
    for row in result.get("top_errors", []):
        lines.append(
            f"- {row['match_id']} {row['home']} x {row['away']} {row['score']}: "
            f"pred={row['predicted']}, real={row['actual']}, Brier={row['brier']:.3f}, LogLoss={row['log_loss']:.3f}"
        )
    lines += ["", "Recomendacoes automaticas:"]
    for recommendation in result.get("recommendations", []):
        lines.append(f"- {recommendation}")
    (out / "backtest_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def tune_weights_grid(matches: list[Match], ratings: dict[str, int], base_config: dict[str, Any]) -> dict[str, Any]:
    best = None
    candidates = []
    baseline = evaluate_finished_matches(matches, ratings, base_config, "model", calibrate_ratings=True)

    old_grid_best_config = None
    for form_weight in (0.05, 0.15, 0.25, 0.35):
        for goal_weight in (4, 6, 8):
            for draw_factor in (0.95, 1.05, 1.15):
                for scale in (0.0018, 0.0022, 0.0026):
                    cfg = json.loads(json.dumps(base_config))
                    cfg.setdefault("rating_model", {})["tournament_form_weight"] = form_weight
                    cfg.setdefault("form_adjustment", {})["goal_difference_weight"] = goal_weight
                    cfg.setdefault("poisson", {})["draw_correction_factor"] = draw_factor
                    cfg.setdefault("poisson", {})["goal_advantage_scale"] = scale
                    candidate = _evaluate_candidate(matches, ratings, cfg, {
                        "form_weight": form_weight,
                        "goal_difference_weight": goal_weight,
                        "draw_correction_factor": draw_factor,
                        "goal_advantage_scale": scale,
                    })
                    candidates.append(candidate)
                    if best is None or candidate["brier_mean"] < best["brier_mean"]:
                        best = candidate
                        old_grid_best_config = cfg

    calibration_seed = old_grid_best_config or base_config
    for draw_floor in (0.18, 0.20, 0.22, 0.24):
        for balanced_floor in (0.24, 0.26, 0.28):
            for ceiling in (0.72, 0.76, 0.80, 0.84):
                for temperature in (1.0, 1.05, 1.10, 1.15):
                    cfg = json.loads(json.dumps(calibration_seed))
                    gsc = cfg.setdefault("group_stage_calibration", {})
                    gsc["enabled"] = True
                    gsc["draw_floor_group_stage"] = draw_floor
                    gsc["draw_floor_balanced_game"] = balanced_floor
                    gsc["favorite_ceiling_group_stage"] = ceiling
                    gsc.setdefault("favorite_ceiling_strong_favorite", min(ceiling, 0.76))
                    gsc.setdefault("upset_floor_group_stage", 0.06)
                    gsc["probability_temperature"] = temperature
                    gsc.setdefault("strong_favorite_rating_gap_threshold", 250)
                    candidate = _evaluate_candidate(matches, ratings, cfg, {
                        "draw_floor_group_stage": draw_floor,
                        "draw_floor_balanced_game": balanced_floor,
                        "favorite_ceiling_group_stage": ceiling,
                        "probability_temperature": temperature,
                    })
                    candidates.append(candidate)
                    if best is None or candidate["brier_mean"] < best["brier_mean"]:
                        best = candidate
    return {
        "baseline": {
            "brier_mean": baseline["brier_mean"],
            "log_loss_mean": baseline["log_loss_mean"],
            "config": base_config,
        },
        "best": best,
        "tested": len(candidates),
        "improvement": (baseline["brier_mean"] - best["brier_mean"]) if baseline["brier_mean"] is not None else 0,
        "candidates": candidates,
    }


def _evaluate_candidate(matches: list[Match], ratings: dict[str, int], cfg: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    result = evaluate_finished_matches(matches, ratings, cfg, "model", calibrate_ratings=True)
    score = result["brier_mean"] if result["brier_mean"] is not None else 999
    complete_params = _candidate_params_from_config(cfg)
    complete_params.update(params)
    return {
        **complete_params,
        "brier_mean": score,
        "log_loss_mean": result["log_loss_mean"],
        "config": cfg,
    }


def _candidate_params_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    poisson = cfg.get("poisson", {})
    rating_model = cfg.get("rating_model", {})
    form = cfg.get("form_adjustment", {})
    gsc = _group_stage_calibration_config(cfg)
    return {
        "form_weight": rating_model.get("tournament_form_weight"),
        "goal_difference_weight": form.get("goal_difference_weight"),
        "draw_correction_factor": poisson.get("draw_correction_factor"),
        "goal_advantage_scale": poisson.get("goal_advantage_scale"),
        "draw_floor_group_stage": gsc.get("draw_floor_group_stage"),
        "draw_floor_balanced_game": gsc.get("draw_floor_balanced_game"),
        "favorite_ceiling_group_stage": gsc.get("favorite_ceiling_group_stage"),
        "favorite_ceiling_strong_favorite": gsc.get("favorite_ceiling_strong_favorite"),
        "upset_floor_group_stage": gsc.get("upset_floor_group_stage"),
        "probability_temperature": gsc.get("probability_temperature"),
    }


def _walk_forward_ratings(
    target_match: Match,
    target_index: int,
    finished_matches: list[Match],
    base_ratings: dict[str, int],
    model_config: dict[str, Any],
) -> dict[str, int]:
    previous = [
        match for index, match in enumerate(finished_matches)
        if index != target_index and _is_before(match, target_match, index, target_index)
    ]
    if not previous:
        return base_ratings
    return build_calibrated_ratings(base_ratings, previous, model_config)["ratings"]


def _is_before(match: Match, target_match: Match, match_index: int, target_index: int) -> bool:
    match_date = _parse_match_date(match.date)
    target_date = _parse_match_date(target_match.date)
    if match_date is not None and target_date is not None:
        return match_date < target_date
    return match_index < target_index


def _parse_match_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def uniform_baseline_probs() -> dict[str, float]:
    return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}


def _poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _predict_match_1x2_raw(home: str, away: str, ratings: dict[str, int], model_config: dict[str, Any]) -> dict[str, float]:
    poisson = model_config.get("poisson", {})
    eh, ea = expected_goals(
        ratings[home],
        ratings[away],
        poisson.get("base_goals", 1.25),
        poisson.get("goal_advantage_scale", 0.0022),
        poisson.get("min_expected_goals", 0.20),
        poisson.get("max_expected_goals", 3.20),
    )
    probs = {"home": 0.0, "draw": 0.0, "away": 0.0}
    max_goals = 8
    for hg in range(max_goals + 1):
        hp = _poisson_pmf(hg, eh)
        for ag in range(max_goals + 1):
            p = hp * _poisson_pmf(ag, ea)
            probs[match_result(hg, ag)] += p
    probs = _normalize_probs(probs)
    draw_factor = poisson.get("draw_correction_factor", 1.0)
    if draw_factor != 1.0:
        probs["draw"] *= draw_factor
        probs = _normalize_probs(probs)
    return probs


def _group_stage_calibration_config(model_config: dict[str, Any] | None) -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_GROUP_STAGE_CALIBRATION))
    if model_config:
        cfg.update(model_config.get("group_stage_calibration", {}))
    return cfg


def _normalize_probs(probs: dict[str, float]) -> dict[str, float]:
    clean = {key: max(0.0, float(probs.get(key, 0.0))) for key in RESULT_KEYS}
    total = sum(clean.values())
    if total <= 0:
        return uniform_baseline_probs()
    return {key: clean[key] / total for key in RESULT_KEYS}


def _temperature_scale(probs: dict[str, float], temperature: float) -> dict[str, float]:
    if temperature <= 0 or abs(temperature - 1.0) < 1e-12:
        return _normalize_probs(probs)
    scaled = {key: max(1e-12, probs[key]) ** (1.0 / temperature) for key in RESULT_KEYS}
    return _normalize_probs(scaled)


def _raise_floor(
    probs: dict[str, float], target: str, floor: float, preferred_donors: list[str] | None = None
) -> dict[str, float]:
    floor = min(max(floor, 0.0), 0.95)
    if probs[target] >= floor:
        return probs
    needed = floor - probs[target]
    donors = preferred_donors or [key for key in RESULT_KEYS if key != target]
    for donor in donors:
        if donor == target or needed <= 1e-12:
            continue
        available = max(0.0, probs[donor] - 0.01)
        taken = min(available, needed)
        probs[donor] -= taken
        probs[target] += taken
        needed -= taken
    if needed > 1e-12:
        for donor in RESULT_KEYS:
            if donor == target or needed <= 1e-12:
                continue
            available = max(0.0, probs[donor])
            taken = min(available, needed)
            probs[donor] -= taken
            probs[target] += taken
            needed -= taken
    return _normalize_probs(probs)


def _game_type(home: str, away: str, ratings: dict[str, int]) -> str:
    diff = abs(ratings[home] - ratings[away])
    if diff >= 250:
        return "favorito forte"
    if diff <= 80:
        return "jogo equilibrado"
    return "favorito moderado"


def _evaluate_baseline(matches: list[Match], ratings: dict[str, int], model_config: dict[str, Any], kind: str) -> dict[str, Any]:
    rows = []
    for match in matches:
        if match.status != "finished" or match.home_score is None or match.away_score is None:
            continue
        probs = uniform_baseline_probs() if kind == "uniform" else _predict_match_1x2_raw(match.home, match.away, ratings, model_config)
        actual = match_result(match.home_score, match.away_score)
        favorite = max(probs, key=probs.get)
        rows.append({
            "brier": brier_score(probs, actual),
            "log_loss": log_loss_score(probs, actual),
            "favorite_correct": favorite == actual,
        })
    return {
        "brier_mean": sum(r["brier"] for r in rows) / len(rows) if rows else None,
        "log_loss_mean": sum(r["log_loss"] for r in rows) / len(rows) if rows else None,
        "favorite_accuracy": 100 * sum(r["favorite_correct"] for r in rows) / len(rows) if rows else None,
    }


def _category_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    categories = {}
    for key in ("game_type", "result_type", "group"):
        for value in sorted({row[key] for row in rows}):
            selected = [row for row in rows if row[key] == value]
            categories[f"{key}:{value}"] = _summarize_rows(selected)
    return categories


def _calibration_summary(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    selected_categories = {
        "result_type:empate": [row for row in rows if row["result_type"] == "empate"],
        "result_type:zebra": [row for row in rows if row["result_type"] == "zebra"],
        "game_type:favorito forte": [row for row in rows if row["game_type"] == "favorito forte"],
        "game_type:jogo equilibrado": [row for row in rows if row["game_type"] == "jogo equilibrado"],
    }
    return {name: _summarize_calibration(selected) for name, selected in selected_categories.items() if selected}


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "matches": len(rows),
        "brier_mean": sum(row["brier"] for row in rows) / len(rows),
        "log_loss_mean": sum(row["log_loss"] for row in rows) / len(rows),
        "favorite_accuracy": 100 * sum(row["favorite_correct"] for row in rows) / len(rows),
    }


def _summarize_calibration(rows: list[dict[str, Any]]) -> dict[str, float]:
    brier = sum(row["brier"] for row in rows) / len(rows)
    raw_brier = sum(row["raw_brier"] for row in rows) / len(rows)
    log_loss = sum(row["log_loss"] for row in rows) / len(rows)
    raw_log_loss = sum(row["raw_log_loss"] for row in rows) / len(rows)
    return {
        "matches": len(rows),
        "brier_mean": brier,
        "raw_brier_mean": raw_brier,
        "brier_improvement": raw_brier - brier,
        "log_loss_mean": log_loss,
        "raw_log_loss_mean": raw_log_loss,
    }


def _automatic_recommendations(rows: list[dict[str, Any]]) -> list[str]:
    recommendations = []
    by_category = _category_summary(rows)
    empate = by_category.get("result_type:empate")
    zebra = by_category.get("result_type:zebra")
    forte = by_category.get("game_type:favorito forte")
    if empate and empate["brier_mean"] > 0.80:
        recommendations.append("Empates ainda pesam no erro; considerar draw_floor_group_stage/draw_floor_balanced_game mais altos.")
    if zebra and zebra["brier_mean"] > 0.90:
        recommendations.append("Zebras ainda estão caras; considerar upset_floor_group_stage maior e teto de favorito menor.")
    if forte and forte["favorite_accuracy"] < 60:
        recommendations.append("Favoritos fortes seguem superconfiantes; reduzir favorite_ceiling_strong_favorite ou aumentar temperature.")
    if not recommendations:
        recommendations.append("Calibracao atual nao aponta gargalo dominante; manter monitoramento com mais jogos.")
    return recommendations


def _result_type(predicted: str, actual: str) -> str:
    if actual == "draw":
        return "empate"
    if predicted == actual:
        return "favorito venceu"
    return "zebra"
