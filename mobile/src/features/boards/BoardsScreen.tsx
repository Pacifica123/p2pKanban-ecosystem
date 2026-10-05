import { prepareDeviceLink } from '../deviceLink/service';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import {getApiNodeOrigin} from '../../shared/api/client';
import {isPrivateNodeOrigin} from '../connection/connection';
import {listLocalReplicaBoards} from '../localFirst/repository';
import {refreshDeviceCatalog} from '../roaming/catalog';
import { useAuth } from '../auth/AuthProvider';
import type { RootStackParamList } from '../../app/navigation/types';
import { radius, spacing, useAppColors } from '../../app/theme';
import {
  archiveBoard,
  createBoard,
  deleteBoard,
  getBoards,
  updateBoard,
} from '../../shared/api/endpoints';
import {
  loadCachedBoards,
  saveCachedBoards,
} from '../../shared/storage/storage';
import type { Board } from '../../shared/types/api';
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
import {
  primeWorkspaceBoards,
  type PrimeBoardsResult,
} from '../roaming/primeBoards';

type Props = NativeStackScreenProps<RootStackParamList, 'Boards'>;

export function BoardsScreen({ navigation, route }: Props) {
  const {
    workspaceId,
    workspaceName,
    workspaceRole = 'member',
    accessEpoch = 1,
  } = route.params;
  const canEdit = workspaceRole === 'owner' || workspaceRole === 'member';
  const colors = useAppColors();
  const { user } = useAuth();
  const { isOnline, networkType } = useNetwork();
  const privateHttpNode = isPrivateNodeOrigin(getApiNodeOrigin());
  const preferReplicaCatalog = networkType === 'cellular' && privateHttpNode;
  const queryClient = useQueryClient();
  const [cached, setCached] = useState<Board[]>([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingBoard, setEditingBoard] = useState<Board | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [primeState, setPrimeState] = useState<
    { status: 'idle' | 'running' | 'done'; result: PrimeBoardsResult | null }
  >({ status: 'idle', result: null });

  useEffect(() => {
    let active=true;
    void Promise.all([loadCachedBoards(workspaceId),listLocalReplicaBoards(workspaceId)])
      .then(([saved,replicas])=>{
        if(!active)return;
        setCached([...new Map([...saved,...replicas].map(board=>[board.id,board])).values()]);
      });
    return()=>{active=false;};
  }, [workspaceId]);

  const query = useQuery({
    queryKey: ['boards', workspaceId],
    queryFn: async () => {
      let response;
      try { response = await getBoards(workspaceId); }
      catch (error) {
        const local = await loadCachedBoards(workspaceId);
        if (local.length) return { items: local };
        throw error;
      }
      await saveCachedBoards(workspaceId, response.items);
      setCached(response.items);
      return response;
    },
    enabled: isOnline && !preferReplicaCatalog,
  });

  const saveMutation = useMutation({
    mutationFn: () => editingBoard
      ? updateBoard(editingBoard.id, {
        name: name.trim(),
        description: description.trim() || null,
      })
      : createBoard(workspaceId, {
        name: name.trim(),
        description: description.trim() || undefined,
      }),
    onSuccess: async () => {
      setModalVisible(false);
      setEditingBoard(null);
      setName('');
      setDescription('');
      setFormError(null);
      await queryClient.invalidateQueries({ queryKey: ['boards', workspaceId] });
    },
    onError: (error) => setFormError(error instanceof Error ? error.message : 'Не удалось сохранить доску.'),
  });

  const archiveMutation = useMutation({
    mutationFn: (boardId: string) => archiveBoard(boardId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boards', workspaceId] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (boardId: string) => deleteBoard(boardId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['boards', workspaceId] }),
  });

  const items = [...new Map([...(query.data?.items || []), ...cached].map(board => [board.id, board])).values()];
  useEffect(() => {
    if (!isOnline) return;
    let active = true;
    let busy = false;
    const refreshCatalog = async () => {
      if (busy) return;
      busy = true;
      try {
        const boards = await refreshDeviceCatalog(workspaceId, user?.id);
        if (active && boards.length) setCached(current =>
          [...new Map([...current, ...boards].map(board => [board.id, board])).values()]);
      } catch { /* Local replica stays usable during a relay outage. */ }
      finally { busy = false; }
    };
    void refreshCatalog();
    const timer = setInterval(() => { void refreshCatalog(); }, 30_000);
    return () => { active = false; clearInterval(timer); };
  }, [isOnline, workspaceId, networkType, user?.id]);
  const boardIds = items.map((board) => board.id).join('|');

  function openCreate() {
    if (!canEdit) return;
    setEditingBoard(null);
    setName('');
    setDescription('');
    setFormError(null);
    setModalVisible(true);
  }

  function openActions(board: Board) {
    if (!canEdit) return;
    Alert.alert(board.name, 'Выберите действие с доской.', [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Изменить',
        onPress: () => {
          setEditingBoard(board);
          setName(board.name);
          setDescription(board.description || '');
          setFormError(null);
          setModalVisible(true);
        },
      },
      ...(!board.isArchived ? [{
        text: 'Архивировать',
        onPress: () => archiveMutation.mutate(board.id),
      }] : []),
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          Alert.alert(
            'Удалить доску безвозвратно?',
            'Все колонки, карточки и связанные данные будут удалены.',
            [
              { text: 'Отмена', style: 'cancel' },
              {
                text: 'Удалить',
                style: 'destructive',
                onPress: () => deleteMutation.mutate(board.id),
              },
            ],
          );
        },
      },
    ]);
  }

  useEffect(() => {
    if (!isOnline || !items.length) return;
    let active = true;
    setPrimeState({ status: 'running', result: null });
    void primeWorkspaceBoards(workspaceId, items, networkType === 'wifi' || networkType === 'ethernet').then((result) => {
      if (active) {
        setPrimeState({ status: 'done', result });
        if (workspaceRole === 'owner' && result.failed === 0) void prepareDeviceLink().catch(() => undefined);
      }
    });
    return () => {
      active = false;
    };
  }, [boardIds, isOnline, networkType, workspaceId]);

  return (
    <Screen scroll contentStyle={styles.screen}>
      <ScreenHeader
        title={workspaceName}
        subtitle={workspaceRole === 'guest' ? 'Доски · только чтение' : 'Доски'}
        onBack={() => navigation.goBack()}
        action={(
          <Button
            label="Доступ"
            compact
            variant="ghost"
            onPress={() => navigation.navigate('WorkspaceAccess', {
              workspaceId,
              workspaceName,
            })}
          />
        )}
      />

      {query.isError && items.length > 0 ? <InlineNotice text="Прямой узел недоступен. Открывайте сохранённые доски: relay-связь проверяется отдельно. Новые доски от ПК пока не получены." tone="warning" /> : null}
      {!isOnline ? (
        <InlineNotice text="Нет связи. Открываются только сохранённые доски." tone="warning" />
      ) : null}
      {primeState.status === 'running' ? (
        <InlineNotice
          text="Проверяем локальные реплики досок…"
          tone="neutral"
        />
      ) : null}
      {primeState.status === 'done' && primeState.result?.failed ? (
        <InlineNotice
          text={`${formatCountRu(primeState.result.failed, 'доску', 'доски', 'досок')} пока не удалось восстановить. Для нового устройства нужен ключ; для известной доски — сохранённый снимок или доступный relay.`}
          tone="warning"
        />
      ) : null}

      <View style={styles.toolbar}>
        <Text style={[styles.summary, { color: colors.muted }]}>
          {formatCountRu(items.length, 'доска', 'доски', 'досок')}
        </Text>
        {canEdit ? <Button
          label="Создать"
          compact
          variant="primary"
          disabled={!isOnline}
          onPress={openCreate}
        /> : null}
      </View>

      {query.isPending && !items.length && !preferReplicaCatalog ? <StateView title="Загружаем доски" busy /> : null}

      {query.isError && !items.length && !privateHttpNode ? (
        <StateView
          title="Доски недоступны"
          description={query.error instanceof Error ? query.error.message : 'Не удалось получить данные.'}
          action={<Button label="Повторить" onPress={() => void query.refetch()} />}
        />
      ) : null}

      {(!query.isPending || preferReplicaCatalog) && !items.length ? (
        <StateView
          title="Досок пока нет"
          description={isOnline && !preferReplicaCatalog
            ? 'Создайте первую доску в этом пространстве.'
            : 'После подключения здесь появятся сохранённые доски.'}
          action={isOnline && !preferReplicaCatalog && canEdit
            ? <Button label="Создать доску" variant="primary" onPress={openCreate} />
            : undefined}
        />
      ) : null}

      <View style={styles.list}>
        {items.map((board) => (
          <Pressable
            key={board.id}
            onLongPress={canEdit ? () => openActions(board) : undefined}
            onPress={() => navigation.navigate('Board', {
              workspaceId,
              boardId: board.id,
              boardName: board.name,
              workspaceRole,
              accessEpoch,
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
              <Text style={[styles.rowTitle, { color: colors.text }]}>{board.name}</Text>
              <Text style={[styles.rowDescription, { color: colors.muted }]} numberOfLines={2}>
                {board.description || 'Без описания'}
              </Text>
              <Text style={[styles.rowHint, { color: colors.muted }]}>
                {workspaceRole === 'guest'
                  ? 'Только чтение'
                  : board.isArchived
                    ? 'В архиве · удерживайте для действий'
                    : 'Удерживайте для изменения, архива или удаления'}
              </Text>
            </View>
            <Text style={[styles.chevron, { color: colors.muted }]}>›</Text>
          </Pressable>
        ))}
      </View>

      <FormModal
        visible={modalVisible}
        title={editingBoard ? 'Изменить доску' : 'Новая доска'}
        onClose={() => {
          if (!saveMutation.isPending) {
            setModalVisible(false);
            setEditingBoard(null);
          }
        }}
      >
        <Field
          label="Название"
          value={name}
          onChangeText={setName}
          autoFocus
          placeholder="Разработка"
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
          label={editingBoard ? 'Сохранить' : 'Создать'}
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
