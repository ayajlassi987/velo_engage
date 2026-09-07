import {
  Database, RadioTower, Workflow, ChartNoAxesCombined, Share2, ShieldCheck, KeyRound,
  ArrowUpRight, Braces, BrainCircuit,
} from "lucide-react";
import { apiGet } from "../api/client";
import type { OperationsData } from "../api/types";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";

const SERVICE_ICONS = [Database, RadioTower, Workflow, ChartNoAxesCombined, Share2, ShieldCheck, KeyRound];

function fetchOperations() {
  return apiGet<OperationsData>("/api/v1/operations");
}

export function OperationsPage() {
  const { session } = useSession();
  const { data, status } = useLiveRefresh(fetchOperations);

  return (
    <AppShell session={session} title="System operations" subtitle="Live connectivity across the VeloDoc platform." liveStatus={status}>
      {data && (
        <>
          {data.alerts.length > 0 && (
            <section className="content-section">
              <div className="section-heading">
                <div><h2>Model alerts</h2><span>{data.alerts.length} signal{data.alerts.length !== 1 ? "s" : ""} needing attention — see <a href="/models">ML models</a> for detail</span></div>
              </div>
              <div style={{ padding: "0 18px 18px", display: "flex", flexDirection: "column", gap: 8 }}>
                {data.alerts.map((alert, i) => (
                  <div key={i}><Badge value="critical" /> <strong>{alert.label}</strong> — {alert.detail}</div>
                ))}
              </div>
            </section>
          )}

          <section className="operations-summary">
            <span className="health-ring"><strong>{data.healthy}</strong><small>of {data.services.length}</small></span>
            <div><h2>Platform connectivity</h2><p>Live checks from the console container to every core dependency.</p></div>
            <span className={`badge ${data.healthy === data.services.length ? "badge-ready" : "badge-warning"}`}>
              {data.healthy === data.services.length ? "All systems operational" : "Attention required"}
            </span>
          </section>

          <section className="service-grid">
            {data.services.map((service, i) => {
              const Icon = SERVICE_ICONS[i] ?? Database;
              return (
                <article className="service-card" key={service.name}>
                  <div className="service-head">
                    <span className="service-icon"><Icon /></span>
                    <span className={`service-state ${service.ok ? "healthy" : "offline"}`}><i />{service.ok ? "Healthy" : "Unavailable"}</span>
                  </div>
                  <h2>{service.name}</h2>
                  <p>{service.role}</p>
                  {service.url ? (
                    <a href={service.url} target="_blank" rel="noreferrer">Open service<ArrowUpRight /></a>
                  ) : <span className="internal-label">Internal service</span>}
                </article>
              );
            })}
          </section>

          <section className="content-section quick-links">
            <div className="section-heading"><div><h2>Developer endpoints</h2><span>Useful links for local operations</span></div></div>
            <div>
              <a href="http://localhost:8080" target="_blank" rel="noreferrer">
                <Workflow /><span><strong>Temporal UI</strong><small>Workflow history and schedules</small></span><ArrowUpRight />
              </a>
              <a href="http://localhost:5000" target="_blank" rel="noreferrer">
                <BrainCircuit /><span><strong>MLflow</strong><small>Experiments and model registry</small></span><ArrowUpRight />
              </a>
              <a href="/api/docs">
                <Braces /><span><strong>Console API</strong><small>FastAPI endpoint reference</small></span><ArrowUpRight />
              </a>
            </div>
          </section>
        </>
      )}
    </AppShell>
  );
}
