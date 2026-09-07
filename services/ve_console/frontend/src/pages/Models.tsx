import { Box, ArrowUpRight } from "lucide-react";
import { apiGet } from "../api/client";
import type { ModelCard, ModelsData } from "../api/types";
import { useLiveRefresh } from "../hooks/useLiveRefresh";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { Badge } from "../components/ui/Badge";
import { EmptyState } from "../components/ui/EmptyState";
import { formatDateTime } from "../lib/format";

function fetchModels() {
  return apiGet<ModelsData>("/api/v1/models");
}

function ModelHero({ model, mlflowUrl }: { model: ModelCard; mlflowUrl: string }) {
  const metricEntries = Object.entries(model.metrics);
  return (
    <div className="model-hero">
      <div>
        <span className="eyebrow">{model.model_name}</span>
        <h2>{model.label}</h2>
        {model.headline_version ? (
          <p>
            <Badge value={model.headline_version.current_stage || "unstaged"} /> · v{model.headline_version.version} ·{" "}
            {formatDateTime(model.headline_version.creation_timestamp)}
          </p>
        ) : <p>No registered versions yet.</p>}
        <div className="model-actions">
          <a className="button secondary" href={`${mlflowUrl}/#/models/${model.model_name}`} target="_blank" rel="noreferrer">
            <Box />Model registry
          </a>
        </div>
      </div>
      <div className="model-score">
        {metricEntries.length ? (
          <>
            <span>{metricEntries[0][0]}</span>
            <strong>{metricEntries[0][1].toFixed(3)}</strong>
            <small>{metricEntries.slice(1).map(([k, v]) => `${k} ${v.toFixed(3)}`).join(", ")}</small>
          </>
        ) : (
          <>
            <span>metrics</span>
            <strong>–</strong>
            <small>No run metrics logged yet</small>
          </>
        )}
      </div>
    </div>
  );
}

function QualityBlock({ label, hint, quality }: { label: string; hint: string; quality: ModelCard["quality_synthetic"] }) {
  return (
    <div>
      <strong>{label}</strong> <small>({hint})</small><br />
      {quality && quality.status === "ok" ? (
        <>
          n={quality.n} · P {quality.precision?.toFixed(3)} · R {quality.recall?.toFixed(3)} · F1 {quality.f1?.toFixed(3)}
          {quality.auc ? ` · AUC ${quality.auc.toFixed(3)}` : ""}
        </>
      ) : <EmptyState title="Insufficient data" text="Not enough outcomes yet to compute quality metrics." />}
    </div>
  );
}

export function ModelsPage() {
  const { session } = useSession();
  const { data, status } = useLiveRefresh(fetchModels);

  return (
    <AppShell session={session} title="ML models" subtitle="Training runs, registered versions, and drift across every model." liveStatus={status}>
      {data && (
        <>
          {data.alerts.length > 0 && (
            <section className="content-section">
              <div className="section-heading"><div><h2>Alerts</h2><span>{data.alerts.length} signal{data.alerts.length !== 1 ? "s" : ""} needing attention</span></div></div>
              <div style={{ padding: "0 18px 18px", display: "flex", flexDirection: "column", gap: 8 }}>
                {data.alerts.map((alert, i) => (
                  <div key={i}><Badge value="critical" /> <strong>{alert.label}</strong> — {alert.detail}</div>
                ))}
              </div>
            </section>
          )}

          {data.model_cards.map((model) => (
            <div key={model.model_name}>
              <ModelHero model={model} mlflowUrl={data.mlflow_url} />

              <section className="content-section">
                <div className="section-heading">
                  <div>
                    <h2>Prediction drift</h2>
                    {model.score_column ? (
                      <span>{model.score_column} distribution, last {model.drift?.window_days ?? "-"}d vs. baseline (PSI)</span>
                    ) : <span>Not applicable — see note below</span>}
                  </div>
                </div>
                {!model.score_column ? (
                  <EmptyState
                    title="No continuous score persisted"
                    text={`${model.label} predicts a label (see inbound_messages.detected_intent), not a continuous score — this PSI implementation needs a score distribution, so drift here would need a different, category-proportion-based metric, not built yet.`}
                  />
                ) : model.drift && model.drift.psi != null ? (
                  <div className="model-score" style={{ margin: "0 18px 18px" }}>
                    <span>PSI</span>
                    <strong>{model.drift.psi.toFixed(3)}</strong>
                    <small><Badge value={model.drift.status} /> · baseline n={model.drift.baseline_n} · current n={model.drift.current_n}</small>
                  </div>
                ) : model.drift ? (
                  <EmptyState title="Not enough data yet" text="Need a larger scored population on each side of the window to compute PSI." />
                ) : (
                  <EmptyState title="No scored campaigns yet" text={`PSI drift appears once campaigns carry a ${model.score_column}.`} />
                )}
              </section>

              {(model.quality_synthetic !== null || model.quality_real !== null) && (
                <section className="content-section">
                  <div className="section-heading"><div><h2>Prediction quality</h2><span>Precision / recall / F1 / AUC against real logged outcomes</span></div></div>
                  <div style={{ padding: "0 18px 18px", display: "flex", gap: 24, flexWrap: "wrap" }}>
                    <QualityBlock label="Synthetic cohort" hint="historical backtest, not live performance" quality={model.quality_synthetic} />
                    <QualityBlock label="Real cohort" hint="live Epic patients" quality={model.quality_real} />
                  </div>
                </section>
              )}
            </div>
          ))}

          <section className="content-section">
            <div className="section-heading">
              <div><h2>Feature drift</h2><span>Population-level input drift (age, days_since_last_visit, visit_cadence_baseline), independent of any single model's score</span></div>
            </div>
            <div style={{ padding: "0 18px 18px", display: "flex", gap: 24, flexWrap: "wrap" }}>
              {Object.entries(data.feature_drift).map(([column, drift]) => (
                <div key={column}>
                  <strong>{column}</strong><br />
                  {drift && drift.psi != null ? (
                    <>PSI {drift.psi.toFixed(3)} <Badge value={drift.status} /> <small>n={drift.baseline_n}/{drift.current_n}</small></>
                  ) : <small>Insufficient data</small>}
                </div>
              ))}
            </div>
          </section>

          <section className="content-section">
            <div className="section-heading"><div><h2>Registered versions</h2><span>Immutable model artifacts tracked in MLflow, across every model</span></div></div>
            {data.versions.length ? (
              <div className="table-frame">
                <table>
                  <thead><tr><th>Model</th><th>Version</th><th>Stage</th><th>Registry</th><th>Run</th><th>Created</th><th></th></tr></thead>
                  <tbody>
                    {data.versions.map((row) => (
                      <tr key={`${row.name}-${row.version}`}>
                        <td><strong>{row.name}</strong></td>
                        <td><span className="version-tag">v{row.version}</span></td>
                        <td><Badge value={row.current_stage || "unstaged"} /></td>
                        <td><Badge value={row.status.toLowerCase()} /></td>
                        <td><Badge value={(row.run_status || "").toLowerCase()} /></td>
                        <td>{formatDateTime(row.creation_timestamp)}</td>
                        <td>
                          <a className="icon-button small" href={`${data.mlflow_url}/#/models/${row.name}/versions/${row.version}`} target="_blank" rel="noreferrer" title="Open in MLflow">
                            <ArrowUpRight />
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <EmptyState title="No registered models" text="Run a training pipeline to create version 1." />}
          </section>
        </>
      )}
    </AppShell>
  );
}
