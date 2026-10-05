import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { NavLink, Outlet, useParams } from 'react-router-dom';
import { paths } from '@/app/router/paths';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import { useWorkspacesQuery } from '@/features/workspaces/hooks/useWorkspaces';
import { useBoardsQuery } from '@/features/boards/hooks/useBoards';
import { LoadingState } from '@/shared/ui/LoadingState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Button } from '@/shared/ui/Button';
import { Icon } from '@/shared/ui/Icon';
import { getBackendVersion } from '@/features/system/api/version';
import { webClientVersion } from '@/shared/version';
import { SourceUpdateSurface } from '@/features/system/components/SourceUpdateSurface';
import { apiRequest } from '@/shared/api/client';

const NAV_COLLAPSED_KEY = 'p2pkanban:navigation-collapsed';

function visibilityLabel(value: string) {
  return value === 'shared' ? 'общая' : 'личная';
}

export function MainLayout() {
  const { workspaceId, boardId } = useParams();
  const { user, signOutCurrent, signOutEverywhere } = useAuthSession();
  const workspacesQuery = useWorkspacesQuery();
  const boardsQuery = useBoardsQuery(workspaceId);
  const backendVersionQuery = useQuery({
    queryKey: ['backend-version'],
    queryFn: getBackendVersion,
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });
  const incomingQuery = useQuery({
    queryKey: ['device-link-lan-inbox'],
    queryFn: () => apiRequest<Array<{ id: string }>>('/auth/device-link/lan/inbox'),
    refetchInterval: 5000,
    retry: 0,
  });
  const [isNavigationCollapsed, setNavigationCollapsed] = useState(
    () => window.localStorage.getItem(NAV_COLLAPSED_KEY) === 'true',
  );

  function toggleNavigation() {
    setNavigationCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(NAV_COLLAPSED_KEY, String(next));
      return next;
    });
  }

  return (
    <>
      <SourceUpdateSurface />
      <div className={`app-shell ${isNavigationCollapsed ? 'app-shell--navigation-collapsed' : ''}`} data-testid="app-shell">
      <aside className="app-sidebar" data-testid="main-nav">
        <div className="app-sidebar__brand">
          <NavLink to={paths.home} className="brand-link">
            p2pKanban
          </NavLink>
          <p className="brand-copy">Локальный планировщик</p>
        </div>

        <details className="sidebar-group" open>
          <summary className="sidebar-group__summary">
            <span>Пространства</span>
            <span className="nav-list__meta">{workspacesQuery.data?.items.length ?? 0}</span>
          </summary>
          {workspacesQuery.isLoading ? (
            <LoadingState label="Загружаем пространства…" compact />
          ) : workspacesQuery.isError ? (
            <ErrorState title="Не удалось загрузить пространства" compact />
          ) : (
            <nav className="nav-list nav-list--scroll">
              <NavLink to={paths.home} className={({ isActive }) => `nav-list__item ${isActive ? 'is-active' : ''}`} end>
                Все пространства
              </NavLink>
              {workspacesQuery.data?.items.map((workspace) => (
                <NavLink
                  key={workspace.id}
                  to={paths.workspaceBoards(workspace.id)}
                  className={({ isActive }) => `nav-list__item ${isActive ? 'is-active' : ''}`}
                >
                  <span>{workspace.name}</span>
                  <span className="nav-list__meta">{visibilityLabel(workspace.visibility)}</span>
                </NavLink>
              ))}
            </nav>
          )}
        </details>

        {workspaceId ? (
          <details className="sidebar-group sidebar-group--boards" open>
            <summary className="sidebar-group__summary">
              <span>Доски</span>
              <span className="nav-list__meta">{boardsQuery.data?.items.length ?? 0}</span>
            </summary>
            {boardsQuery.isLoading ? (
              <LoadingState label="Загружаем доски…" compact />
            ) : boardsQuery.isError ? (
              <ErrorState title="Не удалось загрузить доски" compact />
            ) : boardsQuery.data?.items.length ? (
              <nav className="nav-list nav-list--scroll nav-list--boards">
                {boardsQuery.data.items.map((board) => (
                  <NavLink
                    key={board.id}
                    to={paths.board(workspaceId, board.id)}
                    className={({ isActive }) => `nav-list__item ${isActive ? 'is-active' : ''}`}
                  >
                    <span>{board.name}</span>
                  </NavLink>
                ))}
              </nav>
            ) : (
              <p className="sidebar-empty">В этом пространстве пока нет досок.</p>
            )}
          </details>
        ) : null}

        <details className="sidebar-group sidebar-group--settings">
          <summary className="sidebar-group__summary">
            <span>Настройки</span>
            <Icon name="settings" size={15} />
          </summary>
          <nav className="nav-list">
            <NavLink to={paths.network} className={({ isActive }) => `nav-list__item ${isActive ? 'is-active' : ''}`}>
              <span>Сеть и устройства {incomingQuery.data?.length ? `· запросов: ${incomingQuery.data.length}` : ''}</span>
            </NavLink>
            <NavLink to={paths.userAppearance} className={({ isActive }) => `nav-list__item ${isActive ? 'is-active' : ''}`}>
              <span>Вид приложения</span>
            </NavLink>
            {workspaceId && boardId ? (
              <NavLink to={paths.boardAppearance(workspaceId, boardId)} className={({ isActive }) => `nav-list__item ${isActive ? 'is-active' : ''}`}>
                <span>Вид текущей доски</span>
              </NavLink>
            ) : null}
          </nav>
        </details>
        <div className="app-sidebar__version" title="Версии клиента и подключённого backend-узла">
          <span>Web {webClientVersion}</span>
          <span>Backend {backendVersionQuery.data?.version || 'недоступен'}</span>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="topbar__context">
            <Button
              iconOnly
              variant="ghost"
              onClick={toggleNavigation}
              title={isNavigationCollapsed ? 'Показать навигацию' : 'Скрыть навигацию'}
              aria-label={isNavigationCollapsed ? 'Показать навигацию' : 'Скрыть навигацию'}
              aria-expanded={!isNavigationCollapsed}
            >
              <Icon name="menu" />
            </Button>
            <span className="topbar__product">p2pKanban</span>
          </div>

          <details className="account-menu">
            <summary className="account-menu__summary">
              <span className="account-menu__avatar">{(user?.displayName || user?.email || '?').slice(0, 1).toUpperCase()}</span>
              <span className="account-menu__name">{user?.displayName || 'Пользователь'}</span>
              <Icon name="chevron" size={15} />
            </summary>
            <div className="account-menu__popover">
              <div className="account-menu__identity">
                <strong>{user?.displayName || 'Пользователь'}</strong>
                <span>{user?.email}</span>
              </div>
              <Button variant="ghost" onClick={() => void signOutCurrent()}>
                Выйти на этом устройстве
              </Button>
              <Button variant="danger" onClick={() => void signOutEverywhere()}>
                Выйти везде
              </Button>
            </div>
          </details>
        </header>

        <main className="content-area" data-testid="route-outlet">
          {incomingQuery.data?.length ? <p role="status" className="panel">
            Поступил запрос на подключение устройства. <NavLink to={paths.network}>Открыть сетевые настройки</NavLink>
          </p> : null}
          <Outlet />
        </main>
      </div>
      </div>
    </>
  );
}
