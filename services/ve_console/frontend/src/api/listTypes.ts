// Generic row shape for list.html-equivalent pages — columns are declared
// per-page (see ColumnDef) and each cell's "kind" decides how DataTable
// renders it, mirroring macros.html's data_table macro exactly.
export type Row = Record<string, unknown>;

export type ColumnKind =
  | "text" | "badge" | "family" | "datetime" | "campaign" | "score"
  | "boolean" | "paid" | "money" | "money_with_currency" | "mono" | "list" | "flags";

export interface ColumnDef {
  key: string;
  label: string;
  kind: ColumnKind;
}

export interface Summary {
  [key: string]: number;
}
