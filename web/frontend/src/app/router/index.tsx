import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { MainLayout } from '@/app/layouts/MainLayout';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import { WorkspacesPage } from '@/features/workspaces/pages/WorkspacesPage';
import { WorkspaceBoardsPage } from '@/features/boards/pages/WorkspaceBoardsPage';
import { BoardPage } from '@/features/boards/pages/BoardPage';
import { UserAppearancePage } from '@/features/appearance/pages/UserAppearancePage';
import { BoardAppearancePage } from '@/features/appearance/pages/BoardAppearancePage';
import { AuthPage } from '@/features/auth/pages/AuthPage';
import { NetworkPage } from '@/features/deviceLink/NetworkPage';
import { LoadingState } from '@/shared/ui/LoadingState';
import { WorkspaceAccessPage } from '@/features/workspaces/pages/WorkspaceAccessPage';
import { InvitationAcceptPage } from '@/features/workspaces/pages/InvitationAcceptPage';

function RequireAuth() {
  const { status } = useAuthSession();
  const location = useLocation();

  if (status === 'loading') {
    return <LoadingState label="Восстанавливаем сессию…" />;
  }

  if (status !== 'authenticated') {
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/auth?next=${encodeURIComponent(next)}`} replace />;
  }

  return <Outlet />;
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<MainLayout />}>
            <Route path="/" element={<WorkspacesPage />} />
            <Route path="/settings/appearance" element={<UserAppearancePage />} />
            <Route path="/settings/network" element={<NetworkPage />} />
            <Route path="/workspaces/:workspaceId/boards" element={<WorkspaceBoardsPage />} />
            <Route path="/workspaces/:workspaceId/access" element={<WorkspaceAccessPage />} />
            <Route path="/workspaces/:workspaceId/boards/:boardId" element={<BoardPage />} />
            <Route path="/workspaces/:workspaceId/boards/:boardId/customize" element={<BoardAppearancePage />} />
          </Route>
          <Route path="/invite/:token" element={<InvitationAcceptPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
