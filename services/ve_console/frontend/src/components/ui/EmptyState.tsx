import { Inbox } from "lucide-react";

export function EmptyState({
  title = "No records found",
  text = "Try changing the current filters.",
}: {
  title?: string;
  text?: string;
}) {
  return (
    <div className="empty-state">
      <Inbox />
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}
