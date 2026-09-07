import { Search, ListFilter } from "lucide-react";
import { apiGet } from "../api/client";
import type { ListPageData } from "../api/types";
import type { ColumnDef } from "../api/listTypes";
import { useListData } from "../hooks/useListData";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { SummaryCards } from "../components/ui/SummaryCards";
import { DataTable } from "../components/ui/DataTable";

const COLUMNS: ColumnDef[] = [
  { key: "invoice_id", label: "Invoice", kind: "mono" },
  { key: "patient_id", label: "Patient", kind: "text" },
  { key: "amount", label: "Amount", kind: "money_with_currency" },
  { key: "paid", label: "Payment", kind: "paid" },
  { key: "booking_id", label: "Booking", kind: "mono" },
  { key: "campaign_id", label: "Campaign", kind: "campaign" },
  { key: "occurred_at", label: "Occurred", kind: "datetime" },
];

export function RevenuePage() {
  const { session } = useSession();
  const { data, status, searchParams, setSearchParams } = useListData<ListPageData>(
    (params) => apiGet(`/api/v1/revenue?${params.toString()}`),
  );

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSearchParams({ q: String(form.get("q") || ""), state: String(form.get("state") || "all") });
  }

  return (
    <AppShell session={session} title="Recovered revenue" subtitle="Paid billing linked back to campaign-attributed bookings." liveStatus={status}>
      {data && (
        <>
          <SummaryCards summary={data.summary} />
          <section className="content-section">
            <div className="section-toolbar">
              <div><h2>All revenue</h2><span>Showing up to 200 latest records</span></div>
              <form className="filters" onSubmit={onSubmit}>
                <label className="search-field">
                  <Search />
                  <input name="q" defaultValue={searchParams.get("q") || ""} placeholder="Search patient or ID" />
                </label>
                <select name="state" defaultValue={searchParams.get("state") || "all"} aria-label="Payment state">
                  <option value="all">All payments</option>
                  <option value="paid">Paid</option>
                  <option value="unpaid">Unpaid</option>
                </select>
                <button className="button secondary" type="submit"><ListFilter />Apply</button>
              </form>
            </div>
            <DataTable rows={data.rows} columns={COLUMNS} />
          </section>
        </>
      )}
    </AppShell>
  );
}
