import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Alert, Share, StyleSheet, Text, View } from 'react-native';

import type { RootStackParamList } from '../../app/navigation/types';
import { radius, spacing, useAppColors } from '../../app/theme';
import {
  createWorkspaceInvitation,
  getWorkspace,
  getWorkspaceInvitations,
  getWorkspaceMembers,
  removeWorkspaceMember,
  revokeWorkspaceInvitation,
  updateWorkspaceMember,
} from '../../shared/api/endpoints';
import { getApiNodeOrigin } from '../../shared/api/client';
import type { WorkspaceMember } from '../../shared/types/api';
import {
  Button,
  FormModal,
  InlineNotice,
  Screen,
  ScreenHeader,
  StateView,
} from '../../shared/ui/primitives';

type Props = NativeStackScreenProps<RootStackParamList, 'WorkspaceAccess'>;

const roleLabel = {
  owner: 'Владелец',
  member: 'Участник',
  guest: 'Гость',
} as const;

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Не удалось изменить доступ.';
}

export function WorkspaceAccessScreen({ navigation, route }: Props) {
  const { workspaceId, workspaceName } = route.params;
  const colors = useAppColors();
  const queryClient = useQueryClient();
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteRole, setInviteRole] = useState<'member' | 'guest'>('member');
  const [expiresInHours, setExpiresInHours] = useState(24);
  const [lastInviteLink, setLastInviteLink] = useState<string | null>(null);

  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => getWorkspace(workspaceId),
  });
  const isOwner = workspaceQuery.data?.currentUserRole === 'owner';
  const membersQuery = useQuery({
    queryKey: ['workspace-members', workspaceId],
    queryFn: () => getWorkspaceMembers(workspaceId),
  });
  const invitationsQuery = useQuery({
    queryKey: ['workspace-invitations', workspaceId],
    queryFn: () => getWorkspaceInvitations(workspaceId),
    enabled: isOwner,
  });

  async function invalidateAccess() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ['workspace-members', workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ['workspace-invitations', workspaceId] }),
      queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
    ]);
  }

  const roleMutation = useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: 'member' | 'guest' }) =>
      updateWorkspaceMember(workspaceId, memberId, role),
    onSuccess: invalidateAccess,
  });
  const removeMutation = useMutation({
    mutationFn: (memberId: string) => removeWorkspaceMember(workspaceId, memberId),
    onSuccess: invalidateAccess,
  });
  const inviteMutation = useMutation({
    mutationFn: () => createWorkspaceInvitation(workspaceId, { role: inviteRole, expiresInHours }),
    onSuccess: async ({ token }) => {
      const origin = getApiNodeOrigin();
      if (!origin) throw new Error('Адрес узла не настроен.');
      const link = `${origin}/invite/${encodeURIComponent(token)}`;
      setLastInviteLink(link);
      setInviteOpen(false);
      await invalidateAccess();
      await Share.share({ message: link, title: `Приглашение в ${workspaceName}` });
    },
  });
  const revokeInviteMutation = useMutation({
    mutationFn: (invitationId: string) => revokeWorkspaceInvitation(workspaceId, invitationId),
    onSuccess: invalidateAccess,
  });

  function openMemberActions(member: WorkspaceMember) {
    if (!isOwner || member.role === 'owner' || member.status !== 'active') return;
    Alert.alert(member.displayName, 'Изменение роли или отзыв доступа сразу ротирует capability пространства.', [
      { text: 'Отмена', style: 'cancel' },
      {
        text: member.role === 'member' ? 'Сделать гостем' : 'Сделать участником',
        onPress: () => roleMutation.mutate({
          memberId: member.id,
          role: member.role === 'member' ? 'guest' : 'member',
        }),
      },
      {
        text: 'Отозвать доступ',
        style: 'destructive',
        onPress: () => removeMutation.mutate(member.id),
      },
    ]);
  }

  const error = workspaceQuery.error
    || membersQuery.error
    || invitationsQuery.error
    || roleMutation.error
    || removeMutation.error
    || inviteMutation.error
    || revokeInviteMutation.error;

  if (workspaceQuery.isPending && !workspaceQuery.data) {
    return (
      <Screen>
        <ScreenHeader title="Доступ" onBack={() => navigation.goBack()} />
        <StateView title="Загружаем участников" busy />
      </Screen>
    );
  }

  return (
    <Screen scroll contentStyle={styles.screen}>
      <ScreenHeader
        title={workspaceName}
        subtitle="Доступ и приглашения"
        onBack={() => navigation.goBack()}
        action={isOwner ? (
          <Button label="Пригласить" compact variant="primary" onPress={() => setInviteOpen(true)} />
        ) : undefined}
      />

      <InlineNotice
        tone="neutral"
        text={`Ваша роль: ${roleLabel[workspaceQuery.data?.currentUserRole || 'guest']}. Эпоха доступа: ${workspaceQuery.data?.accessEpoch || 1}.`}
      />
      {error ? <InlineNotice tone="danger" text={message(error)} /> : null}

      <View style={styles.section}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Участники</Text>
        {membersQuery.data?.items.filter((member) => member.status === 'active').map((member) => (
          <View
            key={member.id}
            style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}
          >
            <View style={styles.rowBody}>
              <Text style={[styles.name, { color: colors.text }]}>{member.displayName}</Text>
              <Text style={[styles.meta, { color: colors.muted }]}>{member.email}</Text>
            </View>
            <Text style={[styles.role, { color: colors.muted }]}>{roleLabel[member.role]}</Text>
            {isOwner && member.role !== 'owner' ? (
              <Button label="Изменить" compact variant="ghost" onPress={() => openMemberActions(member)} />
            ) : null}
          </View>
        ))}
      </View>

      {isOwner ? (
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: colors.text }]}>Приглашения</Text>
          {invitationsQuery.data?.items.map((invitation) => (
            <View
              key={invitation.id}
              style={[styles.row, { borderColor: colors.border, backgroundColor: colors.surface }]}
            >
              <View style={styles.rowBody}>
                <Text style={[styles.name, { color: colors.text }]}>{roleLabel[invitation.role]}</Text>
                <Text style={[styles.meta, { color: colors.muted }]}>
                  {invitation.status} · до {new Date(invitation.expiresAt).toLocaleString()}
                </Text>
              </View>
              {invitation.status === 'active' ? (
                <Button
                  label="Отозвать"
                  compact
                  variant="danger"
                  onPress={() => revokeInviteMutation.mutate(invitation.id)}
                />
              ) : null}
            </View>
          ))}
          {lastInviteLink ? (
            <InlineNotice
              tone="success"
              text="Последняя ссылка создана и передана в системное меню отправки. Повторно секрет на сервере не показывается."
            />
          ) : null}
        </View>
      ) : null}

      <FormModal
        visible={inviteOpen}
        title="Новое приглашение"
        onClose={() => !inviteMutation.isPending && setInviteOpen(false)}
      >
        <Text style={[styles.fieldLabel, { color: colors.text }]}>Роль</Text>
        <View style={styles.choiceRow}>
          <Button
            label="Участник"
            compact
            variant={inviteRole === 'member' ? 'primary' : 'secondary'}
            onPress={() => setInviteRole('member')}
          />
          <Button
            label="Гость"
            compact
            variant={inviteRole === 'guest' ? 'primary' : 'secondary'}
            onPress={() => setInviteRole('guest')}
          />
        </View>
        <Text style={[styles.fieldLabel, { color: colors.text }]}>Срок жизни</Text>
        <View style={styles.choiceRow}>
          {[24, 72, 168, 720].map((hours) => (
            <Button
              key={hours}
              label={hours === 24 ? '24 ч' : hours === 72 ? '3 дня' : hours === 168 ? '7 дней' : '30 дней'}
              compact
              variant={expiresInHours === hours ? 'primary' : 'secondary'}
              onPress={() => setExpiresInHours(hours)}
            />
          ))}
        </View>
        <Button
          label="Создать и отправить"
          variant="primary"
          loading={inviteMutation.isPending}
          onPress={() => inviteMutation.mutate()}
        />
      </FormModal>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingBottom: spacing.xl },
  section: { gap: spacing.sm },
  sectionTitle: { fontSize: 18, fontWeight: '700' },
  row: {
    minHeight: 64,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    padding: spacing.sm,
    borderWidth: 1,
    borderRadius: radius.md,
  },
  rowBody: { flex: 1, minWidth: 0, gap: 2 },
  name: { fontSize: 15, fontWeight: '600' },
  meta: { fontSize: 12 },
  role: { fontSize: 12, fontWeight: '600' },
  fieldLabel: { fontSize: 14, fontWeight: '700' },
  choiceRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
});
