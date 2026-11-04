/** The Veritas Bot assembly mark, drawn from the exact vector in the Figma file. */
import { cn } from "@/lib/cn";

const MARK_PATH =
  "M0 0H22.5L30 7.5V30H7.5L0 22.5V0ZM6.5625 6.5625V19.6875L10.3125 23.4375H23.4375V10.3125L19.6875 6.5625H6.5625ZM11.25 11.25H18.75V18.75H11.25V11.25Z";

export function LogoMark({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" fill="none" aria-hidden="true"
         className={cn("shrink-0 text-primary", className)}>
      <path d={MARK_PATH} fill="currentColor" fillRule="evenodd" clipRule="evenodd" />
    </svg>
  );
}

export function Logo({ size = 20, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark size={size} />
      <span className="text-[13px] font-semibold uppercase tracking-[0.12em] text-primary">Veritas Bot</span>
    </span>
  );
}
