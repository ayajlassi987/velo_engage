import { titleCase } from "../../lib/format";

// Mirrors macros.html's badge() macro exactly: same class-name derivation
// (lowercase, underscores to hyphens) so theme.css's existing
// .badge-treated/.badge-booked/etc. rules apply unchanged.
export function Badge({ value }: { value: string | null | undefined }) {
  const text = String(value ?? "");
  const className = `badge badge-${text.toLowerCase().replace(/_/g, "-")}`;
  return <span className={className}>{titleCase(text)}</span>;
}
