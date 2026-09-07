import { Search } from "lucide-react";
import { apiGet } from "../api/client";
import type { ListPageData } from "../api/types";
import type { ColumnDef } from "../api/listTypes";
import { useListData } from "../hooks/useListData";
import { useSession } from "../hooks/useSession";
import { AppShell } from "../components/layout/AppShell";
import { SummaryCards } from "../components/ui/SummaryCards";
import { DataTable } from "../components/ui/DataTable";

const COLUMNS: ColumnDef[] = [
  { key: "patient_id", label: "Patient", kind: "text" },
  { key: "diagnoses", label: "Diagnoses", kind: "list" },
  { key: "medications", label: "Medications", kind: "list" },
  { key: "procedures", label: "Procedures", kind: "list" },
  { key: "follow_up_recommendations", label: "Follow-up", kind: "list" },
  { key: "clinical_risks", label: "Risks", kind: "list" },
  { key: "validation_flags", label: "Quality", kind: "flags" },
  { key: "extracted_at", label: "Extracted", kind: "datetime" },
];

export function ClinicalSummariesPage() {
  const { session } = useSession();
  const { data, status, searchParams, setSearchParams } = useListData<ListPageData>(
    (params) => apiGet(`/api/v1/clinical-summaries?${params.toString()}`),
  );

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSearchParams({ q: String(form.get("q") || "") });
  }

  return (
    <AppShell
      session={session} title="Clinical summaries" liveStatus={status}
      subtitle="Structured extractions from clinical notes (MedGemma + NemoGuard) — no raw note text is ever stored."
    >
      {data && (
        <>
          <SummaryCards summary={data.summary} />
          <section className="content-section">
            <div className="section-toolbar">
              <div><h2>All clinical summaries</h2><span>Showing up to 200 latest records</span></div>
              <form className="filters" onSubmit={onSubmit}>
                <label className="search-field">
                  <Search />
                  <input name="q" defaultValue={searchParams.get("q") || ""} placeholder="Search patient or ID" />
                </label>
                <button className="button secondary" type="submit">Search</button>
              </form>
            </div>
            <DataTable rows={data.rows} columns={COLUMNS} />
          </section>
        </>
      )}
    </AppShell>
  );
}
