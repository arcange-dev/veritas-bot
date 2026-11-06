import { Navigate, Route, Routes } from "react-router-dom";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { ProvidersPage } from "@/features/providers/ProvidersPage";
import { StudioPage } from "@/features/studio/StudioPage";
import { ProjectsPage } from "@/features/projects/ProjectsPage";
import { NewProjectPage } from "@/features/projects/NewProjectPage";
import { ProjectPage } from "@/features/projects/ProjectPage";
import { AppHeader } from "@/features/session/AppHeader";
import { SessionGate } from "@/features/session/SessionGate";

export default function App() {
  return (
    <div className="flex h-full flex-col">
      <SessionGate>
        <AppHeader />
        <main className="min-h-0 flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/new" element={<NewProjectPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/studio" element={<StudioPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
        </main>
      </SessionGate>
    </div>
  );
}
