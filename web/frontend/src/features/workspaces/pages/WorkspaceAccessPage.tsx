import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { paths } from '@/app/router/paths';
import {
  useWorkspaceAccessMutations,
  useWorkspaceAccessQueries,
  useWorkspaceQuery,
} from '@/features/workspaces/hooks/useWorkspaces';
import { ApiError } from '@/shared/api/errors';
import { formatDateTime } from '@/shared/lib/date';
import type { WorkspaceRole } from '@/shared/types/api';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SelectField } from '@/shared/ui/Field';
import { LoadingState } from '@/shared/ui/LoadingState';

const roleLabels: Record<WorkspaceRole, string> = {
  owner: 'Владелец',
  member: 'Участник',
  guest: 'Гость',
};

function errorText(error: unknown) {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'Операция не выполнена.';
}

export function WorkspaceAccessPage() {
  const { workspaceId } = useParams();
  const navigate = useNavigate();
  const workspaceQuery = useWorkspaceQuery(workspaceId);
  const isOwner = workspaceQuery.data?.currentUserRole === 'owner';
  const { members, invitations } = useWorkspaceAccessQueries(workspaceId, isOwner);
  const mutations = useWorkspaceAccessMutations(workspaceId || '');
  const [inviteRole, setInviteRole] = useState<'member' | 'guest'>('member');
  const [expiresInHours, setExpiresInHours] = useState(24);
  const [createdLink, setCreatedLink] = useState<string | null>(null);
  const [copyLabel, setCopyLabel] = useState('Копировать ссылку');

  if (!workspaceId) {
    return <ErrorState title="Пространство не выбрано" />;
  }
  if (workspaceQuery.isLoading) return <LoadingState label="Загружаем права доступа…" />;
  if (workspaceQuery.isError || !workspaceQuery.data) {
    return (
      <ErrorState
        title="Не удалось открыть управление доступом"
        description={errorText(workspaceQuery.error)}
        onRetry={() => void workspaceQuery.refetch()}
      />
    );
  }

  const workspace = workspaceQuery.data;

  async function createInvite() {
    const result = await mutations.createInvitation.mutateAsync({
      role: inviteRole,
      expiresInHours,
    });
    setCreatedLink(`${window.location.origin}${paths.invitation(result.token)}`);
    setCopyLabel('Копировать ссылку');
  }

  async function copyInvite() {
    if (!createdLink) return;
    await navigator.clipboard.writeText(createdLink);
    setCopyLabel('Скопировано');
  }

  async function changeRole(memberId: string, role: 'member' | 'guest') {
    await mutations.updateMember.mutateAsync({ memberId, role });
  }

  async function removeMember(memberId: string, displayName: string) {
    if (!window.confirm(`Отозвать доступ у «${displayName}»? Старые capability и офлайн-записи этого состава будут отозваны.`)) return;
    await mutations.removeMember.mutateAsync(memberId);
  }

  return (
    <div className="page-shell" data-testid="workspace-access-page">
      <section className="page-header">
        <div>
          <h2>Доступ: {workspace.name}</h2>
          <p className="muted">
            Владелец управляет составом, участник редактирует доски, гость только читает.
          </p>
        </div>
        <div className="page-header__actions">
          <Badge tone={workspace.currentUserRole || 'default'}>
            {workspace.currentUserRole ? roleLabels[workspace.currentUserRole] : 'Нет доступа'}
          </Badge>
          <Button variant="ghost" onClick={() => navigate(paths.workspaceBoards(workspaceId))}>
            К доскам
          </Button>
        </div>
      </section>

      <section className="panel">
        <div className="entity-header">
          <div>
            <h3>Участники</h3>
            <p className="muted">
              Эпоха доступа {workspace.accessEpoch ?? 1}. Она меняется при любом изменении состава или роли.
            </p>
          </div>
        </div>
        {members.isLoading ? <LoadingState label="Загружаем участников…" /> : null}
        {members.isError ? <ErrorState compact title="Не удалось загрузить участников" description={errorText(members.error)} /> : null}
        <div className="access-list">
          {members.data?.items.map((member) => (
            <div className="access-row" key={member.id}>
              <div className="access-row__identity">
                <strong>{member.displayName}</strong>
                <span className="muted">{member.email}</span>
              </div>
              <div className="access-row__actions">
                {isOwner && member.role !== 'owner' && member.status === 'active' ? (
                  <>
                    <label className="field field--compact">
                      <span className="field__label">Роль</span>
                      <select
                        className="field__select"
                        value={member.role}
                        disabled={mutations.updateMember.isPending}
                        onChange={(event) => void changeRole(member.id, event.target.value as 'member' | 'guest')}
                      >
                        <option value="member">Участник</option>
                        <option value="guest">Гость</option>
                      </select>
                    </label>
                    <Button
                      variant="danger"
                      disabled={mutations.removeMember.isPending}
                      onClick={() => void removeMember(member.id, member.displayName)}
                    >
                      Отозвать
                    </Button>
                  </>
                ) : (
                  <Badge tone={member.role}>{roleLabels[member.role]}</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {isOwner ? (
        <section className="panel">
          <div className="entity-header">
            <div>
              <h3>Новая пригласительная ссылка</h3>
              <p className="muted">Ссылка одноразовая; срок жизни — от часа до 30 дней.</p>
            </div>
          </div>
          <div className="grid access-invite-form">
            <SelectField label="Роль" value={inviteRole} onChange={(event) => setInviteRole(event.target.value as 'member' | 'guest')}>
              <option value="member">Участник — чтение и изменения</option>
              <option value="guest">Гость — только чтение</option>
            </SelectField>
            <SelectField label="Срок жизни" value={expiresInHours} onChange={(event) => setExpiresInHours(Number(event.target.value))}>
              <option value={1}>1 час</option>
              <option value={24}>24 часа</option>
              <option value={72}>3 дня</option>
              <option value={168}>7 дней</option>
              <option value={720}>30 дней</option>
            </SelectField>
            <Button variant="primary" disabled={mutations.createInvitation.isPending} onClick={() => void createInvite()}>
              {mutations.createInvitation.isPending ? 'Создаём…' : 'Создать ссылку'}
            </Button>
          </div>
          {mutations.createInvitation.isError ? (
            <ErrorState compact title="Не удалось создать приглашение" description={errorText(mutations.createInvitation.error)} />
          ) : null}
          {createdLink ? (
            <div className="invite-link" data-testid="created-invitation-link">
              <code>{createdLink}</code>
              <Button onClick={() => void copyInvite()}>{copyLabel}</Button>
            </div>
          ) : null}

          <div className="access-list">
            {invitations.data?.items.map((invitation) => (
              <div className="access-row" key={invitation.id}>
                <div className="access-row__identity">
                  <strong>{roleLabels[invitation.role]}</strong>
                  <span className="muted">До {formatDateTime(invitation.expiresAt)}</span>
                </div>
                <div className="access-row__actions">
                  <Badge tone={invitation.status}>{invitation.status}</Badge>
                  {invitation.status === 'active' ? (
                    <Button
                      variant="danger"
                      disabled={mutations.revokeInvitation.isPending}
                      onClick={() => void mutations.revokeInvitation.mutateAsync(invitation.id)}
                    >
                      Отозвать ссылку
                    </Button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : (
        <section className="panel">
          <p className="muted">Создавать приглашения и менять состав может только владелец.</p>
        </section>
      )}
    </div>
  );
}
