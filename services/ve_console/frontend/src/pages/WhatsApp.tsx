import { useSearchParams } from "react-router-dom";
import { Search, ChevronRight, MessagesSquare, ArrowUpRight } from "lucide-react";
import { apiGet } from "../api/client";
import type { WhatsAppData } from "../api/types";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { SummaryCards } from "../components/ui/SummaryCards";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { formatDateTime, titleCase } from "../lib/format";

export function WhatsAppPage() {
  const { session } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const q = searchParams.get("q") || "";
  const tab = searchParams.get("tab") || "outbound";
  const { data, status } = useLiveRefresh<WhatsAppData>(() =>
    apiGet(`/api/v1/whatsapp?q=${encodeURIComponent(q)}`),
  );

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSearchParams({ tab, q: String(form.get("q") || "") });
  }

  return (
    <AppShell session={session} title="WhatsApp" subtitle="Outbound delivery and inbound patient conversations." liveStatus={status}>
      {data && (
        <>
          <SummaryCards summary={data.summary} />
          <section className="content-section">
            <div className="section-toolbar whatsapp-toolbar">
              <div className="tabs">
                <a
                  href="?tab=outbound" className={tab !== "inbound" ? "active" : ""}
                  onClick={(e) => { e.preventDefault(); setSearchParams({ tab: "outbound", q }); }}
                >Outbound</a>
                <a
                  href="?tab=inbound" className={tab === "inbound" ? "active" : ""}
                  onClick={(e) => { e.preventDefault(); setSearchParams({ tab: "inbound", q }); }}
                >Inbox <span>{data.inbound.length}</span></a>
              </div>
              <form className="filters" onSubmit={onSubmit}>
                <input type="hidden" name="tab" value={tab} />
                <label className="search-field"><Search /><input name="q" defaultValue={q} placeholder="Search messages" /></label>
                <button className="button secondary" type="submit">Search</button>
              </form>
            </div>

            {tab === "inbound" ? (
              data.inbound.length ? (
                <div className="inbox-layout">
                  <div className="conversation-list">
                    {data.inbound.map((row) => (
                      <a href={row.campaign_id ? `/campaigns/${row.campaign_id}` : "#"} key={row.inbound_id}>
                        <span className="message-avatar">{row.from_number.slice(-2)}</span>
                        <span className="conversation-copy">
                          <span><strong>{row.patient_id || row.from_number}</strong><time>{formatDateTime(row.received_at)}</time></span>
                          <p>{row.body || `${titleCase(row.message_type)} message`}</p>
                          <small><Badge value={row.detected_intent} /> {row.campaign_id ? `Linked to ${row.campaign_id.slice(0, 10)}` : "Unattributed"}</small>
                        </span>
                        <ChevronRight />
                      </a>
                    ))}
                  </div>
                  <aside className="inbox-empty">
                    <MessagesSquare />
                    <strong>Patient conversations</strong>
                    <p>Select a linked reply to open its full campaign journey.</p>
                  </aside>
                </div>
              ) : <EmptyState title="Inbox is clear" text="New patient replies will arrive through the Meta webhook." />
            ) : data.outbound.length ? (
              <div className="table-frame">
                <table>
                  <thead>
                    <tr><th>Campaign</th><th>Patient / recipient</th><th>Source</th><th>Family</th><th>Sent</th><th>Status</th><th>Delivered</th><th>Read</th><th>Reply</th></tr>
                  </thead>
                  <tbody>
                    {data.outbound.map((row, i) => (
                      <tr key={row.wa_message_id || row.campaign_id || i}>
                        <td>
                          {row.campaign_id ? (
                            <a className="record-link" href={`/campaigns/${row.campaign_id}`}>{row.campaign_id.slice(0, 10)}<ArrowUpRight /></a>
                          ) : row.wa_message_id ? (
                            <a className="record-link" href={`/whatsapp/messages/${row.wa_message_id}`}>Manual test<ArrowUpRight /></a>
                          ) : <span className="muted">Manual test</span>}
                        </td>
                        <td>{row.patient_id || row.recipient_e164}</td>
                        <td><Badge value={row.source} /></td>
                        <td>{row.family ? <span className={`family family-${row.family.toLowerCase()}`}>{row.family}</span> : "-"}</td>
                        <td>{formatDateTime(row.dispatched_at)}</td>
                        <td><Badge value={row.status} /></td>
                        <td>{row.delivered ? <Badge value="delivered" /> : <span className="muted">Pending</span>}</td>
                        <td>{row.read ? <Badge value="read" /> : "-"}</td>
                        <td>{row.replied ? <Badge value="replied" /> : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState />}
          </section>
        </>
      )}
    </AppShell>
  );
}
