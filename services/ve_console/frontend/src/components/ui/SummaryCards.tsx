import { titleCase, formatMoney, formatPercent, formatNumber } from "../../lib/format";
import type { Summary } from "../../api/listTypes";

const MONEY_KEYS = new Set(["revenue", "recovered", "outstanding", "spend"]);
const PERCENT_KEYS = new Set(["roi", "booking_rate", "treated_rate", "holdout_rate", "relative_lift"]);

// Mirrors macros.html's summary_cards() macro exactly — same key-based
// formatting rules, same markup/classes as theme.css's .metric-grid.
export function SummaryCards({ summary }: { summary: Summary }) {
  return (
    <section className="metric-grid">
      {Object.entries(summary).map(([key, value]) => (
        <article className="metric-card" key={key}>
          <span className="metric-label">{titleCase(key)}</span>
          <strong>
            {MONEY_KEYS.has(key) ? formatMoney(value) : PERCENT_KEYS.has(key) ? formatPercent(value) : formatNumber(Math.trunc(value))}
          </strong>
          <span className="metric-rule" />
        </article>
      ))}
    </section>
  );
}
