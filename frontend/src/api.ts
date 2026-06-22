import type { CommandAction, CommandResult, DashboardJob, DashboardSummary, GlobalReport, ModelName, ReportFile, WorkflowReport } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`Erro ${response.status} ao carregar ${path}`);
  }
  return response.json() as Promise<T>;
}

export function fetchDashboard(model: ModelName = "balanced"): Promise<DashboardSummary> {
  return getJson<DashboardSummary>(`/api/dashboard?model=${model}`);
}

export function fetchGlobalReport(): Promise<GlobalReport> {
  return getJson<GlobalReport>("/api/global");
}

export function fetchCommands(): Promise<{ actions: CommandAction[] }> {
  return getJson<{ actions: CommandAction[] }>("/api/commands");
}

export function fetchLatestWorkflow(): Promise<WorkflowReport> {
  return getJson<WorkflowReport>("/api/workflows/latest");
}

export function fetchReports(): Promise<{ reports: ReportFile[] }> {
  return getJson<{ reports: ReportFile[] }>("/api/reports");
}

export async function runCommand(payload: {
  action: string;
  team: string;
  simulations: number;
  seed: number | null;
}): Promise<CommandResult> {
  const response = await fetch(`${API_BASE}/api/commands/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Erro ${response.status} ao executar comando`);
  }
  return response.json() as Promise<CommandResult>;
}

export async function submitJob(payload: {
  action: string;
  team: string;
  simulations: number;
  seed: number | null;
}): Promise<DashboardJob> {
  const response = await fetch(`${API_BASE}/api/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`Erro ${response.status} ao iniciar job`);
  }
  return response.json() as Promise<DashboardJob>;
}

export function fetchJob(jobId: string): Promise<DashboardJob> {
  return getJson<DashboardJob>(`/api/jobs/${jobId}`);
}

export async function retryJob(jobId: string): Promise<DashboardJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/retry`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Erro ${response.status} ao reenfileirar job`);
  }
  return response.json() as Promise<DashboardJob>;
}

export async function cancelJob(jobId: string): Promise<DashboardJob> {
  const response = await fetch(`${API_BASE}/api/jobs/${jobId}/cancel`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Erro ${response.status} ao cancelar job`);
  }
  return response.json() as Promise<DashboardJob>;
}

export function fetchJobs(): Promise<{ jobs: DashboardJob[] }> {
  return getJson<{ jobs: DashboardJob[] }>("/api/jobs");
}

export function fetchMarketReport(): Promise<import("./types").MarketReport> {
  return getJson<import("./types").MarketReport>("/api/market");
}
