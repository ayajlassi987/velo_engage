import { Search, ListFilter } from "lucide-react";
import { apiGet } from "../api/client";
import type { OpportunitiesData } from "../api/types";
import type { ColumnDef } from "../api/listTypes";
import { useListData } from "../hooks/useListData";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { SummaryCards } from "../components/ui/SummaryCards";
import { DataTable } from "../components/ui/DataTable";
import { titleCase } from "../lib/format";

const COLUMNS: ColumnDef[] = [
  { key: "patient_id", label: "Patient", kind: "text" },
  { key: "family", label: "Family", kind: "family" },
  { key: "rule_name", label: "Reason", kind: "text" },
  { key: "priority_score", label: "Priority", kind: "score" },
  { key: "triggered_at", label: "Identified", kind: "datetime" },
  { key: "status", label: "Status", kind: "badge" },
  { key: "campaign_id", label: "Journey", kind: "campaign" },
];

const STATUSES = ["open", "created", "holdout", "sent", "delivered", "read", "replied", "booking_requested", "booked", "attended"];

export function OpportunitiesPage() {
  const { session } = useSession();
  const { data, status, searchParams, setSearchParams } = useListData<OpportunitiesData>(
    (params) => apiGet(`/api/v1/opportunities?${params.toString()}`),
  );

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSearchParams({
      q: String(form.get("q") || ""),
      family: String(form.get("family") || "all"),
      status: String(form.get("status") || "all"),
    });
  }

  return (
    <AppShell session={session} title="Opportunities" subtitle="Patients currently eligible for clinic engagement." liveStatus={status}>
      {data && (
        <>
          <SummaryCards summary={data.summary} />
          <section className="content-section">
            <div className="section-toolbar">
              <div><h2>All opportunities</h2><span>Showing up to 200 latest records</span></div>
              <form className="filters" onSubmit={onSubmit}>
                <label className="search-field">
                  <Search />
                  <input name="q" defaultValue={searchParams.get("q") || ""} placeholder="Search patient or ID" />
                </label>
                <select name="family" defaultValue={searchParams.get("family") || "all"} aria-label="Family">
                  <option value="all">All families</option>
                  {data.families.map((f) => <option value={f} key={f}>Family {f}</option>)}
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
