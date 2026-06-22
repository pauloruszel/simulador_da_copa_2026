import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertTriangle, BarChart3, Clock, Database, FileText, Play, RefreshCw, RotateCcw, ShieldAlert, Square, Trophy, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cancelJob, fetchCommands, fetchDashboard, fetchGlobalReport, fetchJob, fetchJobs, fetchMarketReport, retryJob, submitJob } from "./api";
import type { CommandAction, DashboardJob, DashboardSummary, GlobalReport, GroupLeadershipRow, GroupQualificationRow, MarketAnchorRow, MarketReport, ModelName, ModelSensitivityRow, TeamProbability } from "./types";
import "./styles.css";

type TabKey = "dashboard" | "teams" | "groups" | "calibration" | "operations" | "market";
type MetricKey = "round32_pct" | "round16_pct" | "quarterfinal_pct" | "semifinal_pct" | "final_pct" | "winner_pct";

const metricLabels: Record<MetricKey, string> = {
  round32_pct: "Mata-mata",
  round16_pct: "Oitavas",
  quarterfinal_pct: "Quartas",
  semifinal_pct: "Semifinal",
  final_pct: "Final",
  winner_pct: "Campeão",
};

const modelLabels: Record<ModelName, string> = {
  balanced: "Modelo Padrão",
  tuned: "Modelo Ajustado",
  market_calibrated: "Modelo Mercado",
};

const modelHelp: Record<ModelName, string> = {
  balanced: "Usa a configuração principal e mais estável do simulador.",
  tuned: "Aplica a calibração encontrada no backtest como visão alternativa.",
  market_calibrated: "Probabilidade de campeão ancorada pelas odds do mercado (title_anchor).",
};
const metricHelp: Record<MetricKey, string> = {
  round32_pct: "Chance de passar da fase de grupos e entrar na primeira fase eliminatória.",
  round16_pct: "Chance de passar pela fase de 32 e chegar às oitavas.",
  quarterfinal_pct: "Chance de chegar às quartas de final.",
  semifinal_pct: "Chance de chegar à semifinal.",
  final_pct: "Chance de chegar à decisão.",
  winner_pct: "Chance de ser campeão.",
};


function pct(value: number | string | undefined | null): string {
  const num = Number(value ?? 0);
  if (num > 0 && num < 0.01) return "<0.01%";
  return `${num.toFixed(2)}%`;
}

function pp(value: number | string | undefined | null): string {
  const num = Number(value ?? 0);
  return `${num >= 0 ? "+" : ""}${num.toFixed(2)} p.p.`;
}

function gapPp(value: number | string | undefined | null): string {
  return `${Number(value ?? 0).toFixed(2)} p.p.`;
}

function formatDate(value?: string | null): string {
  if (!value) return "n/d";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "n/d";
  return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function normalizeText(value: string): string {
  return value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function displayRunStatus(status?: string | null, recommendation?: string | null): string {
  const raw = normalizeText(status ?? "");
  const rec = normalizeText(recommendation ?? "");
  if (raw === "atencao" && rec.includes("alerta leve")) return "Atenção leve";
  if (raw === "atencao") return "Atenção";
  if (raw === "erro") return "Erro";
  if (raw === "ok") return "OK";
  if (raw === "indisponivel") return "Indisponível";
  return status || "n/d";
}

function displayRecommendation(value?: string | null): string {
  const normalized = normalizeText(value ?? "");
  if (!value) return "n/d";
  if (normalized.includes("placar live") || normalized.includes("placar ao vivo")) return "Dados confiáveis, com alerta leve: foi detectado um placar ao vivo/não final, mas ele foi ignorado com segurança.";
  if (normalized.includes("warnings do multi-source")) return "Dados confiáveis, com alerta leve: há warnings do multi-source sem conflitos; revise o relatório da atualização.";
  if (normalized.includes("dados confiaveis com alerta leve")) return "Dados confiáveis, com alerta leve: revise o relatório da atualização.";
  if (normalized === "dados confiaveis") return "Dados confiáveis.";
  if (normalized.includes("nao recomendado confiar")) return "Não recomendado confiar: houve erro no workflow.";
  if (normalized.includes("conflitos de fontes")) return "Dados com alerta: há conflitos de fontes.";
  if (normalized.includes("workflow sem observacoes criticas")) return "Sem observações críticas. O alerta atual, quando houver, é apenas preventivo.";
  return value;
}

function workflowMetrics(dashboard: DashboardSummary): Record<string, unknown> {
  const metrics = dashboard.latest_workflow?.metrics;
  return metrics && typeof metrics === "object" && !Array.isArray(metrics) ? metrics : {};
}

function metricObject(metrics: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = metrics[key];
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function numberMetric(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function backtestSummary(dashboard: DashboardSummary): string {
  const metrics = workflowMetrics(dashboard);
  const backtest = metricObject(metrics, "backtest");
  const brier = numberMetric(backtest.brier);
  const logLoss = numberMetric(backtest.log_loss);
  if (brier === null && logLoss === null) return dashboard.status?.best_backtest_model ?? "n/d";
  return `Modelo atual — Brier ${brier?.toFixed(3) ?? "n/d"}, Log Loss ${logLoss?.toFixed(3) ?? "n/d"}`;
}

function tuningSummary(dashboard: DashboardSummary): string {
  const tuning = metricObject(workflowMetrics(dashboard), "tuning");
  const tested = numberMetric(tuning.tested);
  const best = numberMetric(tuning.best_brier);
  const improvement = numberMetric(tuning.improvement);
  if (best === null && improvement === null) return "n/d";
  return `${tested?.toFixed(0) ?? "n/d"} combinações testadas; melhor Brier ${best?.toFixed(3) ?? "n/d"}; melhora ${improvement?.toFixed(3) ?? "n/d"}`;
}

function deltaClass(value: number): string {
  if (value > 0) return "delta-positive";
  if (value < 0) return "delta-negative";
  return "delta-neutral";
}

function impactLabel(value: number): string {
  const abs = Math.abs(value);
  if (abs < 0.25) return "Estável";
  if (abs < 1) return "Mudança leve";
  if (abs < 3) return "Mudança moderada";
  return "Mudança relevante";
}

type RiskHighlight = { team: string; pct: string };

function firstRiskHighlight(riskText: string): RiskHighlight | null {
  const match = riskText.match(/Favoritos com maior risco antes do (?:R32|mata-mata): ([^\n]+)/i);
  const first = match?.[1]?.split(";")[0]?.trim();
  if (!first) return null;
  const parts = first.match(/^(.+?)\s+elim\. grupo\s+([0-9.,]+%)/i);
  if (!parts) return { team: first, pct: "n/d" };
  return { team: parts[1], pct: parts[2] };
}


function phaseRows(rows: TeamProbability[], field: keyof TeamProbability): TeamProbability[] {
  return [...rows].sort((a, b) => Number(b[field] ?? 0) - Number(a[field] ?? 0)).slice(0, 10);
}

function ProgressBar({ value, label }: { value: number | string | undefined | null; label?: string }) {
  const num = Math.max(0, Math.min(100, Number(value ?? 0)));
  return (
    <div className="progress-wrap" aria-label={label ?? `Probabilidade ${num.toFixed(2)}%`}>
      <div className="progress-track"><div className="progress-fill" style={{ width: `${num}%` }} /></div>
    </div>
  );
}

function GapChip({ label, value, tone }: { label: string; value: number | string | undefined | null; tone: "leadership" | "qualification" }) {
  const num = Number(value ?? 0);
  const risk = num <= 10 ? "alta" : num <= 25 ? "média" : "baixa";
  return (
    <div className={`gap-chip gap-${tone}`}>
      <span>{label}</span>
      <strong>{gapPp(num)}</strong>
      <small>Disputa {risk}</small>
    </div>
  );
}

function MetricCard({ icon, label, value, detail, tone = "default" }: { icon: React.ReactNode; label: string; value: string; detail: string; tone?: "default" | "warning" | "success" }) {
  return (
    <section className={`metric-card tone-${tone}`}>
      <div className="metric-icon">{icon}</div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </section>
  );
}

function ModelToggle({ model, onChange, available }: { model: ModelName; onChange: (model: ModelName) => void; available: ModelName[] }) {
  return (
    <div className="model-selector">
      <span>Modelo de simulação</span>
      <div className="mode-toggle" aria-label="Modelo exibido">
        {(["balanced", "tuned", "market_calibrated"] as ModelName[]).map((item) => (
          <button key={item} type="button" title={`${modelLabels[item]}: ${modelHelp[item]}`} className={model === item ? "active" : ""} disabled={!available.includes(item)} onClick={() => onChange(item)}>
            {modelLabels[item]}
          </button>
        ))}
      </div>
      <small>{modelLabels[model]}: {modelHelp[model]}</small>
    </div>
  );
}

function RankingTable({ title, rows, field }: { title: string; rows: TeamProbability[]; field: keyof TeamProbability }) {
  return (
    <section className="panel">
      <header className="panel-header"><h2>{title}</h2></header>
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Seleção</th><th>Grupo</th><th>Prob.</th></tr></thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${title}-${row.team}`}>
                <td>{index + 1}</td><td>{row.team}</td><td>{row.group}</td><td>{pct(row[field] as number)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function GroupOutlook({ title, rows, mode }: { title: string; rows: GroupLeadershipRow[] | GroupQualificationRow[]; mode: "leadership" | "qualification" }) {
  const isLeadershipMode = mode === "leadership";
  return (
    <section className="panel">
      <header className="panel-header">
        <div>
          <h2>{title}</h2>
          <small>{isLeadershipMode ? "Menor diferença entre 1º e 2º favoritos ao topo do grupo." : "Menor diferença entre 2º e 3º em probabilidade de mata-mata; não é necessariamente o corte exato dos melhores terceiros."}</small>
        </div>
      </header>
      <div className="stack-list cards-list">
        {rows.slice(0, 6).map((row) => {
          const isLeadership = mode === "leadership";
          const leftName = isLeadership ? (row as GroupLeadershipRow).favorite_to_win_group : (row as GroupQualificationRow).second_round32_candidate;
          const leftPct = isLeadership ? (row as GroupLeadershipRow).favorite_group_winner_pct : (row as GroupQualificationRow).second_round32_pct;
          const rightName = isLeadership ? (row as GroupLeadershipRow).second_group_winner_candidate : (row as GroupQualificationRow).third_round32_candidate;
          const rightPct = isLeadership ? (row as GroupLeadershipRow).second_group_winner_pct : (row as GroupQualificationRow).third_round32_pct;
          const gap = isLeadership ? (row as GroupLeadershipRow).leadership_gap_pct : (row as GroupQualificationRow).qualification_gap_2v3_pct;
          return (
            <article className="group-row group-row-card" key={`${title}-${row.model}-${row.group}`}>
              <div className="group-row-title"><strong>Grupo {row.group}</strong><span>{isLeadership ? "Disputa pelo 1º lugar" : "Disputa 2º x 3º"}</span></div>
              <div className="duel-line"><span>{leftName}</span><strong>{pct(leftPct)}</strong></div>
              <ProgressBar value={leftPct} />
              <div className="duel-line"><span>{rightName}</span><strong>{pct(rightPct)}</strong></div>
              <ProgressBar value={rightPct} />
              <GapChip label={isLeadership ? "Gap de liderança" : "Gap 2º x 3º"} value={gap} tone={isLeadership ? "leadership" : "qualification"} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SensitivityTable({ rows }: { rows: ModelSensitivityRow[] }) {
  const sorted = [...rows].sort((a, b) => b.abs_delta_winner_pct - a.abs_delta_winner_pct).slice(0, 10);
  return (
    <section className="panel wide">
      <header className="panel-header">
        <div>
          <h2>Impacto do Modelo Ajustado</h2>
          <small>Diferença entre Modelo Ajustado e Modelo Padrão. Probabilidades usam %, diferenças usam p.p.</small>
        </div>
      </header>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Seleção</th><th>Grupo</th><th>Campeão — Padrão</th><th>Campeão — Ajustado</th><th>Δ Campeão</th><th>Δ Final</th><th>Δ Semifinal</th><th>Δ Mata-mata</th><th>Interpretação</th></tr></thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.team}>
                <td>{row.team}</td><td>{row.group}</td><td>{pct(row.balanced_winner_pct)}</td><td>{pct(row.tuned_winner_pct)}</td>
                <td className={deltaClass(row.delta_winner_pct)}>{pp(row.delta_winner_pct)}</td>
                <td className={deltaClass(row.delta_final_pct)}>{pp(row.delta_final_pct)}</td>
                <td className={deltaClass(row.delta_semifinal_pct)}>{pp(row.delta_semifinal_pct)}</td>
                <td className={deltaClass(row.delta_round32_pct)}>{pp(row.delta_round32_pct)}</td>
                <td><span className={`impact-badge ${impactLabel(row.delta_winner_pct).toLowerCase().replace(/ /g, "-")}`}>{impactLabel(row.delta_winner_pct)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RiskCards({ riskText, leadership, qualification }: { riskText: string; leadership: GroupLeadershipRow[]; qualification: GroupQualificationRow[] }) {
  const top5 = riskText.match(/Concentra[cç][aã]o dos 5 maiores favoritos ao t[ií]tulo: ([0-9.,]+%)/i)?.[1] ?? "n/d";
  const firstRisk = firstRiskHighlight(riskText);
  return (
    <section className="panel wide">
      <header className="panel-header"><h2>Riscos globais</h2><ShieldAlert size={18} /></header>
      <div className="risk-grid">
        <MetricCard icon={<AlertTriangle size={18} />} label="Top 5 favoritos" value={top5} detail="Concentração do título" tone="warning" />
        <MetricCard icon={<Users size={18} />} label="Liderança mais aberta" value={`Grupo ${leadership[0]?.group ?? "n/d"}`} detail={leadership[0] ? `Gap ${gapPp(leadership[0].leadership_gap_pct)}` : "n/d"} />
        <MetricCard icon={<Users size={18} />} label="Disputa 2º x 3º" value={`Grupo ${qualification[0]?.group ?? "n/d"}`} detail={qualification[0] ? `Gap ${gapPp(qualification[0].qualification_gap_2v3_pct)}` : "n/d"} />
        <MetricCard icon={<ShieldAlert size={18} />} label="Maior risco pré-mata-mata" value={firstRisk?.team ?? "n/d"} detail={firstRisk ? `${firstRisk.pct} de eliminação no grupo` : "Entre favoritos monitorados"} tone="warning" />
      </div>
      <details className="details-block"><summary>Ver relatório textual completo</summary><pre className="report-text">{riskText || "Sem relatório de risco."}</pre></details>
    </section>
  );
}

function RunObservations({ dashboard }: { dashboard: DashboardSummary }) {
  const observations = dashboard.status?.observations ?? [];
  const latestReport = dashboard.reports?.find((item) => item.name === "latest_global_report.txt" || item.name === "latest_full_report.txt") ?? dashboard.reports?.[0];
  return (
    <section className="panel wide">
      <header className="panel-header"><h2>Observações do run</h2><Clock size={18} /></header>
      <div className="observations">
        <div><strong>Status:</strong> {displayRunStatus(dashboard.status?.status, dashboard.status?.recommendation)}</div>
        <div><strong>Recomendação:</strong> {displayRecommendation(dashboard.status?.recommendation)}</div>
        <div><strong>Backtest:</strong> {backtestSummary(dashboard)}</div>
        <div><strong>Tuning dos pesos:</strong> {tuningSummary(dashboard)}</div>
        <div><strong>Última atualização:</strong> {latestReport ? `${formatDate(latestReport.modified_at)} (${latestReport.age_minutes} min)` : "n/d"}</div>
        <ul>{observations.map((item) => <li key={item}>{displayRecommendation(item)}</li>)}</ul>
      </div>
    </section>
  );
}

function DashboardPage({ dashboard, global, selectedRows, metric, onMetricChange, chartRows, leadershipRows, qualificationRows }: { dashboard: DashboardSummary; global: GlobalReport; selectedRows: TeamProbability[]; metric: MetricKey; onMetricChange: (metric: MetricKey) => void; chartRows: { team: string; valor: number | string | undefined | null }[]; leadershipRows: GroupLeadershipRow[]; qualificationRows: GroupQualificationRow[] }) {
  return (
    <section className="main-grid">
      <section className="panel wide">
        <header className="panel-header"><h2>Modelos de simulação</h2></header>
        <div className="model-explanation dashboard-model-grid">
          <article>
            <strong>Modelo Padrão</strong>
            <p>Configuração principal e mais estável do simulador. É o cenário de referência para leitura executiva.</p>
          </article>
          <article>
            <strong>Modelo Ajustado</strong>
            <p>Aplica a calibração encontrada no backtest. Deve ser lido como visão alternativa, não como substituto automático.</p>
          </article>
          <article>
            <strong>Como comparar</strong>
            <p>Use diferenças em p.p. para entender impacto real da calibração; percentuais isolados mostram probabilidade total.</p>
          </article>
        </div>
      </section>
      <RunObservations dashboard={dashboard} />
      <section className="panel wide">
        <header className="panel-header">
          <div><h2>Ranking por fase — {metricLabels[metric]}</h2><small>{metricHelp[metric]}</small></div>
          <div className="mode-toggle phase-toggle">{(Object.keys(metricLabels) as MetricKey[]).map((key) => <button key={key} className={metric === key ? "active" : ""} type="button" onClick={() => onMetricChange(key)}>{metricLabels[key]}</button>)}</div>
        </header>
        <div className="chart-box"><ResponsiveContainer width="100%" height={280}><BarChart data={chartRows} layout="vertical" margin={{ left: 24, right: 24 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tickFormatter={(value) => `${value}%`} /><YAxis type="category" dataKey="team" width={96} /><Tooltip formatter={(value) => pct(Number(value))} /><ReferenceLine x={10} stroke="#94a3b8" strokeDasharray="3 3" /><Bar dataKey="valor" fill="#2563eb" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer></div>
      </section>
      <RankingTable title="Mata-mata" rows={phaseRows(selectedRows, "round32_pct")} field="round32_pct" />
      <RankingTable title="Oitavas" rows={phaseRows(selectedRows, "round16_pct")} field="round16_pct" />
      <RankingTable title="Quartas" rows={phaseRows(selectedRows, "quarterfinal_pct")} field="quarterfinal_pct" />
      <RankingTable title="Semifinal" rows={phaseRows(selectedRows, "semifinal_pct")} field="semifinal_pct" />
      <RankingTable title="Final" rows={phaseRows(selectedRows, "final_pct")} field="final_pct" />
      <RankingTable title="Campeão" rows={phaseRows(selectedRows, "winner_pct")} field="winner_pct" />
      <GroupOutlook title="Liderança mais indefinida" rows={leadershipRows} mode="leadership" />
      <GroupOutlook title="Disputa 2º x 3º mais indefinida" rows={qualificationRows} mode="qualification" />
      <RiskCards riskText={global.risk_report} leadership={leadershipRows} qualification={qualificationRows} />
    </section>
  );
}

function TeamsPage({ rows }: { rows: TeamProbability[] }) {
  const [query, setQuery] = useState("");
  const filtered = rows.filter((row) => normalizeText(row.team).includes(normalizeText(query)) || normalizeText(row.group).includes(normalizeText(query)));
  return (
    <section className="panel wide">
      <header className="panel-header">
        <div><h2>Seleções</h2><small>Ranking ordenado por chance de campeão no modelo selecionado.</small></div>
        <input className="search-input" placeholder="Buscar seleção ou grupo" value={query} onChange={(event) => setQuery(event.target.value)} />
      </header>
      <div className="table-note">Mata-mata = classificação à primeira fase eliminatória. Valores muito pequenos aparecem como &lt;0.01% para evitar arredondamento enganoso.</div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Seleção</th><th>Grupo</th><th>Mata-mata</th><th>Oitavas</th><th>Quartas</th><th>Semifinal</th><th>Final</th><th>Campeão</th><th>Eliminado na fase de grupos</th><th>Adversário provável no mata-mata</th></tr></thead>
          <tbody>
            {filtered.map((row, index) => (
              <tr key={row.team}>
                <td>{index + 1}</td><td>{row.team}</td><td>{row.group}</td><td>{pct(row.round32_pct)}</td><td>{pct(row.round16_pct)}</td><td>{pct(row.quarterfinal_pct)}</td><td>{pct(row.semifinal_pct)}</td><td>{pct(row.final_pct)}</td><td>{pct(row.winner_pct)}</td><td>{pct(row.group_eliminated_pct)}</td><td>{row.most_common_round32_opponent ?? "n/d"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function GroupsPage({ rows, leadership, qualification }: { rows: TeamProbability[]; leadership: GroupLeadershipRow[]; qualification: GroupQualificationRow[] }) {
  const groups = [...new Set(rows.map((row) => row.group))].sort();
  return (
    <section className="main-grid">
      <section className="panel wide">
        <header className="panel-header"><h2>Grupos</h2></header>
        <div className="table-note">Os cards ordenam seleções por chance de mata-mata. O gap 2º x 3º mede disputa de posição no grupo; no formato de 48 seleções, terceiros também podem avançar.</div>
      </section>
      <section className="group-grid wide">
        {groups.map((group) => {
          const groupRows = rows.filter((row) => row.group === group).sort((a, b) => b.round32_pct - a.round32_pct);
          const lead = leadership.find((row) => row.group === group);
          const qual = qualification.find((row) => row.group === group);
          return (
            <article className="panel group-card" key={group}>
              <header className="group-card-header">
                <div>
                  <span>Grupo</span>
                  <h2>{group}</h2>
                </div>
                <div className="group-card-badge">{lead?.favorite_to_win_group ?? "n/d"} lidera</div>
              </header>
              <div className="group-team-list">
                {groupRows.map((row) => (
                  <div className="team-line" key={row.team}>
                    <div className="team-line-main"><strong>{row.team}</strong><span>{pct(row.round32_pct)}</span></div>
                    <ProgressBar value={row.round32_pct} label={`${row.team} classificação ao mata-mata`} />
                    <div className="team-line-meta"><span>1º {pct(row.group_winner_pct)}</span><span>Elim. grupo {pct(row.group_eliminated_pct)}</span><span>Campeão {pct(row.winner_pct)}</span></div>
                  </div>
                ))}
              </div>
              <footer className="group-card-footer">
                {lead && <GapChip label="Gap de liderança" value={lead.leadership_gap_pct} tone="leadership" />}
                {qual && <GapChip label="Gap 2º x 3º" value={qual.qualification_gap_2v3_pct} tone="qualification" />}
              </footer>
            </article>
          );
        })}
      </section>
    </section>
  );
}

function CalibrationPage({ global }: { global: GlobalReport }) {
  const rows = global.model_sensitivity;
  const biggestGain = [...rows].sort((a, b) => b.delta_winner_pct - a.delta_winner_pct)[0];
  const biggestDrop = [...rows].sort((a, b) => a.delta_winner_pct - b.delta_winner_pct)[0];
  const biggestRound32 = [...rows].sort((a, b) => Math.abs(b.delta_round32_pct) - Math.abs(a.delta_round32_pct))[0];
  const maxAbsWinner = Math.max(0, ...rows.map((row) => Math.abs(row.delta_winner_pct)));
  return (
    <section className="main-grid inner-grid">
      <section className="panel wide">
        <header className="panel-header"><h2>Resumo da calibração</h2></header>
        <div className="risk-grid calibration-summary">
          <MetricCard icon={<Trophy size={18} />} label="Maior alta em campeão" value={biggestGain ? biggestGain.team : "n/d"} detail={biggestGain ? pp(biggestGain.delta_winner_pct) : "n/d"} tone="success" />
          <MetricCard icon={<AlertTriangle size={18} />} label="Maior queda em campeão" value={biggestDrop ? biggestDrop.team : "n/d"} detail={biggestDrop ? pp(biggestDrop.delta_winner_pct) : "n/d"} tone="warning" />
          <MetricCard icon={<Users size={18} />} label="Maior impacto no mata-mata" value={biggestRound32 ? biggestRound32.team : "n/d"} detail={biggestRound32 ? pp(biggestRound32.delta_round32_pct) : "n/d"} />
          <MetricCard icon={<BarChart3 size={18} />} label="Intensidade" value={impactLabel(maxAbsWinner)} detail={`Maior variação em campeão: ${gapPp(maxAbsWinner)}`} />
        </div>
      </section>
      <SensitivityTable rows={rows} />
      <section className="panel wide">
        <header className="panel-header"><h2>Como ler esta aba</h2></header>
        <div className="observations">
          <p>O Modelo Padrão usa os pesos principais do simulador. O Modelo Ajustado aplica a calibração encontrada no backtest.</p>
          <p><strong>%</strong> mostra a chance total de uma seleção. <strong>p.p.</strong> mostra quanto essa chance mudou entre os dois modelos.</p>
          <p>O Modelo Ajustado não substitui automaticamente o Modelo Padrão. Ele serve para comparar sensibilidade e validar se a calibração muda demais o cenário.</p>
        </div>
      </section>
    </section>
  );
}

function OperationsPanel({ actions, onJobFinished }: { actions: CommandAction[]; onJobFinished: () => void }) {
  const [team, setTeam] = useState("Brasil");
  const [simulations, setSimulations] = useState(50000);
  const [seed, setSeed] = useState("42");
  const [running, setRunning] = useState("");
  const [job, setJob] = useState<DashboardJob | null>(null);
  const [jobs, setJobs] = useState<DashboardJob[]>([]);
  const [mode, setMode] = useState<"recommended" | "advanced">("recommended");
  const [error, setError] = useState("");

  const reloadJobs = useCallback(() => fetchJobs().then((payload) => setJobs(payload.jobs)).catch(() => setJobs([])), []);

  useEffect(() => { reloadJobs(); }, [reloadJobs]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(() => {
      fetchJob(job.id)
        .then((nextJob) => {
          setJob(nextJob);
          if (["succeeded", "failed", "canceled"].includes(nextJob.status)) {
            setRunning("");
            reloadJobs();
            if (nextJob.status === "succeeded") onJobFinished();
          }
        })
        .catch((err: Error) => {
          setError(err.message);
          setRunning("");
        });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job, onJobFinished, reloadJobs]);

  async function execute(action: string) {
    if (action === "update_results") {
      const confirmed = window.confirm("Você está prestes a aplicar alterações reais em data/matches.json. Confirme apenas se o dry-run estiver OK e sem conflitos.");
      if (!confirmed) return;
    }
    if (action === "odds_fetch_periodic") {
      const confirmed = window.confirm("A coleta periódica padrão roda 4 coletas com intervalo de 30 minutos. O job pode ficar ativo por mais de 90 minutos. Deseja iniciar?");
      if (!confirmed) return;
    }
    if (simulations < 100000 && ["workflow_team", "workflow_global", "odds_workflow", "odds_workflow_anchor", "odds_workflow_benchmark", "odds_workflow_experimental"].includes(action)) {
      const confirmed = window.confirm("Simulações abaixo de 100.000 são boas para exploração. Para relatório final, recomenda-se 200.000. Deseja continuar?");
      if (!confirmed) return;
    }
    setRunning(action);
    setError("");
    try {
      const nextJob = await submitJob({ action, team, simulations, seed: seed.trim() ? Number(seed) : null });
      setJob(nextJob);
      setJobs((current) => [nextJob, ...current]);
    } catch (err) {
      setError((err as Error).message);
      setRunning("");
    }
  }

  async function retryFailedJob(jobId: string) {
    setRunning(`retry-${jobId}`);
    setError("");
    try {
      const nextJob = await retryJob(jobId);
      setJob(nextJob);
      setJobs((current) => [nextJob, ...current]);
    } catch (err) {
      setError((err as Error).message);
      setRunning("");
    }
  }

  async function cancelCurrentJob() {
    if (!job) return;
    setError("");
    try {
      const canceled = await cancelJob(job.id);
      setJob(canceled);
      setRunning("");
      reloadJobs();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const latest = (action: string) => jobs.find((item) => item.request.action === action);
  const activeJob = jobs.find((item) => ["queued", "running"].includes(item.status));
  const retriedJobIds = new Set(jobs.map((item) => item.retried_from).filter(Boolean));
  const failedJobs = jobs.filter((item) => item.status === "failed" && !retriedJobIds.has(item.id)).slice(0, 4);
  const dryRun = latest("dry_run_multisource");
  const update = latest("update_results");
  const marketOdds = latest("fetch_market_odds") ?? latest("import_market_odds") ?? latest("odds_fetch_periodic");
  const marketComparison = latest("market_comparison");
  const oddsWorkflow = latest("odds_workflow");
  const backtest = latest("backtest");
  const tuning = latest("tune_weights");
  const dryRunOk = dryRun?.status === "succeeded";
  const updateOk = update?.status === "succeeded";
  const marketOk = marketOdds?.status === "succeeded" || oddsWorkflow?.status === "succeeded";
  const calibrationOk = backtest?.status === "succeeded" || tuning?.status === "succeeded" || oddsWorkflow?.status === "succeeded";
  const actionLabel = (action: string) => actions.find((item) => item.action === action)?.label ?? action;
  const busy = Boolean(running || activeJob);
  const stepStatus = (items: (DashboardJob | undefined)[]) => {
    if (items.some((item) => item?.status === "running" || item?.status === "queued")) return "em andamento";
    if (items.some((item) => item?.status === "failed")) return "revisar";
    if (items.some((item) => item?.status === "succeeded")) return "concluído";
    return "pendente";
  };

  const oddsWorkflowAnchor = latest("odds_workflow_anchor");
  const oddsWorkflowBenchmark = latest("odds_workflow_benchmark");
  const oddsWorkflowExperimental = latest("odds_workflow_experimental");
  const anyOddsWorkflow = oddsWorkflow ?? oddsWorkflowAnchor ?? oddsWorkflowBenchmark ?? oddsWorkflowExperimental;

  const stepGroups = [
    { number: 1, title: "Diagnóstico das fontes", status: stepStatus([latest("source_health_check"), dryRun]), detail: "Audita fontes e compara dados sem alterar arquivos.", actions: ["source_health_check", "dry_run_multisource"] },
    { number: 2, title: "Atualização dos dados", status: stepStatus([update]), detail: "Altera data/matches.json, cria snapshot e atualiza integridade dos grupos.", actions: ["update_results"], locked: !dryRunOk, lockReason: "Rode o dry-run sem erro antes de aplicar resultados." },
    { number: 3, title: "Odds de mercado", status: stepStatus([marketOdds, marketComparison]), detail: "Atualiza odds do Oddschecker, preserva o CSV/cache manual e compara mercado x modelo quando houver relatório global.", actions: ["fetch_market_odds", "import_market_odds", "market_comparison"] },
    { number: 4, title: "Calibração do modelo", status: stepStatus([backtest, tuning]), detail: "Valida o modelo e gera pesos recomendados sem sobrescrever os pesos padrão.", actions: ["backtest", "tune_weights"] },
    {
      number: 5,
      title: "Workflow com odds — Corrigir campeão pelo mercado",
      status: stepStatus([oddsWorkflowAnchor ?? oddsWorkflow]),
      detail: "Recomendado. Coleta odds, roda simulação global e ancora probabilidade de campeão pelo mercado (title_anchor). Gera Modelo Mercado.",
      actions: ["odds_workflow_anchor"],
      highlight: true,
    },
    { number: 6, title: "Workflow com odds — Benchmark", status: stepStatus([oddsWorkflowBenchmark]), detail: "Diagnóstico puro: compara modelo x mercado sem alterar probabilidades.", actions: ["odds_workflow_benchmark"] },
    { number: 7, title: "Workflow com odds — Ajuste experimental", status: stepStatus([oddsWorkflowExperimental]), detail: "Experimental: incorpora mercado no rating. Use apenas para análise comparativa.", actions: ["odds_workflow_experimental"] },
    { number: 8, title: "Simulação sem odds", status: stepStatus([latest("workflow_team"), latest("workflow_global")]), detail: updateOk || dryRunOk ? "Fluxo tradicional para probabilidades finais sem atualizar odds." : "Sem update recente registrado; revise dados antes do relatório final.", actions: ["workflow_team", "workflow_global"] },
  ];

  return (
    <section className="panel wide">
      <header className="panel-header">
        <h2>Operações do simulador</h2>
        <div className="mode-toggle">
          <button className={mode === "recommended" ? "active" : ""} type="button" onClick={() => setMode("recommended")}>Fluxo recomendado</button>
          <button className={mode === "advanced" ? "active" : ""} type="button" onClick={() => setMode("advanced")}>Avançado</button>
        </div>
      </header>
      <div className="ops-body">
        <div className="info-banner"><strong>Fluxo recomendado:</strong> rode diagnóstico e dry-run antes de aplicar resultados. Para relatório mais realista, use o botão <strong>Workflow com odds</strong>: ele coleta odds, preserva o CSV/cache, roda simulação global e gera comparação modelo x mercado.</div>
        <div className="ops-form">
          <label>Time<input value={team} onChange={(event) => setTeam(event.target.value)} /></label>
          <label>Simulações<input type="number" min={1} max={500000} value={simulations} onChange={(event) => setSimulations(Number(event.target.value))} /></label>
          <label>Seed<input value={seed} onChange={(event) => setSeed(event.target.value)} /></label>
        </div>
        <div className="ops-state">
          <span>Dry-run: {dryRun?.status ?? "pendente"}</span><span>Update: {update?.status ?? "pendente"}</span><span>Odds: {marketOk ? "ok" : "pendente"}</span><span>Calibração: {calibrationOk ? "ok" : "pendente"}</span><span>Fila: {activeJob ? `${activeJob.request.action} ${activeJob.status}` : "livre"}</span>
        </div>
        {mode === "recommended" ? (
          <div className="workflow-steps">
            {stepGroups.map((step) => (
              <article className={`workflow-step status-${step.status.replace(" ", "-")}${(step as {highlight?: boolean}).highlight ? " step-highlight" : ""}`} key={step.number}>
                <div className="step-index">{step.number}</div>
                <div className="step-content">
                  <header><strong>{step.title}</strong><span>{step.status}</span></header>
                  <p>{step.detail}</p>{(step as {locked?: boolean; lockReason?: string}).locked && <small>{(step as {locked?: boolean; lockReason?: string}).lockReason}</small>}
                  <div className="step-actions">
                    {step.actions.map((action) => <button className={`command-button${(step as {highlight?: boolean}).highlight ? " primary" : ""}`} type="button" key={action} disabled={busy || Boolean((step as {locked?: boolean}).locked)} onClick={() => execute(action)}><Play size={15} />{running === action ? "Executando..." : actionLabel(action)}</button>)}
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="command-grid">
            {actions.map((item) => <button className="command-button" type="button" key={item.action} disabled={busy} onClick={() => execute(item.action)}><Play size={15} />{running === item.action ? "Executando..." : item.label}</button>)}
          </div>
        )}
        {error && <div className="command-error">{error}</div>}
        {failedJobs.length > 0 && <div className="dead-letter-list">{failedJobs.map((failedJob) => <article key={failedJob.id} className="dead-letter-item"><div><strong>{actionLabel(failedJob.request.action)}</strong><span>{failedJob.error || failedJob.result?.stderr || "Job finalizado com erro."}</span></div><button className="command-button" type="button" disabled={Boolean(running)} onClick={() => retryFailedJob(failedJob.id)}><RotateCcw size={15} />{running === `retry-${failedJob.id}` ? "Reenfileirando..." : "Tentar de novo"}</button></article>)}</div>}
        {job && <div className="command-result"><strong>Job {job.status}</strong><span>{job.result?.command ?? `${job.request.action} aguardando execução`}{job.retried_from ? ` | retry de ${job.retried_from}` : ""}</span><pre>{job.result?.stdout || job.result?.stderr || job.error || "Aguardando saída do comando..."}</pre>{["queued", "running"].includes(job.status) && <button className="command-button secondary" type="button" onClick={cancelCurrentJob}><Square size={15} />Cancelar</button>}{job.status === "failed" && <button className="command-button" type="button" disabled={Boolean(running)} onClick={() => retryFailedJob(job.id)}><RotateCcw size={15} />{running === `retry-${job.id}` ? "Reenfileirando..." : "Tentar de novo"}</button>}</div>}
      </div>
    </section>
  );
}

function MarketPage({ marketReport }: { marketReport: MarketReport | null }) {
  if (!marketReport) {
    return (
      <section className="panel wide">
        <header className="panel-header"><h2>Mercado</h2></header>
        <div className="info-banner">Dados de mercado não disponíveis. Execute o <strong>Workflow com odds — Corrigir campeão pelo mercado</strong> na aba Operações para gerar este relatório.</div>
      </section>
    );
  }
  const { anchor, alerts, odds_summary, comparison } = marketReport;
  const anchorRows: MarketAnchorRow[] = anchor?.rows ?? [];
  const alertList = alerts?.alerts ?? [];
  const summary = anchor?.summary;
  const marketMode = anchor?.market_mode ?? "title_anchor";

  const modeBadge = {
    benchmark: "Odds usadas como benchmark",
    title_anchor: "Odds ancorando campeão",
    rating_adjustment: "Odds ajustando rating",
  }[marketMode] ?? marketMode;

  return (
    <div className="market-page">
      {/* Cards de resumo */}
      <section className="panel wide">
        <header className="panel-header"><h2>Mercado — Odds de Campeão</h2></header>
        <div className="market-summary-grid">
          <MetricCard icon={<Database size={20} />} label="Odds carregadas" value={String(odds_summary?.teams ?? summary?.teams_with_odds ?? "n/d")} detail={`${summary?.teams_without_odds ?? 0} seleções sem odds`} />
          <MetricCard icon={<BarChart3 size={20} />} label="Overround" value={odds_summary?.overround_pct != null ? `${odds_summary.overround_pct.toFixed(2)}%` : "n/d"} detail="soma das probabilidades brutas" />
          {summary?.biggest_above_market && <MetricCard icon={<AlertTriangle size={20} />} label="Maior acima do mercado" value={summary.biggest_above_market.team} detail={`${summary.biggest_above_market.delta_pp > 0 ? "+" : ""}${summary.biggest_above_market.delta_pp.toFixed(2)} p.p.`} tone="warning" />}
          {summary?.biggest_below_market && <MetricCard icon={<AlertTriangle size={20} />} label="Maior abaixo do mercado" value={summary.biggest_below_market.team} detail={`${summary.biggest_below_market.delta_pp.toFixed(2)} p.p.`} tone="warning" />}
          <MetricCard icon={<ShieldAlert size={20} />} label="Modo de mercado" value={modeBadge} detail={`${alerts?.alert_count ?? 0} alertas (|Δ| ≥ 3 p.p.)`} />
        </div>
      </section>

      {/* Alertas */}
      {alertList.length > 0 && (
        <section className="panel wide">
          <header className="panel-header"><h2>Alertas de divergência (|Δ| ≥ 3 p.p.)</h2></header>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Seleção</th><th>Modelo</th><th>Mercado</th><th>Modelo Mercado</th><th>Delta</th><th>Severidade</th></tr></thead>
              <tbody>
                {alertList.map((alert) => (
                  <tr key={alert.team} className={`severity-${alert.severity}`}>
                    <td><strong>{alert.team}</strong></td>
                    <td>{pct(alert.model_winner_pct)}</td>
                    <td>{pct(alert.market_winner_pct)}</td>
                    <td>{pct(alert.anchor_winner_pct)}</td>
                    <td className={alert.delta_pp > 0 ? "delta-positive" : "delta-negative"}>{alert.delta_pp > 0 ? "+" : ""}{alert.delta_pp.toFixed(2)} p.p.</td>
                    <td><span className={`badge badge-${alert.severity}`}>{alert.severity}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Tabela principal anchor */}
      {anchorRows.length > 0 && (
        <section className="panel wide">
          <header className="panel-header"><h2>Comparação: Modelo Padrão × Mercado × Modelo Mercado</h2></header>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Seleção</th><th>Grupo</th>
                  <th>Modelo Padrão</th><th>Mercado</th><th>Modelo Mercado</th>
                  <th>Δ Mod × Merc</th><th>Ajuste aplicado</th><th>Diagnóstico</th>
                </tr>
              </thead>
              <tbody>
                {anchorRows.map((row, idx) => {
                  const diagLabel: Record<string, string> = {
                    capped_above_market:    "Modelo muito acima do mercado (cap aplicado)",
                    capped_below_market:    "Modelo muito abaixo do mercado (cap aplicado)",
                    above_market_in_band:   "Modelo acima do mercado (dentro da banda)",
                    below_market_in_band:   "Modelo abaixo do mercado (dentro da banda)",
                    within_market_band:     "Alinhado com o mercado",
                    missing_market_odds:    "Sem odds de mercado",
                    insufficient_market_coverage: "Cobertura insuficiente",
                  };
                  const delta = row.delta_model_vs_market_pp;
                  const adj = row.adjustment_applied_pp;
                  return (
                    <tr key={row.team}>
                      <td>{idx + 1}</td>
                      <td><strong>{row.team}</strong></td>
                      <td>{row.group}</td>
                      <td>{pct(row.model_winner_pct)}</td>
                      <td>{row.market_winner_pct != null ? pct(row.market_winner_pct) : "n/d"}</td>
                      <td><strong>{pct(row.anchor_winner_pct)}</strong></td>
                      <td className={delta != null ? (delta > 0 ? "delta-positive" : delta < 0 ? "delta-negative" : "delta-neutral") : ""}>
                        {delta != null ? `${delta > 0 ? "+" : ""}${delta.toFixed(2)} p.p.` : "n/d"}
                      </td>
                      <td className={adj > 0.01 ? "delta-positive" : adj < -0.01 ? "delta-negative" : "delta-neutral"}>
                        {adj > 0 ? "+" : ""}{adj.toFixed(2)} p.p.
                      </td>
                      <td>{diagLabel[row.anchor_reason] ?? row.anchor_reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="table-note">
            Modelo Mercado = média ponderada 50/50 entre Modelo Padrão e probabilidade de mercado normalizada,
            com cap máximo de ±5 p.p. em relação ao mercado e renormalização final.
            O Modelo Padrão é preservado para auditoria.
          </div>
        </section>
      )}
    </div>
  );
}

function App() {
  const [dashboard, setDashboard] = useState<DashboardSummary | null>(null);
  const [global, setGlobal] = useState<GlobalReport | null>(null);
  const [actions, setActions] = useState<CommandAction[]>([]);
  const [model, setModel] = useState<ModelName>("balanced");
  const [metric, setMetric] = useState<MetricKey>("winner_pct");
  const [tab, setTab] = useState<TabKey>("dashboard");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [marketReport, setMarketReport] = useState<MarketReport | null>(null);

  const refreshData = useCallback(async (selectedModel: ModelName = model) => {
    setLoading(true); setError("");
    try {
      const [dashboardData, globalData, commandData] = await Promise.all([fetchDashboard(selectedModel), fetchGlobalReport(), fetchCommands()]);
      setDashboard(dashboardData); setGlobal(globalData); setActions(commandData.actions); setLastRefresh(new Date());
      // Tenta carregar market report (opcional — não falha se não existir)
      fetchMarketReport().then(setMarketReport).catch(() => setMarketReport(null));
    } catch (err) { setError((err as Error).message); } finally { setLoading(false); }
  }, [model]);

  useEffect(() => { refreshData(model); }, [model, refreshData]);

  const selectedRows = useMemo(() => global?.stage_probabilities.filter((row) => row.model === model).sort((a, b) => b.winner_pct - a.winner_pct) ?? dashboard?.top_title ?? [], [dashboard, global, model]);
  const chartRows = useMemo(() => [...selectedRows].sort((a, b) => Number(b[metric]) - Number(a[metric])).slice(0, 8).map((row) => ({ team: row.team, valor: row[metric] })), [selectedRows, metric]);
  const leadershipRows = useMemo(() => global?.group_leadership.filter((row) => row.model === model) ?? [], [global, model]);
  const qualificationRows = useMemo(() => global?.group_qualification.filter((row) => row.model === model) ?? [], [global, model]);

  if (error) return <main className="shell error-state">{error}</main>;
  if (loading && (!dashboard || !global)) return <main className="shell loading">Carregando relatórios...</main>;
  if (!dashboard || !global) return <main className="shell loading">Sem dados disponíveis.</main>;

  return (
    <main className="shell">
      <aside className="sidebar"><div className="brand"><Trophy size={24} /><span>Copa 2026</span></div><nav>{[{k:"dashboard",l:"Dashboard"},{k:"teams",l:"Seleções"},{k:"groups",l:"Grupos"},{k:"calibration",l:"Calibração"},{k:"market",l:"Mercado"},{k:"operations",l:"Operações"}].map((item) => <button key={item.k} className={tab === item.k ? "active" : ""} type="button" onClick={() => setTab(item.k as TabKey)}>{item.l}</button>)}</nav></aside>
      <section className="content">
        <header className="topbar"><div><h1>Dashboard de Simulação</h1><p>Relatórios locais gerados pelo simulador Monte Carlo. {lastRefresh ? `Atualizado às ${formatDate(lastRefresh.toISOString())}.` : ""}</p></div><div className="topbar-actions"><ModelToggle model={model} onChange={setModel} available={dashboard.available_models ?? ["balanced", "tuned"]} /><button className="ghost-button" type="button" disabled={loading} onClick={() => refreshData(model)}><RefreshCw size={16} />{loading ? "Atualizando..." : "Atualizar dados"}</button></div></header>
        {tab !== "operations" && tab !== "market" && <section className="metrics-grid"><MetricCard icon={<Activity size={20} />} label="Simulações" value={String(dashboard.meta.simulations ?? "n/d")} detail={`Seed ${dashboard.meta.seed ?? "n/d"}`} /><MetricCard icon={<Trophy size={20} />} label="Favorito" value={selectedRows[0]?.team ?? "n/d"} detail={`${pct(selectedRows[0]?.winner_pct)} de título no ${modelLabels[model]}`} /><MetricCard icon={<BarChart3 size={20} />} label="Relatórios" value={String(dashboard.report_files.length)} detail="arquivos em output/" /><MetricCard icon={<Database size={20} />} label="Fonte" value="Local" detail="global reports + workflow" /></section>}
        {tab === "dashboard" && <DashboardPage dashboard={dashboard} global={global} selectedRows={selectedRows} metric={metric} onMetricChange={setMetric} chartRows={chartRows} leadershipRows={leadershipRows} qualificationRows={qualificationRows} />}
        {tab === "teams" && <section className="main-grid"><TeamsPage rows={selectedRows} /></section>}
        {tab === "groups" && <GroupsPage rows={selectedRows} leadership={leadershipRows} qualification={qualificationRows} />}
        {tab === "calibration" && <CalibrationPage global={global} />}
        {tab === "market" && <MarketPage marketReport={marketReport} />}
        {tab === "operations" && <section className="main-grid"><OperationsPanel actions={actions} onJobFinished={() => refreshData(model)} /><section className="panel wide"><header className="panel-header"><h2>Relatórios disponíveis</h2><FileText size={18} /></header><div className="table-wrap"><table><thead><tr><th>Arquivo</th><th>Atualizado</th><th>Idade</th><th>Tamanho</th></tr></thead><tbody>{dashboard.reports.slice(0, 20).map((report) => <tr key={report.name}><td>{report.name}</td><td>{formatDate(report.modified_at)}</td><td>{report.age_minutes} min</td><td>{Math.round(report.size_bytes / 1024)} KB</td></tr>)}</tbody></table></div></section></section>}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
