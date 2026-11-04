import { Play, Hammer, FlaskConical, MonitorPlay, GitBranch, Cpu } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Project } from "@/lib/api";

interface StudioToolbarProps {
  project: Project | null;
  target: "local" | "cloud";
  model: string;
}

/**
 * Build, Run, Test and Preview need a command-execution endpoint that does not
 * exist yet: the API can run agent runs, but does not expose "run this project's
 * test command" to the browser. They are shown disabled with the reason, rather
 * than wired to something that merely looks similar (an LLM run is slow and
 * costs money; a Test button must not start one).
 */
const NOT_AVAILABLE = "Needs the execution endpoint, which is not built yet";

const actionClass =
  "inline-flex h-7 items-center gap-1.5 rounded-sm border border-subtle bg-overlay px-2 text-[12px] text-secondary transition-colors duration-[var(--dur-fast)] hover:border-strong hover:text-primary disabled:opacity-40";

export function StudioToolbar({ project, target, model }: StudioToolbarProps) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-3 border-b border-subtle bg-raised px-3">
      <div className="min-w-0">
        <p className="truncate text-[13px] font-medium text-primary">
          {project?.name ?? "No project selected"}
        </p>
        <p className="truncate text-[11px] text-muted">
          {project ? `${project.slug} · ${project.default_branch}` : "Create a project to begin"}
        </p>
      </div>

      <span className="h-6 w-px bg-subtle" aria-hidden />

      <span className={cn("inline-flex items-center gap-1 text-[11.5px]", "text-secondary")}>
        <Cpu className="size-3.5" aria-hidden />
        {target === "local" ? "Local runner" : "Cloud sandbox"}
      </span>
      <span className="font-mono text-[11.5px] text-muted">{model}</span>

      <div className="ml-auto flex items-center gap-1.5">
        <button type="button" className={actionClass} disabled aria-disabled="true" title={NOT_AVAILABLE}>
          <Hammer className="size-3.5" aria-hidden /> Build
        </button>
        <button type="button" className={actionClass} disabled aria-disabled="true" title={NOT_AVAILABLE}>
          <Play className="size-3.5" aria-hidden /> Run
        </button>
        <button type="button" className={actionClass} disabled aria-disabled="true" title={NOT_AVAILABLE}>
          <FlaskConical className="size-3.5" aria-hidden /> Test
        </button>
        <button type="button" className={actionClass} disabled aria-disabled="true" title={NOT_AVAILABLE}>
          <MonitorPlay className="size-3.5" aria-hidden /> Preview
        </button>
        <span className={actionClass} title="Git status is not connected yet">
          <GitBranch className="size-3.5" aria-hidden /> {project?.default_branch ?? "no branch"}
        </span>
      </div>
    </div>
  );
}
