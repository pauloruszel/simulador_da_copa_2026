from __future__ import annotations

import csv
import html
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from src.storage.json_store import JsonStore
from src.team_names import resolve_team_name

ODDSCHECKER_WINNER_URL = (
    "https://www.oddschecker.com/br/futebol/internacional/copa-do-mundo-fifa/"
    "copa-do-mundo/vencedor?utm_source=oddschecker&utm_medium=referral&utm_campaign=uksite"
)

TEAM_ALIASES = {
    "França": "France",
    "Espanha": "Spain",
    "Inglaterra": "England",
    "Brasil": "Brazil",
    "Alemanha": "Germany",
    "Holanda": "Netherlands",
    "Noruega": "Norway",
    "Estados Unidos": "United States",
    "Marrocos": "Morocco",
    "Japão": "Japan",
    "México": "Mexico",
    "Colômbia": "Colombia",
    "Bélgica": "Belgium",
    "Suíça": "Switzerland",
    "Uruguai": "Uruguay",
    "Croácia": "Croatia",
    "Áustria": "Austria",
    "Costa do Marfim": "Ivory Coast",
    "Austrália": "Australia",
    "Canadá": "Canada",
    "Suécia": "Sweden",
    "Egito": "Egypt",
    "Equador": "Ecuador",
    "Escócia": "Scotland",
    "Coreia do Sul": "South Korea",
    "Paraguai": "Paraguay",
    "Bósnia Herzegovina": "Bosnia and Herzegovina",
    "Bósnia e Herzegovina": "Bosnia and Herzegovina",
    "Gana": "Ghana",
    "Argélia": "Algeria",
    "Arábia Saudita": "Saudi Arabia",
    "RD Congo": "DR Congo",
    "Congo DR": "DR Congo",
    "Cabo Verde": "Cape Verde",
    "República Tcheca": "Czechia",
    "África do Sul": "South Africa",
    "Catar": "Qatar",
    "Uzbequistão": "Uzbekistan",
    "Iraque": "Iraq",
    "Panamá": "Panama",
    "Jordânia": "Jordan",
    "Haiti": "Haiti",
    "Curaçao": "Curacao",
    "Tunísia": "Tunisia",
    "Nova Zelândia": "New Zealand",
    "Irã": "Iran",
    "Turquia": "Turkey",
    "Portugal": "Portugal",
    "Argentina": "Argentina",
    "Senegal": "Senegal",
}

STOP_MARKERS = {
    "comparar todas as odds",
    "para chegar na final",
    "para chegar nas quartas de final",
    "para chegar na semifinal",
    "to reach last 16",
    "vencedor da chuteira de ouro",
    "apostas em jogadores",
    "outros",
    "melhor seleção sul-americana",
    "top north american team",
    "vencedor pela primeira vez",
}

CSV_FIELDS = [
    "market_type",
    "team",
    "group",
    "odds_decimal",
    "bookmaker",
    "source_url",
    "collected_at",
    "notes",
]


@dataclass(frozen=True)
class MarketOdd:
    market_type: str
    team: str
    odds_decimal: float
    bookmaker: str
    source_url: str
    collected_at: str
    group: str = ""
    notes: str = ""

    def to_csv_row(self) -> dict[str, str]:
        return {
            "market_type": self.market_type,
            "team": self.team,
            "group": self.group,
            "odds_decimal": _format_decimal(self.odds_decimal),
            "bookmaker": self.bookmaker,
            "source_url": self.source_url,
            "collected_at": self.collected_at,
            "notes": self.notes,
        }

    def to_json_record(self) -> dict[str, Any]:
        return {
            "market_type": self.market_type,
            "team": self.team,
            "group": self.group or None,
            "odds_decimal": self.odds_decimal,
            "bookmaker": self.bookmaker,
            "source_url": self.source_url,
            "collected_at": self.collected_at,
            "notes": self.notes,
        }


def fetch_oddschecker_html(url: str = ODDSCHECKER_WINNER_URL, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - CLI scraping of public page.
            raw = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Falha ao buscar Oddschecker: {exc}") from exc
    text = raw.decode("utf-8", errors="replace")
    lowered = text.lower()
    blocked = ["captcha", "cloudflare", "access denied", "forbidden", "verify you are human"]
    if any(marker in lowered for marker in blocked):
        raise RuntimeError("Possivel bloqueio antirobo detectado na pagina de odds.")
    return text


def html_to_lines(page_html: str) -> list[str]:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", "\n", page_html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(div|p|li|span|a|button|h1|h2|h3|td|tr|th)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return [line for line in lines if line]


def scrape_oddschecker_winner(url: str = ODDSCHECKER_WINNER_URL, page_html: str | None = None) -> list[MarketOdd]:
    collected_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    page = page_html if page_html is not None else fetch_oddschecker_html(url)
    lines = html_to_lines(page)
    return parse_winner_market_lines(lines, url, collected_at)


def parse_winner_market_lines(lines: list[str], source_url: str, collected_at: str | None = None) -> list[MarketOdd]:
    collected_at = collected_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    start = _find_winner_start(lines)
    if start is None:
        start = 0
    records: list[MarketOdd] = []
    seen: set[str] = set()
    i = start
    while i < len(lines) - 1:
        line = _clean_noise(lines[i])
        low = line.casefold()
        if records and any(marker in low for marker in STOP_MARKERS):
            break
        team = normalize_team_name(line)
        if team:
            odds = _find_next_decimal(lines, i + 1, max_lookahead=4)
            if odds is not None and team not in seen:
                records.append(
                    MarketOdd(
                        market_type="winner",
                        team=team,
                        odds_decimal=odds,
                        bookmaker="Oddschecker_best",
                        source_url=source_url,
                        collected_at=collected_at,
                        notes="scraped winner market",
                    )
                )
                seen.add(team)
                i += 2
                continue
        i += 1
    return records


def _find_winner_start(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        low = line.casefold()
        if low in {"vencedor", "copa do mundo | vencedor"}:
            return idx + 1
    for idx, line in enumerate(lines):
        if "mercados de vitória" in line.casefold():
            return idx + 1
    return None


def normalize_team_name(value: str) -> str | None:
    clean = _clean_noise(value)
    if not clean or _is_decimal(clean):
        return None
    candidate = TEAM_ALIASES.get(clean, clean)
    if candidate in set(TEAM_ALIASES.values()):
        return candidate
    try:
        return resolve_team_name(candidate)
    except (ValueError, FileNotFoundError):
        return None


def _clean_noise(value: str) -> str:
    value = re.sub(r"\s+logo$", "", value.strip(), flags=re.I)
    value = re.sub(r"\s+bookie logo$", "", value, flags=re.I)
    return value.strip()


def _find_next_decimal(lines: list[str], start: int, max_lookahead: int) -> float | None:
    for j in range(start, min(len(lines), start + max_lookahead)):
        candidate = _parse_decimal(lines[j])
        if candidate is not None and candidate > 1:
            return candidate
    return None


def _parse_decimal(value: str) -> float | None:
    clean = value.strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", clean):
        return None
    try:
        return float(clean)
    except ValueError:
        return None


def _is_decimal(value: str) -> bool:
    return _parse_decimal(value) is not None


def write_market_odds_csv(records: list[MarketOdd], path: str | Path = "data/market_odds_manual.csv") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def read_market_odds_csv(path: str | Path = "data/market_odds_manual.csv") -> list[MarketOdd]:
    target = Path(path)
    if not target.exists():
        return []
    out: list[MarketOdd] = []
    with target.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("market_type") or "").strip() != "winner":
                continue
            team = normalize_team_name(row.get("team", ""))
            odds = _parse_decimal(row.get("odds_decimal", ""))
            if not team or odds is None or odds <= 1:
                continue
            out.append(
                MarketOdd(
                    market_type="winner",
                    team=team,
                    group=(row.get("group") or "").strip(),
                    odds_decimal=odds,
                    bookmaker=(row.get("bookmaker") or "manual").strip(),
                    source_url=(row.get("source_url") or "manual").strip(),
                    collected_at=(row.get("collected_at") or datetime.now(UTC).isoformat().replace("+00:00", "Z")).strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return out


def write_normalized_market_odds(records: list[MarketOdd], path: str | Path = "data/odds.json") -> dict[str, Any]:
    payload = build_market_odds_payload(records)
    JsonStore().write(str(path), payload)
    return payload


def build_market_odds_payload(records: list[MarketOdd]) -> dict[str, Any]:
    winners = [r for r in records if r.market_type == "winner" and r.odds_decimal > 1]
    grouped: dict[str, list[MarketOdd]] = {}
    for record in winners:
        grouped.setdefault(record.team, []).append(record)
    aggregated: list[dict[str, Any]] = []
    for team, items in grouped.items():
        odds = median([item.odds_decimal for item in items])
        raw_probability = 1 / odds
        latest = max(item.collected_at for item in items)
        aggregated.append({
            "market_type": "winner",
            "team": team,
            "odds_decimal": odds,
            "raw_implied_probability": raw_probability,
            "bookmakers": sorted({item.bookmaker for item in items}),
            "source_urls": sorted({item.source_url for item in items}),
            "collected_at": latest,
            "records": [item.to_json_record() for item in items],
        })
    total_raw = sum(item["raw_implied_probability"] for item in aggregated)
    overround = total_raw if total_raw else None
    for item in aggregated:
        item["market_probability"] = item["raw_implied_probability"] / total_raw if total_raw else 0.0
        item["market_probability_pct"] = item["market_probability"] * 100
    aggregated.sort(key=lambda r: r["market_probability"], reverse=True)
    return {
        "source": "market_odds",
        "provider": "oddschecker_manual_or_scraped",
        "last_updated": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "markets": ["winner"] if aggregated else [],
        "overround": overround,
        "outrights": aggregated,
        "matches": [],
    }


def merge_market_odds_records(primary: list[MarketOdd], fallback: list[MarketOdd]) -> list[MarketOdd]:
    """Merge odds preserving scraped/current records and filling missing teams from cache/manual CSV.

    This prevents a partial HTML scrape from overwriting a richer manually collected CSV.
    Records in ``primary`` win over records in ``fallback`` for the same market/team/group.
    """
    merged: list[MarketOdd] = []
    seen: set[tuple[str, str, str]] = set()
    for source in (primary, fallback):
        for record in source:
            key = (record.market_type, record.team, record.group or "")
            if key in seen:
                continue
            merged.append(record)
            seen.add(key)
    return merged


def update_market_odds_files(
    records: list[MarketOdd],
    csv_path: str | Path = "data/market_odds_manual.csv",
    odds_json_path: str | Path = "data/odds.json",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    write_market_odds_csv(records, csv_path)
    payload = build_market_odds_payload(records)
    if metadata:
        payload.update(metadata)
    JsonStore().write(str(odds_json_path), payload)
    write_market_odds_report(payload)
    return payload


def fetch_market_odds_periodically(
    url: str = ODDSCHECKER_WINNER_URL,
    csv_path: str | Path = "data/market_odds_manual.csv",
    odds_json_path: str | Path = "data/odds.json",
    runs: int = 1,
    interval_minutes: float = 0,
    use_cache_on_fail: bool = True,
) -> dict[str, Any]:
    if runs < 1:
        raise ValueError("market odds runs precisa ser >= 1.")
    last_payload: dict[str, Any] = {}
    errors: list[str] = []
    for run_idx in range(runs):
        try:
            scraped_records = scrape_oddschecker_winner(url)
            if not scraped_records:
                raise RuntimeError("Nenhuma odd de vencedor encontrada no HTML.")
            cached_records = read_market_odds_csv(csv_path) if use_cache_on_fail else []
            records = merge_market_odds_records(scraped_records, cached_records) if cached_records else scraped_records
            last_payload = update_market_odds_files(
                records,
                csv_path,
                odds_json_path,
                metadata={
                    "fetch_status": "partial_merged" if cached_records and len(scraped_records) < len(records) else "scraped",
                    "scraped_records": len(scraped_records),
                    "cached_records": len(cached_records),
                    "merged_records": len(records),
                },
            )
        except Exception as exc:
            errors.append(str(exc))
            cached_records = read_market_odds_csv(csv_path) if use_cache_on_fail else []
            if cached_records:
                last_payload = build_market_odds_payload(cached_records)
                last_payload.update({
                    "fetch_status": "cache_fallback",
                    "scraped_records": 0,
                    "cached_records": len(cached_records),
                    "merged_records": len(cached_records),
                })
                JsonStore().write(str(odds_json_path), last_payload)
                write_market_odds_report(last_payload, warnings=[f"Scraping falhou; cache CSV usado: {exc}"])
            else:
                raise
        if run_idx < runs - 1 and interval_minutes > 0:
            time.sleep(interval_minutes * 60)
    if errors and last_payload:
        last_payload.setdefault("warnings", []).extend(errors)
    return last_payload


def load_market_probabilities(path: str | Path = "data/odds.json") -> dict[str, float]:
    payload = JsonStore().read(str(path), {})
    probs: dict[str, float] = {}
    for item in payload.get("outrights", []) or []:
        team = item.get("team")
        probability = item.get("market_probability")
        if team and isinstance(probability, (int, float)):
            probs[team] = float(probability)
    return probs


def write_market_comparison(
    model_csv_path: str | Path = "output/global_title_ranking.csv",
    odds_path: str | Path = "data/odds.json",
    output_csv: str | Path = "output/market_comparison.csv",
    output_txt: str | Path = "output/market_comparison_report.txt",
    model_name: str = "balanced",
) -> list[dict[str, Any]]:
    market = load_market_probabilities(odds_path)
    if not market:
        raise ValueError("Nenhuma probabilidade de mercado encontrada em data/odds.json.")
    model_rows = _read_model_title_rows(model_csv_path, model_name)
    rows: list[dict[str, Any]] = []
    for team, model_pct in model_rows.items():
        if team not in market:
            continue
        market_pct = market[team] * 100
        delta = model_pct - market_pct
        rows.append({
            "team": team,
            "model": model_name,
            "model_winner_pct": round(model_pct, 4),
            "market_winner_pct": round(market_pct, 4),
            "delta_pp": round(delta, 4),
            "interpretation": _market_delta_interpretation(delta),
        })
    rows.sort(key=lambda row: abs(row["delta_pp"]), reverse=True)
    out_csv = Path(output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        fields = ["team", "model", "model_winner_pct", "market_winner_pct", "delta_pp", "interpretation"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write_market_comparison_report(rows, output_txt)
    return rows


def _read_model_title_rows(path: str | Path, model_name: str) -> dict[str, float]:
    target = Path(path)
    if not target.exists():
        raise ValueError(f"Arquivo de ranking global nao encontrado: {path}. Rode o workflow com --all-teams antes.")
    rows: dict[str, float] = {}
    with target.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("model") != model_name:
                continue
            team = row.get("team")
            if not team:
                continue
            try:
                rows[team] = float(row.get("winner_pct") or 0)
            except ValueError:
                continue
    return rows


def write_market_odds_report(payload: dict[str, Any], warnings: list[str] | None = None) -> None:
    lines = ["Market Odds Report", "", f"Fonte: {payload.get('provider') or payload.get('source')}"]
    lines.append(f"Atualizado em: {payload.get('last_updated')}")
    overround = payload.get("overround")
    if overround:
        lines.append(f"Overround bruto: {overround * 100:.2f}%")
    lines.append(f"Selecoes com odds de campeao: {len(payload.get('outrights', []) or [])}")
    if payload.get("fetch_status"):
        lines.append(f"Status da coleta: {payload.get('fetch_status')}")
    if payload.get("scraped_records") is not None:
        lines.append(f"Registros raspados: {payload.get('scraped_records')} | cache/manual: {payload.get('cached_records')} | mesclados: {payload.get('merged_records')}")
    if warnings:
        lines += ["", "Warnings:"] + [f"- {warning}" for warning in warnings]
    lines += ["", "Top mercado de campeao:"]
    for item in (payload.get("outrights", []) or [])[:15]:
        lines.append(f"- {item['team']}: odd {item['odds_decimal']:.2f}; mercado {item['market_probability_pct']:.2f}%")
    target = Path("output/market_odds_report.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_market_comparison_report(rows: list[dict[str, Any]], path: str | Path = "output/market_comparison_report.txt") -> None:
    lines = ["Market Comparison Report", "", "Modelo vs mercado - Campeao", ""]
    if not rows:
        lines.append("Nenhuma selecao em comum entre o modelo e o mercado.")
    else:
        lines.append("Maiores discrepancias absolutas:")
        for row in rows[:12]:
            lines.append(
                f"- {row['team']}: modelo {row['model_winner_pct']:.2f}% vs "
                f"mercado {row['market_winner_pct']:.2f}% ({row['delta_pp']:+.2f} p.p.) — {row['interpretation']}"
            )
        optimistic = [row for row in rows if row["delta_pp"] > 0]
        pessimistic = [row for row in rows if row["delta_pp"] < 0]
        lines += ["", "Modelo mais otimista que o mercado:"]
        for row in optimistic[:8]:
            lines.append(f"- {row['team']}: {row['delta_pp']:+.2f} p.p.")
        lines += ["", "Modelo mais pessimista que o mercado:"]
        for row in pessimistic[:8]:
            lines.append(f"- {row['team']}: {row['delta_pp']:+.2f} p.p.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _market_delta_interpretation(delta: float) -> str:
    if abs(delta) < 1.0:
        return "alinhado"
    if delta > 0:
        return "modelo mais otimista que o mercado"
    return "modelo mais pessimista que o mercado"


def _format_decimal(value: float) -> str:
    if math.isclose(value, round(value)):
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


# ─────────────────────────────────────────────────────────────────────────────
# Funções adicionadas: write_market_comparison_v2 e write_market_comparison_report_v2
# (substituem as originais mantendo compatibilidade retroativa)
# ─────────────────────────────────────────────────────────────────────────────

def write_market_comparison_full(
    model_csv_path: str | Path = "output/global_title_ranking.csv",
    odds_path: str | Path = "data/odds.json",
    output_csv: str | Path = "output/market_comparison.csv",
    output_txt: str | Path = "output/market_comparison_report.txt",
    model_name: str = "balanced",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Versão corrigida: compara TODAS as seleções, sem limitar silenciosamente.

    Seleções sem odds são incluídas no CSV com market_winner_pct=None.
    O parâmetro ``limit`` controla exibição no relatório, não no CSV.
    """
    market = load_market_probabilities(odds_path)
    if not market:
        raise ValueError("Nenhuma probabilidade de mercado encontrada em data/odds.json.")
    model_rows = _read_model_title_rows(model_csv_path, model_name)

    rows_with_odds: list[dict[str, Any]] = []
    rows_without_odds: list[dict[str, Any]] = []
    for team, model_pct in model_rows.items():
        if team in market:
            market_pct = market[team] * 100
            delta = model_pct - market_pct
            rows_with_odds.append({
                "team": team,
                "model": model_name,
                "model_winner_pct": round(model_pct, 4),
                "market_winner_pct": round(market_pct, 4),
                "delta_pp": round(delta, 4),
                "interpretation": _market_delta_interpretation(delta),
            })
        else:
            rows_without_odds.append({
                "team": team,
                "model": model_name,
                "model_winner_pct": round(model_pct, 4),
                "market_winner_pct": None,
                "delta_pp": None,
                "interpretation": "sem_odds_de_mercado",
            })

    rows_with_odds.sort(key=lambda row: abs(row["delta_pp"]), reverse=True)
    all_rows = rows_with_odds + rows_without_odds

    out_csv = Path(output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        fields = ["team", "model", "model_winner_pct", "market_winner_pct", "delta_pp", "interpretation"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)

    _write_market_comparison_report_full(rows_with_odds, rows_without_odds, output_txt, limit=limit)
    return all_rows


def _write_market_comparison_report_full(
    rows_with_odds: list[dict[str, Any]],
    rows_without_odds: list[dict[str, Any]],
    path: str | Path = "output/market_comparison_report.txt",
    limit: int | None = None,
) -> None:
    total_with = len(rows_with_odds)
    total_without = len(rows_without_odds)
    lines = [
        "Market Comparison Report",
        "",
        "Modelo vs mercado - Campeao",
        f"Selecoes comparadas com odds: {total_with}",
        f"Selecoes sem odds:            {total_without}",
        "",
    ]

    display_rows = rows_with_odds[:limit] if limit else rows_with_odds
    display_msg = ""
    if limit and limit < total_with:
        display_msg = f" (exibindo top {limit} de {total_with} seleções comparadas)"

    if not display_rows:
        lines.append("Nenhuma selecao em comum entre o modelo e o mercado.")
    else:
        lines.append(f"Maiores discrepancias absolutas{display_msg}:")
        for row in display_rows[:12]:
            lines.append(
                f"- {row['team']}: modelo {row['model_winner_pct']:.2f}% vs "
                f"mercado {row['market_winner_pct']:.2f}% ({row['delta_pp']:+.2f} p.p.) — {row['interpretation']}"
            )
        optimistic = [row for row in rows_with_odds if row["delta_pp"] > 0]
        pessimistic = [row for row in rows_with_odds if row["delta_pp"] < 0]
        lines += ["", "Modelo mais otimista que o mercado:"]
        for row in optimistic[:8]:
            lines.append(f"- {row['team']}: {row['delta_pp']:+.2f} p.p.")
        lines += ["", "Modelo mais pessimista que o mercado:"]
        for row in pessimistic[:8]:
            lines.append(f"- {row['team']}: {row['delta_pp']:+.2f} p.p.")

    if rows_without_odds:
        lines += ["", "Selecoes sem odds de mercado:"]
        for row in rows_without_odds[:20]:
            lines.append(f"- {row['team']}: {row['model_winner_pct']:.2f}% (sem odds)")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
