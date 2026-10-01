import type { Evidence, PropertyDirection } from "./types";

export function colorFor(value: number, direction: PropertyDirection): string {
  if (value > 0.00001) {
    return direction === "higher" ? "var(--mmp-gain)" : "var(--mmp-loss)";
  }
  if (value < -0.00001) {
    return direction === "higher" ? "var(--mmp-loss)" : "var(--mmp-gain)";
  }
  return "var(--mmp-neutral)";
}

export function dashFor(evidence: Evidence): string {
  if (evidence === "Strong") return "";
  if (evidence === "Moderate") return "8 5";
  return "3 7";
}
