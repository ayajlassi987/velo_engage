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
  { key: "booking_id", label: "Booking", kind: "mono" },
  { key: "patient_id", label: "Patient", kind: "text" },
  { key: "appointment_date", label: "Appointment", kind: "datetime" },
  { key: "status", label: "Status", kind: "badge" },
  { key: "campaign_id", label: "Campaign", kind: "campaign" },
  { key: "revenue", label: "Paid revenue", kind: "money" },
];

export function BookingsPage() {
  const { session } = useSession();
  const { data, status, searchParams, setSearchParams } = useListData<ListPageData>(
    (params) => apiGet(`/api/v1/bookings?${params.toString()}`),
  );

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSearchParams({ q: String(form.get("q") || ""), status: String(form.get("status") || "all") });
  }

  return (
    <AppShell session={session} title="Bookings" subtitle="Appointments attributed to engagement campaigns." liveStatus={status}>
      {data && (
        <>
          <SummaryCards summary={data.summary} />
          <section className="content-section">
            <div className="section-toolbar">
              <div><h2>All bookings</h2><span>Showing up to 200 latest records</span></div>
              <form className="filters" onSubmit={onSubmit}>
                <label className="search-field">
                  <Search />
                  <input name="q" defaultValue={searchParams.get("q") || ""} placeholder="Search patient or ID" />
                </label>
                <select name="status" defaultValue={searchParams.get("status") || "all"} aria-label="Status">
                  <option value="all">All statuses</option>
                  <option value="booked">{titleCase("booked")}</option>
                  <option value="attended">{titleCase("attended")}</option>
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
