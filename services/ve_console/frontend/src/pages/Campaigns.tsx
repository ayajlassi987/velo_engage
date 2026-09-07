import { Search, ListFilter } from "lucide-react";
import { apiGet } from "../api/client";
import type { ListPageData } from "../api/types";
import type { ColumnDef } from "../api/listTypes";
import { useListData } from "../hooks/useListData";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { SummaryCards } from "../components/ui/SummaryCards";
import { DataTable } from "../components/ui/DataTable";
import { titleCase } from "../lib/format";

const COLUMNS: ColumnDef[] = [
  { key: "campaign_id", label: "Campaign", kind: "campaign" },
  { key: "patient_id", label: "Patient", kind: "text" },
  { key: "family", label: "Family", kind: "family" },
  { key: "treatment_arm", label: "Arm", kind: "badge" },
  { key: "created_at", label: "Created", kind: "datetime" },
  { key: "status", label: "Status", kind: "badge" },
  { key: "dispatched_at", label: "Sent", kind: "datetime" },
  { key: "revenue", label: "Revenue", kind: "money" },
];

const STATUSES = ["open", "holdout", "sent", "delivered", "read", "replied", "booking_requested", "booked", "attended"];

export function CampaignsPage() {
  const { session } = useSession();
  const { data, status, searchParams, setSearchParams } = useListData<ListPageData>(
    (params) => apiGet(`/api/v1/campaigns?${params.toString()}`),
  );

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSearchParams({
      q: String(form.get("q") || ""),
      arm: String(form.get("arm") || "all"),
      status: String(form.get("status") || "all"),
    });
  }

  return (
    <AppShell session={session} title="Campaigns" subtitle="Treatment allocation and campaign execution status." liveStatus={status}>
      {data && (
        <>
          <SummaryCards summary={data.summary} />
          <section className="content-section">
            <div className="section-toolbar">
              <div><h2>All campaigns</h2><span>Showing up to 200 latest records</span></div>
              <form className="filters" onSubmit={onSubmit}>
                <label className="search-field">
                  <Search />
                  <input name="q" defaultValue={searchParams.get("q") || ""} placeholder="Search patient or ID" />
                </label>
                <select name="arm" defaultValue={searchParams.get("arm") || "all"} aria-label="Treatment arm">
                  <option value="all">All arms</option>
                  <option value="treated">Treated</option>
                  <option value="holdout">Holdout</option>
                </select>
                <select name="status" defaultValue={searchParams.get("status") || "all"} aria-label="Status">
                  <option value="all">All statuses</option>
                  {STATUSES.map((s) => <option value={s} key={s}>{titleCase(s)}</option>)}
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
