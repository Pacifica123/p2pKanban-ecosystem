import { FormEvent, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { paths } from '@/app/router/paths';
import { useWorkspacesQuery } from '@/features/workspaces/hooks/useWorkspaces';
import { useArchiveBoardMutation, useBoardsQuery, useCreateBoardMutation, useUpdateBoardMutation } from '@/features/boards/hooks/useBoards';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { TextAreaField, TextField } from '@/shared/ui/Field';
import { LoadingState } from '@/shared/ui/LoadingState';
import { Badge } from '@/shared/ui/Badge';
import { formatDateTime } from '@/shared/lib/date';
import { BoardImportPanel } from '@/features/integrations/components/BoardImportPanel';
import { Icon } from '@/shared/ui/Icon';

export function WorkspaceBoardsPage() {
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const workspacesQuery = useWorkspacesQuery();
  const boardsQuery = useBoardsQuery(workspaceId);
  const createBoardMutation = useCreateBoardMutation(workspaceId);
  const updateBoardMutation = useUpdateBoardMutation(workspaceId);
  const archiveBoardMutation = useArchiveBoardMutation(workspaceId);

  const workspace = useMemo(
    () => workspacesQuery.data?.items.find((item) => item.id === workspaceId),
    [workspaceId, workspacesQuery.data?.items],
  );
  const canEdit = workspace?.currentUserRole === 'owner' || workspace?.currentUserRole === 'member';

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspaceId || !name.trim()) return;
    createBoardMutation.mutate(
      { name: name.trim(), description: description.trim() || undefined },
      {
        onSuccess: (board) => {
          setName('');
          setDescription('');
          navigate(paths.board(workspaceId, board.id));
        },
      },
    );
  }

  async function handleRename(boardId: string, currentName: string) {
    const next = window.prompt('Новое название доски', currentName)?.trim();
    if (!next || next === currentName) return;
    await updateBoardMutation.mutateAsync({ boardId, input: { name: next } });
  }

  async function handleArchive(boardId: string, boardName: string) {
    if (!window.confirm(`Архивировать доску «${boardName}»?`)) return;
    await archiveBoardMutation.mutateAsync(boardId);
  }

  if (!workspaceId) {
    return <ErrorState title="Пространство не выбрано" description="Выберите его в боковой панели." />;
  }

  return (
    <div className="page-shell" data-testid="workspace-boards-page">
      <section className="page-header">
        <div>
          <h2>{workspace?.name || 'Доски'}</h2>
          <p className="muted">Доски выбранного пространства.</p>
        </div>
        <div className="page-header__actions">
          {workspace ? (
            <Button onClick={() => navigate(paths.workspaceAccess(workspace.id))}>Доступ</Button>
          ) : null}
          <Button variant="ghost" onClick={() => navigate(paths.home)}>
            <Icon name="back" size={16} />
            К пространствам
          </Button>
        </div>
      </section>

      {canEdit ? <section className="panel">
        <div className="entity-header">
          <div>
            <h3>Новая доска</h3>
            <p className="muted">Название можно изменить позже.</p>
          </div>
        </div>
        <form className="inline-form" data-testid="board-create-form" onSubmit={handleCreate}>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <TextField data-testid="board-name-input" label="Название" value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, План релиза" />
            <TextAreaField data-testid="board-description-input" label="Описание" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Необязательно" />
          </div>
          <div className="inline-actions">
            <Button data-testid="board-create-submit" type="submit" variant="primary" disabled={createBoardMutation.isPending}>
              {createBoardMutation.isPending ? 'Создаём…' : 'Создать доску'}
            </Button>
          </div>
        </form>
      </section> : (
        <section className="panel">
          <h3>Режим чтения</h3>
          <p className="muted">Гость может просматривать доски, но не изменять их содержимое.</p>
        </section>
      )}

      {canEdit ? <BoardImportPanel
        workspaceId={workspaceId}
        existingBoardNames={boardsQuery.data?.items.map((board) => board.name) || []}
        onImported={async (boardId) => {
          await boardsQuery.refetch();
          navigate(paths.board(workspaceId, boardId));
        }}
      /> : null}

      {boardsQuery.isLoading ? <LoadingState label="Загружаем доски…" /> : null}
      {boardsQuery.isError ? <ErrorState title="Не удалось загрузить доски" onRetry={() => void boardsQuery.refetch()} /> : null}

      {!boardsQuery.isLoading && !boardsQuery.isError ? (
        boardsQuery.data?.items.length ? (
          <div className="grid grid--cards">
            {boardsQuery.data.items.map((board) => (
              <article key={board.id} className="board-card" data-testid="board-card">
                <div className="entity-header">
                  <div>
                    <h3>{board.name}</h3>
                    <p className="muted">{board.description || 'Без описания'}</p>
                  </div>
                  <div className="row-actions">
                    {board.isArchived ? <Badge tone="warning">в архиве</Badge> : null}
                  </div>
                </div>

                <div className="grid" style={{ marginTop: 12 }}>
                  <div className="meta-line">Изменена {formatDateTime(board.updatedAt)}</div>
                </div>

                <div className="page-header__actions" style={{ marginTop: 16 }}>
                  <Button data-testid="board-open" variant="primary" onClick={() => navigate(paths.board(workspaceId, board.id))}>
                    Открыть
                  </Button>
                  {canEdit ? <Button
                    iconOnly
                    onClick={() => void handleRename(board.id, board.name)}
                    disabled={updateBoardMutation.isPending}
                    title="Переименовать доску"
                    aria-label="Переименовать доску"
                  >
                    <Icon name="edit" size={16} />
                  </Button> : null}
                  {canEdit && !board.isArchived ? (
                    <Button
                      iconOnly
                      variant="danger"
                      onClick={() => void handleArchive(board.id, board.name)}
                      disabled={archiveBoardMutation.isPending}
                      title="Архивировать доску"
                      aria-label="Архивировать доску"
                  >
                    <Icon name="archive" size={16} />
                    </Button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="На этом узле пока нет досок" description="Новые доски другого узла не обнаруживаются автоматически. На странице пространств выберите «Получить новые доски от доверенного устройства» либо создайте доску здесь." />
        )
      ) : null}
    </div>
  );
}
