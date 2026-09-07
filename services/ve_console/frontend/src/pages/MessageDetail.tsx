import { useParams } from "react-router-dom";
import { ArrowLeft, ArrowUpRight, UserCheck, Split, Send, MessageCircleReply, FlaskConical } from "lucide-react";
import { apiGet } from "../api/client";
import type { MessageDetailData } from "../api/types";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { JourneyRail } from "../components/ui/JourneyRail";
import { formatDateTime, titleCase } from "../lib/format";

export function MessageDetailPage() {
  const { waMessageId = "" } = useParams();
  const { session } = useSession();
  const { data, status } = useLiveRefresh<MessageDetailData>(() => apiGet(`/api/v1/whatsapp/messages/${waMessageId}`));

  if (!data) {
    return (
      <AppShell session={session} title="WhatsApp message" subtitle="" liveStatus={status}>
        <EmptyState title="Loading…" text="Fetching this message's details." />
      </AppShell>
    );
  }

  const { message, inbound, delivered, read, replied } = data;
  const steps: [string, boolean][] = [["Accepted", true], ["Delivered", delivered], ["Read", read], ["Replied", replied]];

  return (
    <AppShell session={session} title="WhatsApp message" subtitle={`Recipient ${message.recipient_e164}`} liveStatus={status}>
      <div className="detail-header">
        <a href="/whatsapp" className="back-link"><ArrowLeft />WhatsApp</a>
        <div className="detail-actions"><Badge value={message.source} /><Badge value={message.status} /></div>
      </div>

      <JourneyRail steps={steps} />

      <div className="detail-grid">
        <section className="content-section detail-facts">
          <div className="section-heading"><div><h2>Message details</h2><span>Provider record for this WhatsApp send</span></div></div>
          <dl>
            <div><dt>Recipient</dt><dd>{message.recipient_e164}</dd></div>
            <div><dt>Source</dt><dd>{titleCase(message.source)}</dd></div>
            <div><dt>Template</dt><dd className="mono">{message.template_name || "-"}</dd></div>
            <div><dt>Status</dt><dd><Badge value={message.status} /></dd></div>
            <div><dt>Sent</dt><dd>{formatDateTime(message.sent_at)}</dd></div>
            <div><dt>Last update</dt><dd>{formatDateTime(message.updated_at)}</dd></div>
            <div><dt>Replied</dt><dd>{formatDateTime(message.replied_at)}</dd></div>
            <div><dt>Patient</dt><dd>{message.patient_id || "Not assigned"}</dd></div>
          </dl>
          <div className="evidence"><span>Meta message ID</span><pre>{message.wa_message_id}</pre></div>
        </section>

        <section className="content-section outcome-panel">
          <div className="section-heading"><div><h2>Campaign connection</h2><span>Attribution context for this message</span></div></div>
          {message.campaign_id ? (
            <>
              <div className="outcome-value">
                <span>Linked campaign</span>
                <a className="record-link" href={`/campaigns/${message.campaign_id}`}>{message.campaign_id}<ArrowUpRight /></a>
              </div>
              <div className="outcome-flags">
                <span className="on"><UserCheck />{message.patient_id}</span>
                <span className="on"><Split />{titleCase(message.treatment_arm || "")}</span>
              </div>
            </>
          ) : (
            <div className="empty-state compact-empty">
              <FlaskConical />
              <strong>Standalone manual test</strong>
              <span>This provider test was sent directly, so it has no campaign, opportunity, booking, or revenue attribution.</span>
            </div>
          )}
        </section>
      </div>

      <section className="content-section">
        <div className="section-heading"><div><h2>Conversation activity</h2><span>Replies attributed to this outbound message</span></div></div>
        {inbound.length ? (
          <div className="timeline">
            <div>
              <span className="timeline-icon sent"><Send /></span>
              <span><strong>WhatsApp message accepted</strong><small>{message.template_name || "Template message"}</small><time>{formatDateTime(message.sent_at)}</time></span>
            </div>
            {inbound.map((row) => (
              <div key={row.inbound_id}>
                <span className="timeline-icon reply"><MessageCircleReply /></span>
                <span><strong>Recipient replied · {titleCase(row.detected_intent)}</strong><small>{row.body || row.message_type}</small><time>{formatDateTime(row.received_at)}</time></span>
              </div>
            ))}
          </div>
        ) : <EmptyState title="No reply yet" text="An inbound reply attributed to this message will appear here." />}
      </section>
    </AppShell>
  );
}
