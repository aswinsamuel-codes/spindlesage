// Typed client for the SpindleSage REST API (apps/api/app.py).

export type Role = "viewer" | "ingest" | "technician" | "maintenance_lead" | "admin";

export interface Me {
  user_id: string;
  role: Role;
  permissions: string[];
}

export interface Machine {
  machine_id: string;
  name: string;
  model: string;
  product_type: string;
  location: string;
  readings_buffered: number;
  last_reading_utc: string | null;
  pending_approvals: number;
}

export interface MaintenanceRecord {
  record_id: string;
  date: string;
  kind: string;
  component: string;
  description: string;
  outcome: string;
}

export interface MachineDetail extends Machine {
  commissioned: string;
  spindle_max_rpm: number;
  maintenance_history: MaintenanceRecord[];
}

export interface Reading {
  machine_id: string;
  timestamp: string;
  product_type: string;
  air_temperature_k: number;
  process_temperature_k: number;
  rotational_speed_rpm: number;
  torque_nm: number;
  tool_wear_min: number;
}

export interface TopFeature {
  feature: string;
  exceedance_band_widths: number;
  direction: "above" | "below";
}

export interface Anomaly {
  alarm: boolean;
  score: number;
  threshold: number;
  consecutive_exceedances: number;
  top_features: TopFeature[];
  samples: number;
}

export interface MachineStatus {
  machine_id: string;
  latest_reading: Reading | null;
  anomaly: Anomaly | null;
  pending_approvals: number;
}

export interface Finding {
  statement: string;
  evidence_ids: string[];
}

export interface ProposedAction {
  action_type: string;
  description: string;
  urgency: "routine" | "next_stop" | "immediate";
  evidence_ids: string[];
}

export interface Recommendation {
  machine_id: string;
  risk_level: "low" | "medium" | "high" | "unknown";
  summary: string;
  findings: Finding[];
  actions: ProposedAction[];
  uncertainties: string[];
}

export interface EvidenceItem {
  evidence_id: string;
  kind: string;
  title: string;
  content: Record<string, unknown>;
  source: string;
}

export interface GuardReport {
  passed: boolean;
  claims: number;
  uncited_claims: number;
  unknown_citations: number;
  issues: { code: string; severity: string; message: string }[];
}

export interface AgentResult {
  created_utc: string;
  machine_id: string;
  engine: string;
  primary_engine: string;
  fallback_reason: string | null;
  approval_status: "pending_approval" | "not_required";
  recommendation: Recommendation;
  guard: GuardReport;
  evidence: { machine_id: string; mode: string; as_of: string; items: EvidenceItem[] };
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "completed";

export interface Approval {
  id: string;
  recommendation_id: string;
  machine_id: string;
  action_index: number;
  action_type: string;
  urgency: string;
  description: string;
  evidence_ids: string[];
  status: ApprovalStatus;
  requested_by: string;
  created_utc: string;
  expires_utc: string;
  decided_by: string | null;
  decided_utc: string | null;
  decision_note: string | null;
  completed_by: string | null;
  completed_utc: string | null;
  completion_note: string | null;
}

export interface RecommendationSummary {
  id: string;
  machine_id: string;
  created_utc: string;
  requested_by: string;
  engine: string;
  mode: string;
  risk_level: Recommendation["risk_level"];
  approval_status: string;
  summary: string;
}

export interface StoredRecommendation extends Omit<RecommendationSummary, "summary"> {
  payload: AgentResult;
  approvals: Approval[];
}

export interface CreatedRecommendation extends AgentResult {
  recommendation_id: string;
  approvals: Approval[];
}

export interface AuditEvent {
  seq: number;
  ts_utc: string;
  actor: string;
  actor_role: string;
  action: string;
  subject_type: string;
  subject_id: string;
  details: Record<string, unknown>;
  hash: string;
}

export interface ChainCheck {
  ok: boolean;
  records: number;
  first_broken_seq: number | null;
  reason: string | null;
}

export interface Health {
  status: string;
  version: string;
  engine: string;
  data_nature: string;
  demo_scenario: string | null;
  machine_control: string;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const API_BASE: string = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "/api" : "");

export class ApiClient {
  constructor(
    private apiKey: string,
    private base: string = API_BASE,
    private fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await this.fetchImpl(`${this.base}${path}`, {
      method,
      headers: {
        "X-API-Key": this.apiKey,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string") detail = payload.detail;
        else if (Array.isArray(payload.detail)) detail = payload.detail.map((d: { msg: string }) => d.msg).join("; ");
      } catch {
        // Body was not JSON; keep the status text.
      }
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  }

  health = () => this.request<Health>("GET", "/health");
  me = () => this.request<Me>("GET", "/me");
  machines = () => this.request<Machine[]>("GET", "/machines");
  machine = (id: string) => this.request<MachineDetail>("GET", `/machines/${encodeURIComponent(id)}`);
  status = (id: string) => this.request<MachineStatus>("GET", `/machines/${encodeURIComponent(id)}/status`);
  telemetry = (id: string, limit = 240) =>
    this.request<{ readings: Reading[] }>("GET", `/machines/${encodeURIComponent(id)}/telemetry?limit=${limit}`);
  recommend = (id: string, mode: "full" | "sensor_only") =>
    this.request<CreatedRecommendation>("POST", `/machines/${encodeURIComponent(id)}/recommendations`, { mode });
  recommendations = (machineId?: string, limit = 10) =>
    this.request<RecommendationSummary[]>(
      "GET",
      `/recommendations?limit=${limit}${machineId ? `&machine_id=${encodeURIComponent(machineId)}` : ""}`,
    );
  recommendation = (id: string) => this.request<StoredRecommendation>("GET", `/recommendations/${encodeURIComponent(id)}`);
  approvals = (status?: ApprovalStatus) =>
    this.request<Approval[]>("GET", `/approvals${status ? `?status=${status}` : ""}`);
  decide = (id: string, verb: "approve" | "reject" | "complete", note?: string) =>
    this.request<Approval>("POST", `/approvals/${encodeURIComponent(id)}/${verb}`, { note: note || null });
  audit = (limit = 200) => this.request<AuditEvent[]>("GET", `/audit?limit=${limit}`);
  verifyAudit = () => this.request<ChainCheck>("GET", "/audit/verify");
}
