import { useState } from "react";
import { useParams } from "react-router-dom";
import {
  ArrowLeft, CheckCheck, Eye, Reply, CalendarCheck, Stethoscope,
  Target, AlertTriangle, CircleDollarSign, TrendingUp, TrendingDown, Clock,
  Send, MessageCircleReply,
} from "lucide-react";
import { apiGet, apiPost } from "../api/client";
import type { CampaignDetailData } from "../api/types";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { JourneyRail } from "../components/ui/JourneyRail";
import { formatDateTime, formatMoney, titleCase } from "../lib/format";

export function CampaignDetailPage() {
  const { campaignId = "" } = useParams();
  const { session } = useSession();
  const { data, status } = useLiveRefresh<CampaignDetailData>(() => apiGet(`/api/v1/campaigns/${campaignId}`));
  const [pending, setPending] = useState(false);
  const [refreshed, setRefreshed] = useState<CampaignDetailData | null>(null);
  const shown = refreshed ?? data;

  async function markOutcome(stage: "booked" | "attended", amount?: string) {
    setPending(true);
    try {
      const next = await apiPost<CampaignDetailData>(
        `/api/v1/campaigns/${campaignId}/outcome`,
        amount ? { stage, amount } : { stage },
      );
      setRefreshed(next);
    } finally {
      setPending(false);
    }
  }

  if (!shown) {
    return (
      <AppShell session={session} title="Campaign journey" subtitle="" liveStatus={status}>
        <EmptyState title="Loading…" text="Fetching this campaign's journey." />
      </AppShell>
    );
  }

  const { campaign, messages, inbound, bookings, revenues, explanation } = shown;
  const steps: [string, boolean][] = [
    ["Targeted", true],
    ["Sent", !!campaign.dispatched_at],
    ["Delivered", campaign.delivered],
    ["Read", campaign.read],
    ["Replied", campaign.replied],
    ["Booking requested", campaign.booking_requested],
    ["Booked", campaign.booked],
    ["Attended", campaign.attended],
  ];
  const showActions = campaign.treatment_arm !== "holdout" && (!campaign.booked || !campaign.attended);

  return (
    <AppShell session={session} title="Campaign journey" subtitle={`Patient ${campaign.patient_id} · ${campaignId}`} liveStatus={status}>
      <div className="detail-header">
        <a href="/campaigns" className="back-link"><ArrowLeft />Campaigns</a>
        <div className="detail-actions">
          <Badge value={campaign.treatment_arm} />
          <Badge value={campaign.attended ? "attended" : campaign.booked ? "booked" : "active"} />
        </div>
      </div>

      <JourneyRail steps={steps} />

      <div className="detail-grid">
        <section className="content-section detail-facts">
          <div className="section-heading"><div><h2>Campaign context</h2><span>Why this patient entered the workflow</span></div></div>
          <dl>
            <div><dt>Patient</dt><dd>{campaign.patient_id}</dd></div>
            <div><dt>Family</dt><dd><span className={`family family-${campaign.family.toLowerCase()}`}>{campaign.family}</span></dd></div>
            <div><dt>Rule</dt><dd>{campaign.rule_name || "-"}</dd></div>
            <div><dt>Priority</dt><dd>{(campaign.priority_score ?? 0).toFixed(2)}</dd></div>
            <div><dt>Channel</dt><dd>{titleCase(campaign.channel)}</dd></div>
            <div><dt>Template</dt><dd className="mono">{campaign.template_id || "-"}</dd></div>
            <div><dt>Created</dt><dd>{formatDateTime(campaign.created_at)}</dd></div>
            <div><dt>Dispatched</dt><dd>{formatDateTime(campaign.dispatched_at)}</dd></div>
          </dl>
          {campaign.rule_evidence && (
            <div className="evidence">
              <span>Rule evidence</span>
              <pre>{JSON.stringify(campaign.rule_evidence, null, 2)}</pre>
            </div>
          )}
          {explanation && (
            <div className="evidence">
              <span>Why this no-show score ({(explanation.predicted_score * 100).toFixed(0)}%)</span>
              <dl className="shap-list">
                {explanation.contributions.slice(0, 6).map((c) => (
                  <div className="shap-row" key={c.feature}>
                    <dt>{titleCase(c.feature)}<small>{String(c.patient_value)}</small></dt>
                    <dd className={c.shap_value > 0 ? "up" : "down"}>{c.shap_value > 0 ? "+" : ""}{c.shap_value.toFixed(3)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </section>

        <section className="content-section outcome-panel">
          <div className="section-heading"><div><h2>Attributed outcome</h2><span>Measured impact from this journey</span></div></div>
          <div className="outcome-value">
            <span>Recovered revenue</span>
            {revenues.length ? <strong>{formatMoney(campaign.revenue)}</strong> : <strong className="outcome-value-empty">No invoice recorded yet</strong>}
          </div>
          <div className="outcome-flags">
            <span className={campaign.delivered ? "on" : ""}><CheckCheck />Delivered</span>
            <span className={campaign.read ? "on" : ""}><Eye />Read</span>
            <span className={campaign.replied ? "on" : ""}><Reply />Replied</span>
            <span className={campaign.booked ? "on" : ""}><CalendarCheck />Booked</span>
            <span className={campaign.attended ? "on" : ""}><Stethoscope />Attended</span>
          </div>
          {showActions ? (
            <div className="outcome-actions">
              <span>No booking/attendance feed for this patient yet? Mark it manually once confirmed by phone or in person.</span>
              <div className="outcome-actions-buttons">
                {!campaign.booked && (
                  <form onSubmit={(e) => { e.preventDefault(); markOutcome("booked"); }}>
                    <button type="submit" className="button secondary" disabled={pending}><CalendarCheck />Mark as booked</button>
                  </form>
                )}
                {!campaign.attended && (
                  <form
                    className="outcome-attend-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const amount = (new FormData(e.currentTarget).get("amount") as string) || "";
                      markOutcome("attended", amount);
                    }}
                  >
                    <input type="number" name="amount" step="0.01" min="0" placeholder="Revenue $ (leave blank if unknown)" />
                    <button type="submit" className="button secondary" disabled={pending}><Stethoscope />Mark as attended</button>
                  </form>
                )}
              </div>
            </div>
          ) : campaign.treatment_arm === "holdout" ? (
            <div className="outcome-actions">
              <span>This is a holdout campaign — deliberately not contacted, so it can't be marked booked/attended. That would corrupt the causal comparison the holdout arm exists to measure.</span>
            </div>
          ) : null}
        </section>
      </div>

      <section className="content-section">
        <div className="section-heading"><div><h2>Model scores</h2><span>What the ranking engine used to prioritize this patient</span></div></div>
        <div className="score-card-grid">
          <article className="score-card accent-blue">
            <Target />
            <span className="score-card-label">Expected value</span>
            <strong>{campaign.expected_value_score != null ? campaign.expected_value_score.toFixed(3) : "-"}</strong>
            <small>Combined ranking score</small>
          </article>
          <article className={`score-card ${(campaign.noshow_score ?? 0) >= 0.5 ? "accent-coral" : "accent-green"}`}>
            <AlertTriangle />
            <span className="score-card-label">No-show risk</span>
            <strong>{campaign.noshow_score != null ? `${(campaign.noshow_score * 100).toFixed(0)}%` : "-"}</strong>
            {campaign.noshow_score != null ? (
              <span className="score-bar"><span style={{ width: `${Math.round(campaign.noshow_score * 100)}%` }} /></span>
            ) : <small>Not scored</small>}
          </article>
          <article className="score-card accent-green">
            <CalendarCheck />
            <span className="score-card-label">Booking propensity</span>
            <strong>{campaign.booking_propensity_score != null ? `${(campaign.booking_propensity_score * 100).toFixed(0)}%` : "-"}</strong>
            {campaign.booking_propensity_score != null ? (
              <span className="score-bar"><span style={{ width: `${Math.round(campaign.booking_propensity_score * 100)}%` }} /></span>
            ) : <small>Not scored</small>}
          </article>
          <article className="score-card accent-amber">
            <CircleDollarSign />
            <span className="score-card-label">Expected value / visit</span>
            <strong>{campaign.value_score != null ? formatMoney(campaign.value_score) : "-"}</strong>
            <small>Predicted revenue if booked</small>
          </article>
          <article className={`score-card ${(campaign.uplift_score ?? 0) > 0 ? "accent-green" : "accent-coral"}`}>
            {(campaign.uplift_score ?? 0) > 0 ? <TrendingUp /> : <TrendingDown />}
            <span className="score-card-label">Uplift (treated − control)</span>
            <strong>{campaign.uplift_score != null ? `${campaign.uplift_score > 0 ? "+" : ""}${campaign.uplift_score.toFixed(3)}` : "-"}</strong>
            <small>
              {campaign.uplift_score == null ? "Not scored" : campaign.uplift_score > 0 ? "Persuadable — worth contacting" : "Discounted 10x — outreach may not help"}
            </small>
          </article>
          <article className="score-card accent-blue">
            <Clock />
            <span className="score-card-label">Predicted days-to-book</span>
            <strong>{campaign.survival_score != null ? `${campaign.survival_score.toFixed(1)} d` : "-"}</strong>
            <small>{campaign.survival_score != null ? "Faster → less timing discount" : "Not scored (pre-model campaign)"}</small>
          </article>
        </div>
      </section>

      <div className="detail-grid timeline-grid">
        <section className="content-section">
          <div className="section-heading"><div><h2>Messages</h2><span>Provider and patient activity</span></div></div>
          {messages.length || inbound.length ? (
            <div className="timeline">
              {messages.map((row) => (
                <div key={row.wa_message_id}>
                  <span className="timeline-icon sent"><Send /></span>
                  <span><strong>WhatsApp accepted</strong><small>{row.wa_message_id}</small><time>{formatDateTime(row.created_at)}</time></span>
                </div>
              ))}
              {inbound.map((row) => (
                <div key={row.inbound_id}>
                  <span className="timeline-icon reply"><MessageCircleReply /></span>
                  <span><strong>Patient replied · {titleCase(row.detected_intent)}</strong><small>{row.body || row.message_type}</small><time>{formatDateTime(row.received_at)}</time></span>
                </div>
              ))}
            </div>
          ) : <EmptyState title="No message events" text="Message provider IDs and patient replies appear here." />}
        </section>
        <section className="content-section">
          <div className="section-heading"><div><h2>Bookings and revenue</h2><span>Attributed conversion records</span></div></div>
          {bookings.length || revenues.length ? (
            <div className="timeline">
              {bookings.map((row) => (
                <div key={row.booking_id}>
                  <span className="timeline-icon booking"><CalendarCheck /></span>
                  <span><strong>{titleCase(row.status)} · {row.booking_id}</strong><small>Appointment {formatDateTime(row.appointment_date)}</small><time>Recorded {formatDateTime(row.created_at)}</time></span>
                </div>
              ))}
              {revenues.map((row) => (
                <div key={row.invoice_id}>
                  <span className="timeline-icon revenue"><CircleDollarSign /></span>
                  <span><strong>{formatMoney(row.amount, row.currency)} · {row.paid ? "Paid" : "Unpaid"}</strong><small>Invoice {row.invoice_id}</small><time>{formatDateTime(row.occurred_at)}</time></span>
                </div>
              ))}
            </div>
          ) : <EmptyState title="No conversion yet" text="Attributed bookings and billing events appear here." />}
        </section>
      </div>
    </AppShell>
  );
}
