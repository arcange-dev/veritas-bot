import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PanelProps {
  label: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function Panel({ label, actions, children, className, bodyClassName }: PanelProps) {
  return (
    <section className={cn("flex min-h-0 min-w-0 flex-col bg-raised/60", className)}>
      <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b border-subtle px-3">
        <h2 className="panel-label truncate">{label}</h2>
        {actions ? <div className="flex items-center gap-1">{actions}</div> : null}
      </header>
      <div className={cn("min-h-0 flex-1 overflow-auto", bodyClassName)}>{children}</div>
    </section>
  );
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
      <p className="text-[13px] font-medium text-primary">{title}</p>
      <p className="max-w-[42ch] text-[12.5px] leading-relaxed text-muted">{body}</p>
      {action}
    </div>
  );
}

export function StatusChip({ tone, children }: { tone: "ok" | "warn" | "danger" | "muted" | "live"; children: ReactNode }) {
  const toneClass = {
    ok: "text-ok border-ok/30 bg-ok/10",
    warn: "text-warn border-warn/30 bg-warn/10",
    danger: "text-danger border-danger/30 bg-danger/10",
    muted: "text-muted border-subtle bg-overlay",
    live: "text-cyan border-cyan/30 bg-cyan/10",
  }[tone];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[11px] font-medium", toneClass)}>
      {children}
    </span>
  );
}
