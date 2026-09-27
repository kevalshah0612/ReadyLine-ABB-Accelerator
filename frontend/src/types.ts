export type User = {
  id: string;
  username: string;
  role: "admin" | "supervisor" | "planner" | "technician";
};
export type Status = {
  setup_required: boolean;
  provider_configured: boolean;
  model: string;
  telemetry_mode: string;
};
export type Reading = {
  id: string;
  asset_id: string;
  observed_at: string;
  vibration: number;
  temperature: number;
  load: number;
  source: string;
};
export type Conclusion = {
  summary: string;
  observations: string[];
  disposition: string;
  uncertainty: string;
};
export type WindowRow = {
  id: string;
  area: string;
  starts_at: string;
  ends_at: string;
  production_fraction: number;
  technicians: number;
  permit_ready: number;
  feasible?: boolean;
  reasons?: string[];
  estimated_disruption_cost?: number;
};
export type Priority = {
  score: number;
  level: string;
  review_deadline: string;
  formula: string;
};
export type Evidence = {
  inspect_telemetry?: {
    condition_score: number;
    vibration_slope_per_hour: number;
    sample_count: number;
    limitations: string;
  };
  find_peer_evidence?: {
    peers: {
      asset_id: string;
      name: string;
      similarity: number;
      confirmed_repairs: { id: string; feedback: { finding: string } }[];
    }[];
    confirmed_peer_repairs: number;
    method: string;
  };
  calculate_priority?: Priority;
  evaluate_windows?: {
    windows: WindowRow[];
    selected_window_id: string | null;
    policy: string;
  };
};
export type Run = {
  id: string;
  asset_id: string;
  status: string;
  created_at: string;
  error: string | null;
  result: { agents: Record<string, Conclusion>; evidence: Evidence } | null;
};
export type Asset = {
  id: string;
  name: string;
  area: string;
  equipment_class: string;
  rated_power: number;
  duty_cycle: number;
  safety: number;
  production_impact: number;
  hourly_cost: number;
  vibration_limit: number;
  temperature_limit: number;
  latest: Reading | null;
  latest_run: Run | null;
};
export type EventRow = {
  id: number;
  created_at: string;
  agent: string;
  kind: string;
  payload: Record<string, unknown>;
};
export type Part = {
  id: string;
  name: string;
  stock: number;
  reserved: number;
};
export type Procedure = {
  id: string;
  equipment_class: string;
  title: string;
  duration_hours: number;
  parts: { part_id: string; quantity: number }[];
  steps: string[];
  source: string;
};
export type Order = {
  id: string;
  run_id: string;
  asset_id: string;
  status: string;
  window_id: string;
  created_at: string;
  approved_at: string | null;
  completed_at: string | null;
  plan: {
    procedure: Procedure;
    parts: {
      part_id: string;
      name: string;
      quantity: number;
      available: number;
      ready: boolean;
    }[];
    priority: Priority;
    agent_summary: string;
  };
  feedback: {
    finding: string;
    actual_hours: number;
    post_vibration: number;
  } | null;
};
export type Resources = {
  parts: Part[];
  procedures: Procedure[];
  windows: WindowRow[];
};
export type AuditRow = {
  id: number;
  created_at: string;
  actor: string;
  action: string;
  entity_id: string;
  detail: Record<string, unknown>;
};
