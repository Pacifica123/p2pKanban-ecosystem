import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import { getApiNodeOrigin } from '../../shared/api/client';
import { isPrivateNodeOrigin } from '../connection/connection';
import { refreshWorkspaceCatalog } from '../roaming/catalog';
import type { RootStackParamList } from '../../app/navigation/types';
import { radius, spacing, useAppColors } from '../../app/theme';
import {
  archiveWorkspace,
  createWorkspace,
  deleteWorkspace,
  getWorkspaces,
  updateWorkspace,
} from '../../shared/api/endpoints';
import {
  loadCachedWorkspaces,
  saveCachedWorkspaces,
} from '../../shared/storage/storage';
import type { Workspace } from '../../shared/types/api';
import { formatCountRu } from '../../shared/lib/russian';
import {
  Button,
  Field,
  FormModal,
  InlineNotice,
  Screen,
  ScreenHeader,
  StateView,
} from '../../shared/ui/primitives';
import { useAuth } from '../auth/AuthProvider';

type Props = NativeStackScreenProps<RootStackParamList, 'Workspaces'>;

export function WorkspacesScreen({ navigation }: Props) {
  const colors = useAppColors();
  const { isOnline, networkType } = useNetwork();
  const auth = useAuth();
  const queryClient = useQueryClient();
  const [cached, setCached] = useState<Workspace[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingWorkspace, setEditingWorkspace] = useState<Workspace | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    void loadCachedWorkspaces().then(setCached);
  }, []);

  const query = useQuery({
    queryKey: ['workspaces'],
    queryFn: async () => {
      const response = await getWorkspaces();
      await saveCachedWorkspaces(response.items);
      setCached(response.items);
      return response;
    },
    enabled: isOnline && !(networkType === 'cellular' && isPrivateNodeOrigin(getApiNodeOrigin())),
  });
  useEffect(() => {
    if (!isOnline || !auth.user?.id) return;
    let active = true;
    let busy = false;
    const refreshCatalog = async () => {
      if (busy) return;
      busy = true;
      try {
        const workspaces = await refreshWorkspaceCatalog(auth.user!.id);
        if (active) setCached(workspaces);
      } catch { /* A failed HTTP or relay request cannot erase cached spaces. */ }
      finally { busy = false; }
    };
    void refreshCatalog();
    const timer = setInterval(() => { void refreshCatalog(); }, 30_000);
    return () => { active = false; clearInterval(timer); };
  }, [isOnline, networkType, auth.user?.id]);

  const saveMutation = useMutation({
    mutationFn: () => editingWorkspace
      ? updateWorkspace(editingWorkspace.id, {
        name: name.trim(),
        description: description.trim() || null,
      })
      : createWorkspace({
        name: name.trim(),
        description: description.trim() || undefined,
        visibility: 'private',
      }),
    onSuccess: async () => {
      setModalVisible(false);
      setEditingWorkspace(null);
      setName('');
      setDescription('');
      setFormError(null);
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
    onError: (error) => setFormError(error instanceof Error ? error.message : 'Не удалось сохранить пространство.'),
  });

  const archiveMutation = useMutation({
    mutationFn: (workspaceId: string) => archiveWorkspace(workspaceId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (workspaceId: string) => deleteWorkspace(workspaceId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] });
    },
  });

  const items = query.data?.items?.length ? [...new Map([...query.data.items,...cached].map(w=>[w.id,w])).values()] : cached;

  function openCreate() {
    setEditingWorkspace(null);
    setName('');
    setDescription('');
    setFormError(null);
    setModalVisible(true);
  }

  function openActions(workspace: Workspace) {
    if (workspace.currentUserRole !== 'owner') return;
    Alert.alert(workspace.name, 'Выберите действие с пространством.', [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Доступ и приглашения',
        onPress: () => navigation.navigate('WorkspaceAccess', {
          workspaceId: workspace.id,
          workspaceName: workspace.name,
        }),
      },
      {
        text: 'Изменить',
        onPress: () => {
          setEditingWorkspace(workspace);
          setName(workspace.name);
          setDescription(workspace.description || '');
          setFormError(null);
          setModalVisible(true);
        },
      },
      ...(!workspace.isArchived ? [{
        text: 'Архивировать',
        onPress: () => archiveMutation.mutate(workspace.id),
      }] : []),
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          Alert.alert(
            'Удалить пространство безвозвратно?',
            'Все доски, карточки и связанные данные будут удалены.',
            [
              { text: 'Отмена', style: 'cancel' },
              {
                text: 'Удалить',
                style: 'destructive',
                onPress: () => deleteMutation.mutate(workspace.id),
              },
            ],
          );
        },
      },
    ]);
  }

  return (
    <Screen scroll contentStyle={styles.screen}>
      <ScreenHeader
        title="Пространства"
        subtitle={auth.isOfflineSession ? 'Офлайн-копия' : auth.user?.displayName}
        action={(
          <Button
            label="Настройки"
            compact
            variant="ghost"
            onPress={() => navigation.navigate('Settings')}
          />
        )}
      />

      {!isOnline ? (
        <InlineNotice
          text="Нет связи с узлом. Доступны сохранённые пространства и доски."
          tone="warning"
        />
      ) : null}

      <View style={styles.toolbar}>
        <Text style={[styles.summary, { color: colors.muted }]}>
          {formatCountRu(items.length, 'пространство', 'пространства', 'пространств')}
        </Text>
        <Button
          label="Создать"
          compact
          variant="primary"
          disabled={!isOnline}
          onPress={openCreate}
        />
      </View>

      {query.isPending && !items.length ? (
        <StateView title="Загружаем пространства" busy />
      ) : null}

      {query.isError && !items.length ? (
        <StateView
          title="Пространства недоступны"
          description={query.error instanceof Error ? query.error.message : 'Не удалось получить данные.'}
          action={<Button label="Повторить" onPress={() => void query.refetch()} />}
        />
      ) : null}

      {!query.isPending && !items.length ? (
        <StateView
          title="Пока пусто"
          description={isOnline
            ? 'Создайте первое пространство для досок.'
            : 'Подключитесь к узлу, чтобы создать первое пространство.'}
          action={isOnline
            ? <Button label="Создать пространство" variant="primary" onPress={openCreate} />
            : undefined}
        />
      ) : null}

      <View style={styles.list}>
        {items.map((workspace) => (
          <Pressable
            key={workspace.id}
            onLongPress={workspace.currentUserRole === 'owner'
              ? () => openActions(workspace)
              : undefined}
            onPress={() => navigation.navigate('Boards', {
              workspaceId: workspace.id,
              workspaceName: workspace.name,
              workspaceRole: workspace.currentUserRole || 'guest',
              accessEpoch: workspace.accessEpoch || 1,
            })}
            style={({ pressed }) => [
              styles.row,
              {
                backgroundColor: colors.surface,
                borderColor: colors.border,
                opacity: pressed ? 0.7 : 1,
              },
            ]}
          >
            <View style={styles.rowBody}>
              <Text style={[styles.rowTitle, { color: colors.text }]}>{workspace.name}</Text>
              <Text style={[styles.rowDescription, { color: colors.muted }]} numberOfLines={2}>
                {workspace.description || (workspace.visibility === 'private' ? 'Личное пространство' : 'Общее пространство')}
              </Text>
              <Text style={[styles.rowHint, { color: colors.muted }]}> 
                {workspace.currentUserRole === 'owner'
                  ? (workspace.isArchived
                    ? 'Владелец · в архиве · удерживайте для действий'
                    : 'Владелец · удерживайте для управления')
                  : workspace.currentUserRole === 'member'
                    ? 'Участник · можно изменять доски'
                    : 'Гость · только чтение'}
              </Text>
            </View>
            <Text style={[styles.chevron, { color: colors.muted }]}>›</Text>
          </Pressable>
        ))}
      </View>

      <FormModal
        visible={modalVisible}
        title={editingWorkspace ? 'Изменить пространство' : 'Новое пространство'}
        onClose={() => {
          if (!saveMutation.isPending) {
            setModalVisible(false);
            setEditingWorkspace(null);
          }
        }}
      >
        <Field
          label="Название"
          value={name}
          onChangeText={setName}
          autoFocus
          placeholder="Например, p2pKanban"
        />
        <Field
          label="Описание"
          value={description}
          onChangeText={setDescription}
          multiline
          placeholder="Необязательно"
        />
        {formError ? <InlineNotice text={formError} tone="danger" /> : null}
        <Button
          label={editingWorkspace ? 'Сохранить' : 'Создать'}
          variant="primary"
          loading={saveMutation.isPending}
          disabled={!name.trim()}
          onPress={() => saveMutation.mutate()}
        />
      </FormModal>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: {
    paddingBottom: spacing.xl,
  },
  toolbar: {
    minHeight: 40,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  summary: {
    fontSize: 13,
  },
  list: {
    gap: spacing.sm,
  },
  row: {
    minHeight: 82,
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  rowBody: {
    flex: 1,
    gap: spacing.xs,
  },
  rowTitle: {
    fontSize: 17,
    fontWeight: '700',
  },
  rowDescription: {
    fontSize: 13,
    lineHeight: 18,
  },
  rowHint: {
    fontSize: 10,
    lineHeight: 14,
  },
  chevron: {
    fontSize: 28,
    paddingLeft: spacing.sm,
  },
});
