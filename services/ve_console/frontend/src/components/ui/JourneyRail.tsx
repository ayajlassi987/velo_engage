import { Check, Circle } from "lucide-react";

export function JourneyRail({ steps }: { steps: [string, boolean | null | undefined][] }) {
  return (
    <section className="journey-rail" aria-label="Journey">
      {steps.map(([label, done]) => (
        <div className={`journey-step ${done ? "done" : ""}`} key={label}>
          <span>{done ? <Check /> : <Circle />}</span>
          <strong>{label}</strong>
        </div>
      ))}
    </section>
  );
}
