export interface SessionUser {
  name: string;
  roles: string[];
}

export interface SessionInfo {
  user: SessionUser;
  clinic: { id: string; name: string };
}

export interface OverviewMetrics {
  opportunities: number;
  campaigns: number;
  dispatched: number;
  bookings: number;
  attended: number;
  booking_requests: number;
  revenue: number;
  spend: number;
  roi: number;
  booking_rate: number;
}

export interface OverviewFunnel {
  treated: number;
  sent: number;
  delivered: number;
  read: number;
  replied: number;
  booking_requested: number;
  booked: number;
  attended: number;
}

export interface RecentCampaign {
  campaign_id: string;
  patient_id: string;
  family: string;
  treatment_arm: string;
  created_at: string;
  status: string;
}

export interface RecentInbound {
  inbound_id: string;
  from_number: string;
  body: string | null;
  detected_intent: string | null;
  campaign_id: string | null;
  received_at: string;
}

export interface OverviewData {
  metrics: OverviewMetrics;
  funnel: OverviewFunnel;
  funnel_max: number;
  recent_campaigns: RecentCampaign[];
  recent_inbound: RecentInbound[];
}

export interface ListPageData {
  rows: Record<string, unknown>[];
  summary: Record<string, number>;
  filters: Record<string, string>;
}

export interface OpportunitiesData extends ListPageData {
  families: string[];
}

export interface Campaign {
  campaign_id: string;
  patient_id: string;
  clinic_id: string;
  family: string;
  channel: string;
  template_id: string | null;
  treatment_arm: string;
  created_at: string | null;
  dispatched_at: string | null;
  priority_score: number | null;
  rule_name: string | null;
  rule_evidence: Record<string, unknown> | null;
  delivered: boolean;
  read: boolean;
  replied: boolean;
  booked: boolean;
  attended: boolean;
  booking_requested: boolean;
  revenue: number;
  noshow_score: number | null;
  booking_propensity_score: number | null;
  value_score: number | null;
  uplift_score: number | null;
  survival_score: number | null;
  expected_value_score: number | null;
}

export interface ShapContribution {
  feature: string;
  patient_value: unknown;
  shap_value: number;
}

export interface Explanation {
  base_value: number;
  predicted_score: number;
  contributions: ShapContribution[];
}

export interface OutboundMessage {
  wa_message_id: string | null;
  campaign_id: string | null;
  patient_id: string | null;
  family: string | null;
  recipient_e164: string | null;
  source: string;
  status: string;
  dispatched_at: string | null;
  message_count: number;
  delivered: boolean;
  read: boolean;
  replied: boolean;
}

export interface InboundMessage {
  inbound_id: string;
  from_number: string;
  patient_id: string | null;
  campaign_id: string | null;
  message_type: string;
  body: string | null;
  detected_intent: string;
  received_at: string;
}

export interface WhatsAppData {
  outbound: OutboundMessage[];
  inbound: InboundMessage[];
  summary: Record<string, number>;
}

export interface MessageDetailData {
  message: {
    wa_message_id: string;
    recipient_e164: string;
    source: string;
    status: string;
    template_name: string | null;
    sent_at: string | null;
    updated_at: string | null;
    replied_at: string | null;
    replied: boolean;
    patient_id: string | null;
    campaign_id: string | null;
    treatment_arm: string | null;
    family: string | null;
  };
  inbound: { inbound_id: string; from_number: string; message_type: string; body: string | null; detected_intent: string; received_at: string }[];
  delivered: boolean;
  read: boolean;
  replied: boolean;
}

export interface HoldoutArmRow {
  treatment_arm: string;
  campaigns: number;
  dispatched: number;
  booked: number;
  attended: number;
  revenue: number;
  booking_rate: number;
  attendance_rate: number;
}

export interface HoldoutData {
  rows: HoldoutArmRow[];
  stats: {
    treated_rate: number;
    holdout_rate: number;
    absolute_lift: number;
    relative_lift: number;
    holdout_dispatches: number;
  };
}

export interface DriftInfo {
  psi: number | null;
  status: string;
  baseline_n: number;
  current_n: number;
  window_days: number;
}

export interface QualityInfo {
  status: string;
  n?: number;
  precision?: number;
  recall?: number;
  f1?: number;
  auc?: number | null;
}

export interface ModelVersion {
  name: string;
  version: number;
  creation_timestamp: string;
  current_stage: string | null;
  status: string;
  run_id: string | null;
  run_status: string | null;
}

export interface ModelCard {
  model_name: string;
  label: string;
  score_column: string | null;
  versions: ModelVersion[];
  headline_version: ModelVersion | null;
  metrics: Record<string, number>;
  drift: DriftInfo | null;
  quality_synthetic: QualityInfo | null;
  quality_real: QualityInfo | null;
}

export interface ModelAlert {
  label: string;
  detail: string;
}

export interface ModelsData {
  model_cards: ModelCard[];
  versions: ModelVersion[];
  mlflow_url: string;
  feature_drift: Record<string, DriftInfo | null>;
  alerts: ModelAlert[];
}

export interface ServiceStatus {
  name: string;
  role: string;
  ok: boolean;
  url: string | null;
}

export interface OperationsData {
  services: ServiceStatus[];
  healthy: number;
  alerts: ModelAlert[];
}

export interface CampaignDetailData {
  campaign: Campaign;
  messages: { wa_message_id: string; created_at: string }[];
  inbound: { inbound_id: string; from_number: string; message_type: string; body: string | null; detected_intent: string; received_at: string }[];
  bookings: { booking_id: string; appointment_date: string; status: string; created_at: string }[];
  revenues: { invoice_id: string; booking_id: string; amount: number; currency: string; paid: boolean; occurred_at: string }[];
  explanation: Explanation | null;
}

