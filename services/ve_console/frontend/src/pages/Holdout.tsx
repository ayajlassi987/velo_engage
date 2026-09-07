import { FlaskConical } from "lucide-react";
import { apiGet } from "../api/client";
import type { HoldoutData } from "../api/types";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { formatMoney, formatPercent, titleCase } from "../lib/format";

function fetchHoldout() {
  return apiGet<HoldoutData>("/api/v1/holdout");
}

export function HoldoutPage() {
  const { session } = useSession();
  const { data, status } = useLiveRefresh(fetchHoldout);

  return (
    <AppShell session={session} title="Holdout analysis" subtitle="Causal comparison of treated and naturally converting patients." liveStatus={status}>
      {data && (
        <>
          <section className="metric-grid">
            <article className="metric-card accent-green">
              <span className="metric-label">Treated booking rate</span>
              <strong>{formatPercent(data.stats.treated_rate)}</strong>
              <small>Patients receiving outreach</small>
            </article>
            <article className="metric-card accent-amber">
              <span className="metric-label">Holdout booking rate</span>
              <strong>{formatPercent(data.stats.holdout_rate)}</strong>
              <small>Natural conversion baseline</small>
            </article>
            <article className="metric-card accent-blue">
              <span className="metric-label">Absolute lift</span>
              <strong>{data.stats.absolute_lift.toFixed(1)} pp</strong>
              <small>Treated minus holdout</small>
            </article>
            <article className={`metric-card ${data.stats.holdout_dispatches === 0 ? "accent-green" : "accent-coral"}`}>
              <span className="metric-label">Holdout safety</span>
              <strong>{data.stats.holdout_dispatches}</strong>
              <small>{data.stats.holdout_dispatches === 0 ? "No accidental sends" : "Release blocked"}</small>
            </article>
          </section>

          <div className="experiment-grid">
            {data.rows.map((row) => (
              <section className={`content-section experiment-arm ${row.treatment_arm}`} key={row.treatment_arm}>
                <div className="arm-heading">
                  <div><span className="arm-dot" /><h2>{titleCase(row.treatment_arm)}</h2></div>
                  <Badge value={row.treatment_arm} />
                </div>
                <strong className="rate-number">{formatPercent(row.booking_rate)}</strong>
                <span className="rate-caption">booking conversion</span>
                <div className="conversion-bar"><span style={{ width: `${Math.min(row.booking_rate, 100)}%` }} /></div>
                <dl>
                  <div><dt>Campaigns</dt><dd>{row.campaigns.toLocaleString()}</dd></div>
                  <div><dt>Booked</dt><dd>{row.booked.toLocaleString()}</dd></div>
                  <div><dt>Attended</dt><dd>{row.attended.toLocaleString()}</dd></div>
                  <div><dt>Revenue</dt><dd>{formatMoney(row.revenue)}</dd></div>
                </dl>
              </section>
            ))}
          </div>

          <section className="content-section interpretation">
            <span className="interpretation-icon"><FlaskConical /></span>
            <div>
              <h2>Experiment interpretation</h2>
              <p>
                The treated arm is converting <strong>{data.stats.absolute_lift.toFixed(1)} percentage points</strong> above
                the holdout baseline, a relative lift of <strong>{formatPercent(data.stats.relative_lift)}</strong>. Holdout
                integrity is {data.stats.holdout_dispatches === 0 ? "intact" : "compromised"}.
              </p>
            </div>
          </section>
        </>
      )}
    </AppShell>
  );
}
