/**
 * Top bar. Signed out, it shows only the brand. Signed in, it shows navigation, the active
 * workspace (switchable when the user has several) and an account menu with sign out.
 */
import { useContext, useState } from "react";
import { NavLink } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/cn";
import { signOut } from "@/lib/auth";
import { SessionContext } from "./context";

const navItem =
  "shrink-0 rounded-sm px-2.5 py-1.5 text-[12.5px] text-secondary transition-colors duration-[var(--dur-fast)] hover:text-primary";
const LINKS = [
  ["/dashboard", "Dashboard"], ["/projects", "Projects"], ["/studio", "Studio"], ["/providers", "Providers"],
] as const;

export function AppHeader() {
  const session = useContext(SessionContext);
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-subtle bg-raised px-3 sm:gap-4 sm:px-4">
      <Logo />
      {session && (
        <>
          {/* Scrolls inside itself on narrow screens instead of widening the whole page. */}
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label="Primary">
            {LINKS.map(([to, label]) => (
              <NavLink key={to} to={to} className={({ isActive }) => cn(navItem, isActive && "bg-overlay text-primary")}>
                {label}
              </NavLink>
            ))}
          </nav>

          {session.me.organizations.length > 1 ? (
            <label className="flex shrink-0 items-center gap-2 text-[11.5px] text-muted">
              <span className="sr-only">Workspace</span>
              <select value={session.org.id} onChange={(e) => { session.setOrg(e.target.value); qc.clear(); }}
                      className="h-7 max-w-[10rem] rounded-sm border border-subtle bg-base px-2 text-[12px] text-primary">
                {session.me.organizations.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            </label>
          ) : (
            <span className="hidden max-w-[10rem] shrink-0 truncate text-[12px] text-secondary sm:inline">{session.org.name}</span>
          )}

          <div className="relative shrink-0">
            <button type="button" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}
                    className="btn-glass flex h-7 items-center gap-2 px-2 text-[12px]">
              <span aria-hidden className="grid h-4 w-4 place-items-center rounded-full bg-overlay text-[9px] uppercase text-primary">
                {(session.me.profile.display_name || session.me.profile.email).slice(0, 1)}
              </span>
              <span className="sr-only">Account menu</span>
            </button>
            {open && (
              <div role="menu" className="glass glass-strong absolute right-0 top-9 z-20 w-56 rounded-md p-1">
                <p className="truncate px-2.5 py-1.5 text-[11.5px] text-muted">{session.me.profile.email}</p>
                <p className="px-2.5 pb-1.5 text-[11px] uppercase tracking-wide text-muted">{session.role} in {session.org.name}</p>
                <button role="menuitem" type="button" onClick={() => void signOut()}
                        className="w-full rounded-sm px-2.5 py-1.5 text-left text-[12.5px] text-secondary hover:bg-overlay hover:text-primary">
                  Sign out
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </header>
  );
}
