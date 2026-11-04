import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/cn";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { ProvidersPage } from "@/features/providers/ProvidersPage";
import { StudioPage } from "@/features/studio/StudioPage";

const navItem =
  "rounded-sm px-2.5 py-1.5 text-[12.5px] text-secondary transition-colors duration-[var(--dur-fast)] hover:text-primary";

export default function App() {
  return (
    <div className="flex h-full flex-col">
      <header className="flex h-11 shrink-0 items-center gap-4 border-b border-subtle bg-raised px-4">
        <Logo />
        <nav className="flex items-center gap-1" aria-label="Primary">
          <NavLink to="/dashboard" className={({ isActive }) => cn(navItem, isActive && "bg-overlay text-primary")}>
            Dashboard
          </NavLink>
          <NavLink to="/studio" className={({ isActive }) => cn(navItem, isActive && "bg-overlay text-primary")}>
            Studio
          </NavLink>
          <NavLink to="/providers" className={({ isActive }) => cn(navItem, isActive && "bg-overlay text-primary")}>
            Providers
          </NavLink>
        </nav>
        <div className="ml-auto text-[11px] text-muted">local</div>
      </header>

      <main className="min-h-0 flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/studio" element={<StudioPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}
