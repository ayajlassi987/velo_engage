import { ArrowUpRight, Check } from "lucide-react";
import { Badge } from "./Badge";
import { EmptyState } from "./EmptyState";
import { formatDateTime, formatMoney } from "../../lib/format";
import type { ColumnDef, Row } from "../../api/listTypes";

function Cell({ column, row }: { column: ColumnDef; row: Row }) {
  const value = row[column.key];
  switch (column.kind) {
    case "badge":
      return <Badge value={value as string} />;
    case "family":
      return <span className={`family family-${String(value).toLowerCase()}`}>{String(value)}</span>;
    case "datetime":
      return <span className="date-cell">{formatDateTime(value as string)}</span>;
    case "campaign":
      return value ? (
        <a className="record-link" href={`/campaigns/${value}`}>
          {String(value).slice(0, 10)}<ArrowUpRight />
        </a>
      ) : (
        <span className="muted">Not created</span>
      );
    case "score": {
      const num = Number(value ?? 0);
      return (
        <>
          <span className="score"><span style={{ width: `${Math.round(num * 100)}%` }} /></span>
          <b>{num.toFixed(2)}</b>
        </>
      );
    }
    case "boolean":
      return value ? (
        <span className="boolean yes"><Check />Yes</span>
      ) : (
        <span className="boolean no">No</span>
      );
    case "paid":
      return <Badge value={value ? "paid" : "unpaid"} />;
    case "money":
      return <>{formatMoney(value as number)}</>;
    case "money_with_currency":
      return <>{formatMoney(value as number, (row["currency"] as string) || "USD")}</>;
    case "mono":
      return <span className="mono">{(value as string) || "-"}</span>;
    case "list":
      return <>{Array.isArray(value) && value.length ? value.join(", ") : "-"}</>;
    case "flags": {
      const flags = Array.isArray(value) ? (value as string[]) : [];
      return flags.length ? (
        <span className="badge badge-warning" title={flags.join("; ")}>
          {flags.length} flag{flags.length !== 1 ? "s" : ""}
        </span>
      ) : (
        <span className="badge badge-stable">Clean</span>
      );
    }
    default:
      return <>{value === null || value === undefined || value === "" ? "-" : String(value)}</>;
  }
}

// Mirrors macros.html's data_table() macro exactly — same column "kind"
// system, same cell-{kind} class per <td>, same empty state.
export function DataTable({ rows, columns }: { rows: Row[]; columns: ColumnDef[] }) {
  if (!rows.length) return <EmptyState />;
  return (
    <div className="table-frame">
      <table>
        <thead>
          <tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={(row["campaign_id"] as string) || (row["opportunity_id"] as string) || (row["booking_id"] as string) || (row["invoice_id"] as string) || (row["extraction_id"] as string) || i}>
              {columns.map((column) => (
                <td className={`cell-${column.kind}`} key={column.key}>
                  <Cell column={column} row={row} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
