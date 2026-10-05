import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { paths } from '@/app/router/paths';
import {
  acceptWorkspaceInvitation,
  previewWorkspaceInvitation,
} from '@/features/workspaces/api/workspaces';
import { workspacesQueryKey } from '@/features/workspaces/hooks/useWorkspaces';
import { formatDateTime } from '@/shared/lib/date';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { LoadingState } from '@/shared/ui/LoadingState';
import { Panel } from '@/shared/ui/Panel';

export function InvitationAcceptPage() {
  const { token = '' } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const preview = useQuery({
    queryKey: ['workspace-invitation-preview', token],
    queryFn: () => previewWorkspaceInvitation(token),
    enabled: Boolean(token),
  });
  const accept = useMutation({
    mutationFn: () => acceptWorkspaceInvitation(token),
    onSuccess: async (workspace) => {
      await queryClient.invalidateQueries({ queryKey: workspacesQueryKey });
      navigate(paths.workspaceBoards(workspace.id), { replace: true });
    },
  });

  if (preview.isLoading) return <LoadingState label="Проверяем приглашение…" />;
  if (preview.isError || !preview.data) {
    return <ErrorState title="Приглашение недоступно" description="Ссылка неверна, отозвана или уже не существует." />;
  }

  const invitation = preview.data;
  const active = invitation.status === 'active';
  return (
    <div className="content-stack" style={{ maxWidth: 620, margin: '40px auto' }}>
      <Panel
        title={`Приглашение в «${invitation.workspaceName}»`}
        description={invitation.role === 'member'
          ? 'Роль участника: можно читать и изменять доски.'
          : 'Роль гостя: доски доступны только для чтения.'}
      >
        <p className="muted">Действует до {formatDateTime(invitation.expiresAt)}</p>
        {!active ? <p className="error-text">Ссылка уже {invitation.status} и не может быть использована.</p> : null}
        {accept.isError ? <ErrorState compact title="Не удалось принять приглашение" description={accept.error instanceof Error ? accept.error.message : undefined} /> : null}
        <div className="toolbar">
          <Button variant="primary" disabled={!active || accept.isPending} onClick={() => accept.mutate()}>
            {accept.isPending ? 'Подключаем…' : 'Принять приглашение'}
          </Button>
          <Button variant="ghost" onClick={() => navigate(paths.home)}>Отмена</Button>
        </div>
      </Panel>
    </div>
  );
}
