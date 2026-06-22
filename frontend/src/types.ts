export type ModelName = "balanced" | "tuned" | "market_calibrated";

export type TeamProbability = {
  model?: ModelName;
  team: string;
  group: string;
  winner_pct: number;
  final_pct: number;
  semifinal_pct: number;
  quarterfinal_pct: number;
  round16_pct: number;
  round32_pct: number;
  group_winner_pct: number;
  group_runner_up_pct: number;
  best_third_pct: number;
  group_eliminated_pct: number;
  most_common_round32_opponent?: string;
  most_common_elimination_stage?: string;
};

export type ReportFile = {
  name: string;
  size_bytes: number;
  modified_at: string;
  age_minutes: number;
  is_stale: boolean;
};

export type WorkflowStatus = {
  status: string;
  recommendation?: string;
  best_backtest_model?: string;
  observations: string[];
};

export type WorkflowStep = {
  name: string;
  status: string;
  message: string;
  outputs?: string[];
};

export type WorkflowReport = {
  workflow?: string;
  status?: string;
  best_backtest_model?: string;
  steps?: WorkflowStep[];
  metrics?: Record<string, unknown>;
  outputs?: string[];
  recommendation?: string;
  report?: string;
  latest_report?: string;
};

export type DashboardSummary = {
  model: ModelName;
  available_models: ModelName[];
  meta: {
    simulations?: number;
    seed?: number | null;
    model?: ModelName;
  };
  top_title: TeamProbability[];
  top_final: TeamProbability[];
  top_semifinal: TeamProbability[];
  report_files: string[];
  reports: ReportFile[];
  latest_workflow?: WorkflowReport;
  status: WorkflowStatus;
};

export type GroupLeadershipRow = {
  model: ModelName;
  group: string;
  favorite_to_win_group: string;
  favorite_group_winner_pct: number;
  second_group_winner_candidate: string;
  second_group_winner_pct: number;
  leadership_gap_pct: number;
  leadership_uncertainty_score: number;
  teams_by_group_winner_pct: string;
};

export type GroupQualificationRow = {
  model: ModelName;
  group: string;
  second_round32_candidate: string;
  second_round32_pct: number;
  third_round32_candidate: string;
  third_round32_pct: number;
  qualification_gap_2v3_pct: number;
  qualification_uncertainty_score: number;
  teams_by_round32_pct: string;
};

export type ModelSensitivityRow = {
  team: string;
  group: string;
  balanced_winner_pct: number;
  tuned_winner_pct: number;
  delta_winner_pct: number;
  delta_final_pct: number;
  delta_semifinal_pct: number;
  delta_round32_pct: number;
  delta_group_eliminated_pct: number;
  abs_delta_winner_pct: number;
};

export type GlobalReport = {
  title_ranking: TeamProbability[];
  stage_probabilities: TeamProbability[];
  group_outlook: Record<string, unknown>[];
  group_leadership: GroupLeadershipRow[];
  group_qualification: GroupQualificationRow[];
  model_sensitivity: ModelSensitivityRow[];
  risk_report: string;
  latest_report: string;
};

export type CommandAction = {
  action: string;
  label: string;
};

export type CommandResult = {
  action: string;
  command: string;
  ok: boolean;
  returncode: number;
  stdout: string;
  stderr: string;
  started_at: string;
  finished_at: string;
};

export type DashboardJob = {
  id: string;
  request: {
    action: string;
    team: string;
    simulations: number;
    seed: number | null;
  };
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  created_at: string;
  retried_from?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  result?: CommandResult | null;
  error?: string | null;
};

export type MarketAnchorRow = {
  team: string;
  group: string;
  model_winner_pct: number;
  market_winner_pct: number | null;
  anchor_winner_pct: number;
  delta_model_vs_market_pp: number | null;
  delta_anchor_vs_market_pp: number | null;
  adjustment_applied_pp: number;
  anchor_reason: string;
  market_rank: number | null;
  model_rank: number | null;
  anchor_rank: number | null;
};

export type MarketAlert = {
  team: string;
  group: string;
  model_winner_pct: number;
  market_winner_pct: number;
  anchor_winner_pct: number;
  delta_pp: number;
  direction: "above" | "below";
  severity: "high" | "medium" | "low";
};

export type MarketAnchorSummary = {
  teams_with_odds: number;
  teams_without_odds: number;
  overround_pct: number | null;
  biggest_above_market: { team: string; delta_pp: number } | null;
  biggest_below_market: { team: string; delta_pp: number } | null;
  alerts_count: number;
  alerts: { team: string; delta_pp: number; direction: "above" | "below" }[];
};

export type MarketAnchorReport = {
  market_mode: string;
  generated_at: string;
  summary: MarketAnchorSummary;
  rows: MarketAnchorRow[];
};

export type MarketAlertsReport = {
  generated_at: string;
  threshold_pp: number;
  alert_count: number;
  alerts: MarketAlert[];
};

export type MarketComparisonRow = {
  team: string;
  model: string;
  model_winner_pct: number;
  market_winner_pct: number | null;
  delta_pp: number | null;
  interpretation: string;
};

export type MarketReport = {
  anchor: MarketAnchorReport;
  alerts: MarketAlertsReport;
  odds_summary: {
    teams: number;
    overround_pct: number;
    last_updated: string | null;
  };
  comparison: {
    rows_with_odds: MarketComparisonRow[];
    rows_without_odds: MarketComparisonRow[];
  };
};
