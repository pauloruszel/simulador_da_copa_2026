import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Activity, AlertTriangle, BarChart3, Clock, Database, FileText, Play, RefreshCw, RotateCcw, ShieldAlert, Square, Trophy, Users } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cancelJob, fetchCommands, fetchDashboard, fetchGlobalReport, fetchJob, fetchJobs, retryJob, submitJob } from "./api";
import type { CommandAction, DashboardJob, DashboardSummary, GlobalReport, GroupLeadershipRow, GroupQualificationRow, ModelName, ModelSensitivityRow, TeamProbability } from "./types";
import "./styles.css";

type TabKey = "dashboard" | "teams" | "groups" | "calibration" | "operations";
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
};

const modelHelp: Record<ModelName, string> = {
  balanced: "Usa os pesos principais do simulador.",
  tuned: "Usa pesos otimizados pelo backtest mais recente.",
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
  return `${Number(value ?? 0).toFixed(2)}%`;
}

function pp(value: number | string | undefined | null): string {
  const num = Number(value ?? 0);
  return `${num >= 0 ? "+" : ""}${num.toFixed(2)} p.p.`;
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
  const risk = num <= 10 ? "alto" : num <= 25 ? "médio" : "baixo";
  return (
    <div className={`gap-chip gap-${tone}`}>
      <span>{label}</span>
      <strong>{num.toFixed(2)} p.p.</strong>
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
        {(["balanced", "tuned"] as ModelName[]).map((item) => (
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
  return (
    <section className="panel">
      <header className="panel-header"><h2>{title}</h2></header>
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
              <div className="group-row-title"><strong>Grupo {row.group}</strong><span>{isLeadership ? "Disputa pelo 1º lugar" : "Disputa por vaga no mata-mata"}</span></div>
              <div className="duel-line"><span>{leftName}</span><strong>{pct(leftPct)}</strong></div>
              <ProgressBar value={leftPct} />
              <div className="duel-line"><span>{rightName}</span><strong>{pct(rightPct)}</strong></div>
              <ProgressBar value={rightPct} />
              <GapChip label={isLeadership ? "Gap de liderança" : "Gap de classificação"} value={gap} tone={isLeadership ? "leadership" : "qualification"} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function SensitivityTable({ rows }: { rows: ModelSensitivityRow[] }) {
  const sorted = [...rows].sort((a, b) => b.abs_delta_winner_pct - a.abs_delta_winner_pct).slice(0, 8);
  return (
    <section className="panel wide">
      <header className="panel-header"><h2>Sensibilidade à calibração</h2><small>Diferença Modelo Ajustado vs Modelo Padrão</small></header>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Seleção</th><th>Grupo</th><th>Título padrão</th><th>Título ajustado</th><th>Delta título</th><th>Delta final</th><th>Delta semi</th><th>Delta R32</th></tr></thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.team}>
                <td>{row.team}</td><td>{row.group}</td><td>{pct(row.balanced_winner_pct)}</td><td>{pct(row.tuned_winner_pct)}</td>
                <td className={row.delta_winner_pct >= 0 ? "delta-positive" : "delta-negative"}>{pp(row.delta_winner_pct)}</td>
                <td className={row.delta_final_pct >= 0 ? "delta-positive" : "delta-negative"}>{pp(row.delta_final_pct)}</td>
                <td className={row.delta_semifinal_pct >= 0 ? "delta-positive" : "delta-negative"}>{pp(row.delta_semifinal_pct)}</td>
                <td className={row.delta_round32_pct >= 0 ? "delta-positive" : "delta-negative"}>{pp(row.delta_round32_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RiskCards({ riskText, leadership, qualification }: { riskText: string; leadership: GroupLeadershipRow[]; qualification: GroupQualificationRow[] }) {
  const top5 = riskText.match(/Concentracao dos 5 maiores favoritos ao titulo: ([0-9.,]+%)/)?.[1] ?? "n/d";
  const firstRisk = riskText.match(/Favoritos com maior risco antes do R32: ([^\n]+)/)?.[1]?.split(";")[0] ?? "n/d";
  return (
    <section className="panel wide">
      <header className="panel-header"><h2>Riscos globais</h2><ShieldAlert size={18} /></header>
      <div className="risk-grid">
        <MetricCard icon={<AlertTriangle size={18} />} label="Top 5 favoritos" value={top5} detail="Concentração do título" tone="warning" />
        <MetricCard icon={<Users size={18} />} label="Liderança mais aberta" value={`Grupo ${leadership[0]?.group ?? "n/d"}`} detail={leadership[0] ? `Gap ${pp(leadership[0].leadership_gap_pct)}` : "n/d"} />
        <MetricCard icon={<Users size={18} />} label="Classificação mais aberta" value={`Grupo ${qualification[0]?.group ?? "n/d"}`} detail={qualification[0] ? `Gap ${pp(qualification[0].qualification_gap_2v3_pct)}` : "n/d"} />
        <MetricCard icon={<ShieldAlert size={18} />} label="Maior risco pré-mata-mata" value={firstRisk.replace(" elim. grupo", "")} detail="Entre favoritos monitorados" tone="warning" />
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
        <div><strong>Status:</strong> {dashboard.status?.status ?? "n/d"}</div>
        <div><strong>Recomendação:</strong> {dashboard.status?.recommendation ?? "n/d"}</div>
        <div><strong>Melhor modelo pelo backtest:</strong> {dashboard.status?.best_backtest_model ?? "n/d"}</div>
        <div><strong>Última atualização:</strong> {latestReport ? `${formatDate(latestReport.modified_at)} (${latestReport.age_minutes} min)` : "n/d"}</div>
        <ul>{observations.map((item) => <li key={item}>{item}</li>)}</ul>
      </div>
    </section>
  );
}

function TeamsPage({ rows }: { rows: TeamProbability[] }) {
  const [query, setQuery] = useState("");
  const filtered = rows.filter((row) => normalizeText(row.team).includes(normalizeText(query)) || normalizeText(row.group).includes(normalizeText(query)));
  return (
    <section className="panel wide">
      <header className="panel-header"><h2>Seleções</h2><input className="search-input" placeholder="Buscar seleção ou grupo" value={query} onChange={(event) => setQuery(event.target.value)} /></header>
      <div className="table-wrap">
        <table>
          <thead><tr><th>#</th><th>Seleção</th><th>Grupo</th><th>Mata-mata</th><th>Oitavas</th><th>Quartas</th><th>Semi</th><th>Final</th><th>Título</th><th>Elim. grupo</th><th>Adversário no mata-mata</th></tr></thead>
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
                  <div className="team-line-meta"><span>1º {pct(row.group_winner_pct)}</span><span>Elim. {pct(row.group_eliminated_pct)}</span><span>Título {pct(row.winner_pct)}</span></div>
                </div>
              ))}
            </div>
            <footer className="group-card-footer">
              {lead && <GapChip label="Gap de liderança" value={lead.leadership_gap_pct} tone="leadership" />}
              {qual && <GapChip label="Gap de classificação" value={qual.qualification_gap_2v3_pct} tone="qualification" />}
            </footer>
          </article>
        );
      })}
    </section>
  );
}

function CalibrationPage({ global }: { global: GlobalReport }) {
  return (
    <section className="main-grid inner-grid">
      <SensitivityTable rows={global.model_sensitivity} />
      <section className="panel wide">
        <header className="panel-header"><h2>Modelo e calibração</h2></header>
        <div className="observations">
          <p>Use esta aba para enxergar quais seleções mudam mais quando o relatório usa o Modelo Ajustado.</p>
          <p><strong>Regra de leitura:</strong> probabilidades absolutas usam %, diferenças entre modelos usam p.p.</p>
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
    if (simulations < 100000 && ["workflow_team", "workflow_global"].includes(action)) {
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
  const backtest = latest("backtest");
  const tuning = latest("tune_weights");
  const dryRunOk = dryRun?.status === "succeeded";
  const updateOk = update?.status === "succeeded";
  const calibrationOk = backtest?.status === "succeeded" || tuning?.status === "succeeded";
  const actionLabel = (action: string) => actions.find((item) => item.action === action)?.label ?? action;
  const busy = Boolean(running || activeJob);
  const stepStatus = (items: (DashboardJob | undefined)[]) => {
    if (items.some((item) => item?.status === "running" || item?.status === "queued")) return "em andamento";
    if (items.some((item) => item?.status === "failed")) return "revisar";
    if (items.some((item) => item?.status === "succeeded")) return "concluído";
    return "pendente";
  };

  const stepGroups = [
    { number: 1, title: "Diagnóstico das fontes", status: stepStatus([latest("source_health_check"), dryRun]), detail: "Audita fontes e compara dados sem alterar arquivos.", actions: ["source_health_check", "dry_run_multisource"] },
    { number: 2, title: "Atualização dos dados", status: stepStatus([update]), detail: "Altera data/matches.json, cria snapshot e atualiza integridade dos grupos.", actions: ["update_results"], locked: !dryRunOk, lockReason: "Rode o dry-run sem erro antes de aplicar resultados." },
    { number: 3, title: "Calibração do modelo", status: stepStatus([backtest, tuning]), detail: "Valida o modelo e gera pesos recomendados sem sobrescrever os pesos padrão.", actions: ["backtest", "tune_weights"] },
    { number: 4, title: "Simulação e relatórios", status: stepStatus([latest("workflow_team"), latest("workflow_global")]), detail: updateOk || dryRunOk ? "Pronto para gerar probabilidades finais." : "Sem update recente registrado; revise dados antes do relatório final.", actions: ["workflow_team", "workflow_global"] },
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
        <div className="ops-form">
          <label>Time<input value={team} onChange={(event) => setTeam(event.target.value)} /></label>
          <label>Simulações<input type="number" min={1} max={500000} value={simulations} onChange={(event) => setSimulations(Number(event.target.value))} /></label>
          <label>Seed<input value={seed} onChange={(event) => setSeed(event.target.value)} /></label>
        </div>
        <div className="ops-state">
          <span>Dry-run: {dryRun?.status ?? "pendente"}</span><span>Update: {update?.status ?? "pendente"}</span><span>Calibração: {calibrationOk ? "ok" : "pendente"}</span><span>Fila: {activeJob ? `${activeJob.request.action} ${activeJob.status}` : "livre"}</span>
        </div>
        {mode === "recommended" ? (
          <div className="workflow-steps">
            {stepGroups.map((step) => (
              <article className={`workflow-step status-${step.status.replace(" ", "-")}`} key={step.number}>
                <div className="step-index">{step.number}</div>
                <div className="step-content">
                  <header><strong>{step.title}</strong><span>{step.status}</span></header>
                  <p>{step.detail}</p>{step.locked && <small>{step.lockReason}</small>}
                  <div className="step-actions">
                    {step.actions.map((action) => <button className="command-button" type="button" key={action} disabled={busy || Boolean(step.locked)} onClick={() => execute(action)}><Play size={15} />{running === action ? "Executando..." : actionLabel(action)}</button>)}
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

  const refreshData = useCallback(async (selectedModel: ModelName = model) => {
    setLoading(true); setError("");
    try {
      const [dashboardData, globalData, commandData] = await Promise.all([fetchDashboard(selectedModel), fetchGlobalReport(), fetchCommands()]);
      setDashboard(dashboardData); setGlobal(globalData); setActions(commandData.actions); setLastRefresh(new Date());
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
      <aside className="sidebar"><div className="brand"><Trophy size={24} /><span>Copa 2026</span></div><nav>{[{k:"dashboard",l:"Dashboard"},{k:"teams",l:"Seleções"},{k:"groups",l:"Grupos"},{k:"calibration",l:"Calibração"},{k:"operations",l:"Operações"}].map((item) => <button key={item.k} className={tab === item.k ? "active" : ""} type="button" onClick={() => setTab(item.k as TabKey)}>{item.l}</button>)}</nav></aside>
      <section className="content">
        <header className="topbar"><div><h1>Dashboard de Simulação</h1><p>Relatórios locais gerados pelo simulador Monte Carlo. {lastRefresh ? `Atualizado às ${formatDate(lastRefresh.toISOString())}.` : ""}</p></div><div className="topbar-actions"><ModelToggle model={model} onChange={setModel} available={dashboard.available_models ?? ["balanced", "tuned"]} /><button className="ghost-button" type="button" disabled={loading} onClick={() => refreshData(model)}><RefreshCw size={16} />{loading ? "Atualizando..." : "Atualizar dados"}</button></div></header>
        {tab !== "operations" && <section className="metrics-grid"><MetricCard icon={<Activity size={20} />} label="Simulações" value={String(dashboard.meta.simulations ?? "n/d")} detail={`Seed ${dashboard.meta.seed ?? "n/d"}`} /><MetricCard icon={<Trophy size={20} />} label="Favorito" value={selectedRows[0]?.team ?? "n/d"} detail={`${pct(selectedRows[0]?.winner_pct)} de título no ${modelLabels[model]}`} /><MetricCard icon={<BarChart3 size={20} />} label="Relatórios" value={String(dashboard.report_files.length)} detail="arquivos em output/" /><MetricCard icon={<Database size={20} />} label="Fonte" value="Local" detail="global reports + workflow" /></section>}
        {tab === "dashboard" && <section className="main-grid"><section className="panel wide"><header className="panel-header"><h2>Modelos de simulação</h2></header><div className="model-explanation"><p>O Modelo Padrão usa a configuração principal do simulador e serve como cenário mais estável.</p><p>O Modelo Ajustado usa pesos calibrados pelo backtest e pode reagir mais às partidas recentes.</p></div></section><RunObservations dashboard={dashboard} /><section className="panel wide"><header className="panel-header"><div><h2>Ranking por fase — {metricLabels[metric]}</h2><small>{metricHelp[metric]}</small></div><div className="mode-toggle phase-toggle">{(Object.keys(metricLabels) as MetricKey[]).map((key) => <button key={key} className={metric === key ? "active" : ""} type="button" onClick={() => setMetric(key)}>{metricLabels[key]}</button>)}</div></header><div className="chart-box"><ResponsiveContainer width="100%" height={280}><BarChart data={chartRows} layout="vertical" margin={{ left: 24, right: 24 }}><CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" tickFormatter={(value) => `${value}%`} /><YAxis type="category" dataKey="team" width={96} /><Tooltip formatter={(value) => pct(Number(value))} /><ReferenceLine x={10} stroke="#94a3b8" strokeDasharray="3 3" /><Bar dataKey="valor" fill="#2563eb" radius={[0, 4, 4, 0]} /></BarChart></ResponsiveContainer></div></section><RankingTable title="Mata-mata" rows={phaseRows(selectedRows, "round32_pct")} field="round32_pct" /><RankingTable title="Oitavas" rows={phaseRows(selectedRows, "round16_pct")} field="round16_pct" /><RankingTable title="Quartas" rows={phaseRows(selectedRows, "quarterfinal_pct")} field="quarterfinal_pct" /><RankingTable title="Semifinal" rows={phaseRows(selectedRows, "semifinal_pct")} field="semifinal_pct" /><RankingTable title="Final" rows={phaseRows(selectedRows, "final_pct")} field="final_pct" /><RankingTable title="Campeão" rows={phaseRows(selectedRows, "winner_pct")} field="winner_pct" /><GroupOutlook title="Liderança mais indefinida" rows={leadershipRows} mode="leadership" /><GroupOutlook title="Classificação mais indefinida" rows={qualificationRows} mode="qualification" /><RiskCards riskText={global.risk_report} leadership={leadershipRows} qualification={qualificationRows} /></section>}
        {tab === "teams" && <section className="main-grid"><TeamsPage rows={selectedRows} /></section>}
        {tab === "groups" && <section className="main-grid"><GroupsPage rows={selectedRows} leadership={leadershipRows} qualification={qualificationRows} /></section>}
        {tab === "calibration" && <CalibrationPage global={global} />}
        {tab === "operations" && <section className="main-grid"><OperationsPanel actions={actions} onJobFinished={() => refreshData(model)} /><section className="panel wide"><header className="panel-header"><h2>Relatórios disponíveis</h2><FileText size={18} /></header><div className="table-wrap"><table><thead><tr><th>Arquivo</th><th>Atualizado</th><th>Idade</th><th>Tamanho</th></tr></thead><tbody>{dashboard.reports.slice(0, 20).map((report) => <tr key={report.name}><td>{report.name}</td><td>{formatDate(report.modified_at)}</td><td>{report.age_minutes} min</td><td>{Math.round(report.size_bytes / 1024)} KB</td></tr>)}</tbody></table></div></section></section>}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
