import { ArrowRight, ChevronRight, ScanSearch, Send, MessageCircleReply, CalendarCheck } from "lucide-react";
import { apiGet } from "../api/client";
import type { OverviewData } from "../api/types";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { formatMoney, formatNumber, formatPercent, formatDateTime, titleCase } from "../lib/format";

function fetchOverview() {
  return apiGet<OverviewData>("/api/v1/overview");
}

export function OverviewPage() {
  const { session } = useSession();
  const { data, status } = useLiveRefresh(fetchOverview);

  return (
    <AppShell
      session={session}
      title="Clinic performance"
      subtitle="From identified opportunity to recovered revenue."
      liveStatus={status}
    >
      {!data ? (
        <EmptyState title="Loading…" text="Fetching the latest clinic metrics." />
      ) : (
        <>
          <section className="metric-grid overview-metrics">
            <article className="metric-card accent-green">
              <span className="metric-label">Recovered revenue</span>
              <strong>{formatMoney(data.metrics.revenue)}</strong>
              <small>Attributed paid invoices</small>
            </article>
            <article className="metric-card accent-blue">
              <span className="metric-label">Attributed bookings</span>
              <strong>{formatNumber(data.metrics.bookings)}</strong>
              <small>{formatPercent(data.metrics.booking_rate)} of campaigns</small>
            </article>
            <article className="metric-card accent-coral">
              <span className="metric-label">Attended visits</span>
              <strong>{formatNumber(data.metrics.attended)}</strong>
              <small>Completed appointments</small>
            </article>
            <article className="metric-card accent-amber">
              <span className="metric-label">Return on outreach</span>
              <strong>{formatPercent(data.metrics.roi)}</strong>
              <small>{formatMoney(data.metrics.spend)} estimated spend</small>
            </article>
          </section>

          <div className="dashboard-grid">
            <section className="content-section funnel-panel">
              <div className="section-heading">
                <div><h2>Engagement funnel</h2><span>Treated campaign progression</span></div>
                <a href="/campaigns">View campaigns<ArrowRight /></a>
              </div>
              <div className="funnel">
                {Object.entries(data.funnel).map(([key, value]) => (
                  <div className="funnel-row" key={key}>
                    <span>{titleCase(key)}</span>
                    <div><i style={{ width: `${data.funnel_max ? (value / data.funnel_max) * 100 : 0}%` }} /></div>
                    <strong>{formatNumber(value)}</strong>
                  </div>
                ))}
              </div>
            </section>

            <section className="content-section snapshot-panel">
              <div className="section-heading"><div><h2>Pipeline snapshot</h2><span>Current clinic inventory</span></div></div>
              <div className="snapshot-list">
                <a href="/opportunities">
                  <span className="snapshot-icon green"><ScanSearch /></span>
                  <span><strong>{formatNumber(data.metrics.opportunities)}</strong><small>Opportunities identified</small></span>
                  <ChevronRight />
                </a>
                <a href="/campaigns">
                  <span className="snapshot-icon blue"><Send /></span>
                  <span><strong>{formatNumber(data.metrics.dispatched)}</strong><small>Campaigns dispatched</small></span>
                  <ChevronRight />
                </a>
                <a href="/whatsapp?tab=inbound">
                  <span className="snapshot-icon green"><MessageCircleReply /></span>
                  <span><strong>{formatNumber(data.metrics.booking_requests)}</strong><small>Booking requests received</small></span>
                  <ChevronRight />
                </a>
                <a href="/bookings">
                  <span className="snapshot-icon coral"><CalendarCheck /></span>
                  <span><strong>{formatNumber(data.metrics.bookings)}</strong><small>Bookings linked</small></span>
                  <ChevronRight />
                </a>
              </div>
            </section>
          </div>

          <div className="dashboard-grid lower-grid">
            <section className="content-section">
              <div className="section-heading">
                <div><h2>Recent campaigns</h2><span>Latest journeys entering the pipeline</span></div>
                <a href="/campaigns">See all<ArrowRight /></a>
              </div>
              <div className="compact-list">
                {data.recent_campaigns.map((row) => (
                  <a href={`/campaigns/${row.campaign_id}`} key={row.campaign_id}>
                    <span className={`family family-${row.family.toLowerCase()}`}>{row.family}</span>
                    <span className="compact-main">
                      <strong>{row.patient_id}</strong>
                      <small>{formatDateTime(row.created_at)}</small>
                    </span>
                    <Badge value={row.treatment_arm} />
                    <Badge value={row.status} />
                    <ChevronRight />
                  </a>
                ))}
              </div>
            </section>

            <section className="content-section">
              <div className="section-heading">
                <div><h2>Patient replies</h2><span>Latest inbound WhatsApp activity</span></div>
                <a href="/whatsapp?tab=inbound">Open inbox<ArrowRight /></a>
              </div>
              {data.recent_inbound.length === 0 ? (
                <div className="compact-empty">
                  <EmptyState title="No inbound replies yet" text="Patient replies will appear here after webhook delivery." />
                </div>
              ) : (
                <div className="message-list">
                  {data.recent_inbound.map((row) => (
                    <a href={row.campaign_id ? `/campaigns/${row.campaign_id}` : "/whatsapp?tab=inbound"} key={row.inbound_id}>
                      <span className="message-avatar">{row.from_number.slice(-2)}</span>
                      <span>
                        <strong>{row.from_number}</strong>
                        <p>{row.body || "Non-text message"}</p>
                        <small>{formatDateTime(row.received_at)}</small>
                      </span>
                      <Badge value={row.detected_intent} />
                    </a>
                  ))}
                </div>
              )}
            </section>
          </div>
        </>
      )}
    </AppShell>
  );
}
