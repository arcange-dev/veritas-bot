/**
 * Display logic for runs, kept pure so it is testable without rendering.
 * Money is handled as integer micro-dollars: the API sends exact decimal
 * strings and floats would round them.
 */
import type { PlanTask, RunStatus } from "./schemas";
import { TERMINAL } from "./schemas";

export type Tone = "ok" | "warn" | "danger" | "muted" | "live";

const STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  paused: "Paused",
  waiting_approval: "Needs your approval",
  succeeded: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
  needs_review: "Needs review",
};

const STATUS_TONE: Record<RunStatus, Tone> = {
  queued: "muted",
  running: "live",
  paused: "warn",
  waiting_approval: "warn",
  succeeded: "ok",
  failed: "danger",
  cancelled: "muted",
  needs_review: "warn",
};

export const statusLabel = (s: RunStatus): string => STATUS_LABEL[s];
export const statusTone = (s: RunStatus): Tone => STATUS_TONE[s];

/** Which controls make sense in a state. The server still enforces transitions. */
export function availableControls(status: RunStatus): ("pause" | "resume" | "cancel")[] {
  if (TERMINAL.has(status)) return [];
  if (status === "paused") return ["resume", "cancel"];
  if (status === "queued") return ["cancel"];
  return ["pause", "cancel"];
}

/** Error codes from the backend, translated. Unknown codes never show raw. */
const ERROR_COPY: Record<string, string> = {
  no_usable_model: "No model is assigned to the agents. Choose one in Agent Studio.",
  spend_cap_exceeded: "This run reached its spending limit and was stopped before spending more.",
  invalid_plan: "The model did not return a usable plan. Try rephrasing the objective.",
  provider_error: "The AI provider returned an error. Check the connection in Providers.",
  internal_error: "Something went wrong on our side. The run was stopped safely.",
};

export function errorMessage(code: string): string | null {
  if (!code) return null;
  return ERROR_COPY[code] ?? "The run stopped unexpectedly.";
}

/** "0.004000" -> 4000 micro-dollars, with no floating point involved. */
export function toMicros(amount: string): number {
  const [whole = "0", frac = ""] = amount.replace("-", "").split(".");
  const micros = Number(whole) * 1_000_000 + Number(frac.padEnd(6, "0").slice(0, 6));
  return amount.startsWith("-") ? -micros : micros;
}

export function formatUsd(amount: string): string {
  const micros = toMicros(amount);
  // Sub-cent spend must stay visible: rounding $0.004 to "$0.00" would hide real cost.
  const digits = Math.abs(micros) < 10_000 && micros !== 0 ? 4 : 2;
  return `$${(micros / 1_000_000).toFixed(digits)}`;
}

/** 0..100, clamped. A zero cap reads as full rather than dividing by zero. */
export function spendPercent(cost: string, cap: string): number {
  const capMicros = toMicros(cap);
  if (capMicros <= 0) return 100;
  return Math.min(100, Math.max(0, Math.round((toMicros(cost) / capMicros) * 100)));
}

export interface PlanProgress {
  done: number;
  total: number;
  failed: number;
  running: number;
}

export function planProgress(plan: PlanTask[]): PlanProgress {
  return {
    total: plan.length,
    done: plan.filter((t) => t.state === "done").length,
    failed: plan.filter((t) => t.state === "failed").length,
    running: plan.filter((t) => t.state === "running").length,
  };
}

/** Tasks that wait on something unfinished, for the "blocked by" hint. */
export function blockedBy(task: PlanTask, plan: PlanTask[]): string[] {
  const byId = new Map(plan.map((t) => [t.id, t]));
  return task.depends_on.filter((id) => byId.get(id)?.state !== "done");
}

/** Human-readable time left on an approval; null once expired. */
export function expiresIn(expiresAt: string, now: Date = new Date()): string | null {
  const ms = new Date(expiresAt).getTime() - now.getTime();
  if (Number.isNaN(ms) || ms <= 0) return null;
  const minutes = Math.ceil(ms / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}
