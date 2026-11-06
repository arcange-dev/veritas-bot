/** Display logic for the dashboard. Pure, so it is tested without rendering. */
import { formatUsd, toMicros } from "@/features/runs/present";

/** "5 min ago" style, from an ISO time. Falls back to a date for old items. */
export function timeAgo(iso: string, now: Date = new Date()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((now.getTime() - then) / 1000);
  if (seconds < 45) return "just now";            // also covers a slightly-future server clock
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** Share of the monthly cap used, 0..100. A missing or zero cap means "unknown", not 100%. */
export function capUsedPercent(spend: string, cap: string | null | undefined): number | null {
  if (!cap) return null;
  const capMicros = toMicros(cap);
  if (capMicros <= 0) return null;
  return Math.min(100, Math.max(0, Math.round((toMicros(spend) / capMicros) * 100)));
}

export const spendLabel = (spend: string): string => formatUsd(spend);

/** Active-run statuses shown as a count of things "in flight". */
export function statusCount(byStatus: Record<string, number>, ...statuses: string[]): number {
  return statuses.reduce((sum, s) => sum + (byStatus[s] ?? 0), 0);
}

/** Greeting that never invents a name: falls back to the email's local part, then nothing. */
export function greetingName(displayName: string, email: string): string {
  const name = displayName.trim();
  if (name) return name.split(/\s+/)[0] ?? "";
  const local = email.split("@")[0] ?? "";
  return local;
}
