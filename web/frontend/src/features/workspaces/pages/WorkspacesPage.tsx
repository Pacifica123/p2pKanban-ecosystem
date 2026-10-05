import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { paths } from '@/app/router/paths';
import { useArchiveWorkspaceMutation, useCreateWorkspaceMutation, useUpdateWorkspaceMutation, useWorkspacesQuery } from '@/features/workspaces/hooks/useWorkspaces';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { TextAreaField, TextField, SelectField } from '@/shared/ui/Field';
import { LoadingState } from '@/shared/ui/LoadingState';
import { Badge } from '@/shared/ui/Badge';
import { formatDateTime } from '@/shared/lib/date';
import { ApiError } from '@/shared/api/errors';
import { Icon } from '@/shared/ui/Icon';

const workspaceRoleLabel = {
  owner: 'владелец',
  member: 'участник',
  guest: 'гость',
} as const;

function getErrorMessage(error: unknown, fallback: string) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}

export function WorkspacesPage() {
  const navigate = useNavigate();
  const workspacesQuery = useWorkspacesQuery();
  const createWorkspaceMutation = useCreateWorkspaceMutation();
  const updateWorkspaceMutation = useUpdateWorkspaceMutation();
  const archiveWorkspaceMutation = useArchiveWorkspaceMutation();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [visibility, setVisibility] = useState<'private' | 'shared'>('private');

  function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) return;
    createWorkspaceMutation.mutate(
      {
        name: name.trim(),
        description: description.trim() || undefined,
        visibility,
      },
      {
        onSuccess: (workspace) => {
          setName('');
          setDescription('');
          setVisibility('private');
          navigate(paths.workspaceBoards(workspace.id));
        },
      },
    );
  }

  async function handleRename(workspaceId: string, currentName: string) {
    const next = window.prompt('Новое название пространства', currentName)?.trim();
    if (!next || next === currentName) return;
    await updateWorkspaceMutation.mutateAsync({ workspaceId, input: { name: next } });
  }

  async function handleArchive(workspaceId: string, nameValue: string) {
    if (!window.confirm(`Архивировать пространство «${nameValue}»?`)) return;
    await archiveWorkspaceMutation.mutateAsync(workspaceId);
  }

  return (
    <div className="page-shell" data-testid="workspace-list-page">
      <section className="page-header">
        <div>
          <h2>Рабочие пространства</h2>
          <p className="muted">Отдельные проекты, команды и личные планы.</p>
        </div>
      </section>

      <section className="panel">
        <div className="entity-header">
          <div>
            <h3>Новое пространство</h3>
            <p className="muted">Название и доступ можно изменить позже.</p>
          </div>
        </div>

        <form className="inline-form" data-testid="workspace-create-form" onSubmit={handleCreate}>
          <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <TextField data-testid="workspace-name-input" label="Название" value={name} onChange={(event) => setName(event.target.value)} placeholder="Например, Учёба" />
            <SelectField label="Доступ" value={visibility} onChange={(event) => setVisibility(event.target.value as 'private' | 'shared')}>
              <option value="private">Личное</option>
              <option value="shared">Общее</option>
            </SelectField>
          </div>
          <TextAreaField data-testid="workspace-description-input" label="Описание" value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Необязательно" />
          <div className="inline-actions">
            <Button data-testid="workspace-create-submit" type="submit" variant="primary" disabled={createWorkspaceMutation.isPending}>
              {createWorkspaceMutation.isPending ? 'Создаём…' : 'Создать пространство'}
            </Button>
          </div>
          {createWorkspaceMutation.isError ? (
            <ErrorState compact title="Не удалось создать пространство" description={getErrorMessage(createWorkspaceMutation.error, 'Проверьте соединение и введённые данные.')} />
          ) : null}
        </form>
      </section>

      {workspacesQuery.isLoading ? <LoadingState label="Загружаем пространства…" /> : null}
      {workspacesQuery.isError ? (
        <ErrorState
          title="Не удалось загрузить пространства"
          description={getErrorMessage(workspacesQuery.error, 'Обновите данные или проверьте соединение с сервером.')}
          onRetry={() => void workspacesQuery.refetch()}
        />
      ) : null}

      {!workspacesQuery.isLoading && !workspacesQuery.isError ? (
        workspacesQuery.data?.items.length ? (
          <div className="grid grid--cards">
            {workspacesQuery.data.items.map((workspace) => (
              <article key={workspace.id} className="workspace-card" data-testid="workspace-card">
                <div className="entity-header">
                  <div>
                    <h3>{workspace.name}</h3>
                    <p className="muted">{workspace.description || 'Без описания'}</p>
                  </div>
                  <div className="row-actions">
                    <Badge tone={workspace.visibility}>{workspace.visibility === 'shared' ? 'общее' : 'личное'}</Badge>
                    {workspace.currentUserRole ? (
                      <Badge tone={workspace.currentUserRole}>{workspaceRoleLabel[workspace.currentUserRole]}</Badge>
                    ) : null}
                    {workspace.isArchived ? <Badge tone="warning">в архиве</Badge> : null}
                  </div>
                </div>

                <div className="grid" style={{ marginTop: 12 }}>
                  <div className="meta-line">Изменено {formatDateTime(workspace.updatedAt)}</div>
                  <div className="meta-line">Участников: {workspace.memberCount ?? 0}</div>
                </div>

                <div className="page-header__actions" style={{ marginTop: 16 }}>
                  <Button data-testid="workspace-open-boards" variant="primary" onClick={() => navigate(paths.workspaceBoards(workspace.id))}>
                    Открыть доски
                  </Button>
                  <Button onClick={() => navigate(paths.workspaceAccess(workspace.id))}>
                    Доступ
                  </Button>
                  {workspace.currentUserRole === 'owner' ? (
                    <Button
                      iconOnly
                      onClick={() => void handleRename(workspace.id, workspace.name)}
                      disabled={updateWorkspaceMutation.isPending}
                      title="Переименовать пространство"
                      aria-label="Переименовать пространство"
                    >
                      <Icon name="edit" size={16} />
                    </Button>
                  ) : null}
                  {workspace.currentUserRole === 'owner' && !workspace.isArchived ? (
                    <Button
                      iconOnly
                      variant="danger"
                      onClick={() => void handleArchive(workspace.id, workspace.name)}
                      disabled={archiveWorkspaceMutation.isPending}
                      title="Архивировать пространство"
                      aria-label="Архивировать пространство"
                    >
                      <Icon name="archive" size={16} />
                    </Button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Пока нет ни одного пространства" description="Создайте первое пространство для своих досок." />
        )
      ) : null}
    </div>
  );
}
