// Mirrors ve_console/main.py's Jinja filters (format_money/format_percent/
// format_datetime) so migrated pages render numbers identically to the
// pages they replace.

export function formatMoney(value: number | null | undefined, currency = "USD"): string {
  const amount = value ?? 0;
  return `${currency} ${amount.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPercent(value: number | null | undefined): string {
  return `${(value ?? 0).toFixed(1)}%`;
}

export function formatNumber(value: number | null | undefined): string {
  return (value ?? 0).toLocaleString("en-US");
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const day = date.toLocaleString("en-US", { day: "2-digit", timeZone: "UTC" });
  const month = date.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const year = date.toLocaleString("en-US", { year: "numeric", timeZone: "UTC" });
  const time = date.toLocaleString("en-US", {
    hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
  });
  return `${day} ${month} ${year}, ${time}`;
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .split(" ")
    .map((word) => (word ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
}
