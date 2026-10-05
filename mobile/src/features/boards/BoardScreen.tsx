import {orderCards} from '../../shared/lib/cardOrder';
import {getAdjacentPosition} from './cardDrag';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useFocusEffect } from '@react-navigation/native';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  BackHandler,
  PanResponder,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import { ColorOverrideProvider } from '../../app/ColorOverrideProvider';
import type { RootStackParamList } from '../../app/navigation/types';
import {
  radius,
  spacing,
  type AppColors,
  useAppColors,
  useResolvedTheme,
} from '../../app/theme';
import {
  createColumn,
  deleteColumn,
  updateColumn,
} from '../../shared/api/endpoints';
import type { BoardAppearanceSettings, BoardColumn, Card } from '../../shared/types/api';
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
import { CardDetailsModal } from '../cards/CardDetailsModal';
import { BoardAppearanceModal } from '../appearance/BoardAppearanceModal';
import {
  defaultBoardAppearance,
  resolveBoardPalette,
  type BoardPalette,
} from '../appearance/boardTheme';
import { useLocalBoard } from '../localFirst/useLocalBoard';
import {
  getAppendPosition,
  getDropColumnIndex,
  getEdgeScrollOffset,
} from './cardDrag';
import { createBoardExitController } from './boardExit';

type Props = NativeStackScreenProps<RootStackParamList, 'Board'>;

const priorityStars: Record<string, string> = {
  low: '★',
  medium: '★★',
  high: '★★★',
  urgent: '★★★★',
};

function DragHandle({
  onStart,
  onMove,
  onEnd,
  onCancel,
}: {
  onStart: (pageX: number, pageY: number) => void;
  onMove: (pageX: number, pageY: number) => void;
  onEnd: () => void;
  onCancel: () => void;
}) {
  const colors = useAppColors();
  const responder = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: (event) => {
      onStart(event.nativeEvent.pageX, event.nativeEvent.pageY);
    },
    onPanResponderMove: (event) => {
      onMove(event.nativeEvent.pageX, event.nativeEvent.pageY);
    },
    onPanResponderRelease: onEnd,
    onPanResponderTerminate: onCancel,
    onPanResponderTerminationRequest: () => false,
  }), [onCancel, onEnd, onMove, onStart]);

  return (
    <View
      {...responder.panHandlers}
      accessibilityRole="adjustable"
      accessibilityLabel="Перетащить карточку"
      style={[styles.dragHandle, { backgroundColor: colors.surfaceMuted }]}
    >
      <Text style={[styles.dragHandleText, { color: colors.muted }]}>≡</Text>
    </View>
  );
}

function formatCardDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' });
}

function CardPreview({
  card,
  appearance,
  palette,
  operationState,
  draggable,
  onPress, onMoveUp, onMoveDown,
  onDragStart,
  onDragMove,
  onDragEnd,
  onDragCancel,
}: {
  card: Card;
  appearance: BoardAppearanceSettings;
  palette: BoardPalette;
  operationState: 'pending' | 'failed' | null;
  draggable: boolean;
  onMoveUp?:()=>void;onMoveDown?:()=>void;
  onPress: () => void;
  onDragStart: (pageX: number, pageY: number) => void;
  onDragMove: (pageX: number, pageY: number) => void;
  onDragEnd: () => void;
  onDragCancel: () => void;
}) {
  const colors = useAppColors();
  const checklistItems = card.checklistItemCount || 0;
  const completedChecklistItems = Math.min(
    card.checklistCompletedItemCount || 0,
    checklistItems,
  );
  const checklistProgress = checklistItems
    ? completedChecklistItems / checklistItems
    : 0;
  return (
    <View
      style={[
        styles.card,
        {
          backgroundColor: palette.card,
          borderColor: operationState === 'failed' ? colors.danger : palette.border,
        },
      ]}
    >
      {(onMoveUp||onMoveDown)&&<View style={{flexDirection:'row',justifyContent:'flex-end'}}><Button label="↑" accessibilityLabel={`Поднять ${card.title}`} compact disabled={!onMoveUp} onPress={()=>onMoveUp?.()}/><Button label="↓" accessibilityLabel={`Опустить ${card.title}`} compact disabled={!onMoveDown} onPress={()=>onMoveDown?.()}/></View>}
      <View style={styles.cardHeader}>
        <Pressable
          onPress={onPress}
          style={({ pressed }) => [styles.cardOpenArea, { opacity: pressed ? 0.68 : 1 }]}
        >
          <Text style={[styles.cardTitle, { color: palette.text }]}>{card.title}</Text>
        </Pressable>
        {draggable ? (
          <DragHandle
            onStart={onDragStart}
            onMove={onDragMove}
            onEnd={onDragEnd}
            onCancel={onDragCancel}
          />
        ) : null}
      </View>
      <Pressable
        onPress={onPress}
        style={({ pressed }) => [styles.cardBody, { opacity: pressed ? 0.68 : 1 }]}
      >
        {appearance.showCardDescription && card.description ? (
          <Text
            style={[styles.cardDescription, { color: palette.muted }]}
            numberOfLines={appearance.cardPreviewMode === 'compact' ? 1 : 3}
          >
            {card.description}
          </Text>
        ) : null}
        {appearance.showChecklistProgress && checklistItems ? (
          <View style={styles.cardProgress}>
            <View style={[styles.cardProgressTrack, { backgroundColor: palette.border }]}>
              <View
                style={[
                  styles.cardProgressFill,
                  {
                    backgroundColor: checklistProgress === 1 ? colors.success : palette.accent,
                    width: `${Math.round(checklistProgress * 100)}%`,
                  },
                ]}
              />
            </View>
            <Text style={[styles.cardProgressText, { color: palette.muted }]}>
              {completedChecklistItems}/{checklistItems}
            </Text>
          </View>
        ) : null}
        <View style={styles.cardMeta}>
          {appearance.showCardDates && card.startAt ? (
            <Text style={[styles.metaText, { color: palette.muted }]}>
              с {formatCardDate(card.startAt)}
            </Text>
          ) : null}
          {appearance.showCardDates && card.dueAt ? (
            <Text style={[styles.metaText, { color: palette.muted }]}>
              до {formatCardDate(card.dueAt)}
            </Text>
          ) : null}
          {card.isArchived ? (
            <Text style={[styles.metaText, { color: colors.warning }]}>В архиве</Text>
          ) : null}
          {card.priority ? (
            <Text style={[
              styles.metaText,
              { color: card.priority === 'urgent' ? colors.danger : palette.muted },
            ]}>
              {priorityStars[card.priority] || card.priority}
            </Text>
          ) : null}
          {operationState ? (
            <Text style={[styles.metaText, { color: operationState === 'failed' ? colors.danger : colors.warning }]}>
              {operationState === 'failed' ? 'Нужна проверка' : 'На устройстве'}
            </Text>
          ) : null}
        </View>
      </Pressable>
    </View>
  );
}

export function BoardScreen({ navigation, route }: Props) {
  const {
    workspaceId,
    boardId,
    boardName,
    workspaceRole = 'member',
    accessEpoch = 1,
  } = route.params;
  const [prioritySort,setPrioritySort]=useState<Record<string,boolean>>({});
  const reorderBusy=useRef(false);
  const canEdit = workspaceRole === 'owner' || workspaceRole === 'member';
  const colors = useAppColors();
  const resolvedTheme = useResolvedTheme();
  const { width, height } = useWindowDimensions();
  const { isOnline } = useNetwork();
  const runtime = useLocalBoard(boardId, workspaceId, accessEpoch, canEdit);
  const exitController = useMemo(
    () => createBoardExitController(() => navigation.pop()),
    [navigation],
  );
  const leaveBoard = useCallback(() => exitController.leave(), [exitController]);
  const columnsScrollRef = useRef<ScrollView>(null);
  const scrollOffsetRef = useRef(0);
  const lastEdgeScrollAtRef = useRef(0);
  const dragRef = useRef<{
    cardId: string;
    sourceColumnId: string;
    targetColumnId: string;
    pageX: number;
    pageY: number;
  } | null>(null);
  const [createCardColumnId, setCreateCardColumnId] = useState<string | null>(null);
  const [newCardTitle, setNewCardTitle] = useState('');
  const [newCardDescription, setNewCardDescription] = useState('');
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [columnModal, setColumnModal] = useState(false);
  const [editingColumn, setEditingColumn] = useState<BoardColumn | null>(null);
  const [newColumnName, setNewColumnName] = useState('');
  const [newColumnDescription, setNewColumnDescription] = useState('');
  const [formBusy, setFormBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [showLocallyHidden, setShowLocallyHidden] = useState(false);
  const [appearanceModal, setAppearanceModal] = useState(false);
  const [appearanceBusy, setAppearanceBusy] = useState(false);
  const [appearanceError, setAppearanceError] = useState<string | null>(null);
  const [dragState, setDragState] = useState<typeof dragRef.current>(null);

  useFocusEffect(useCallback(() => {
    exitController.reset();
    const subscription = BackHandler.addEventListener('hardwareBackPress', leaveBoard);
    return () => subscription.remove();
  }, [exitController, leaveBoard]));

  const snapshot = runtime.snapshot;
  const appearance = snapshot?.appearance || defaultBoardAppearance(boardId);
  const boardPalette = useMemo(
    () => resolveBoardPalette(appearance, resolvedTheme),
    [appearance, resolvedTheme],
  );
  const boardModalColors = useMemo<AppColors>(() => ({
    ...colors,
    background: boardPalette.background,
    surface: boardPalette.card,
    surfaceMuted: boardPalette.column,
    border: boardPalette.border,
    text: boardPalette.text,
    muted: boardPalette.muted,
    accent: boardPalette.accent,
    accentSoft: /^#[0-9a-f]{6}$/i.test(boardPalette.accent)
      ? `${boardPalette.accent}26`
      : colors.accentSoft,
  }), [boardPalette, colors]);
  const columns = useMemo(
    () => [...(snapshot?.columns || [])].sort((left, right) => left.position - right.position),
    [snapshot?.columns],
  );
  const displayedCards = useMemo(
    () => (snapshot?.cards || []).filter((card) => showArchived || !card.isArchived),
    [showArchived, snapshot?.cards],
  );
  const selectedCard = (snapshot?.cards || [])
    .find((card) => card.id === selectedCardId) || null;
  const columnWidth = appearance.columnDensity === 'compact'
    ? Math.min(Math.max(width - 68, 258), 310)
    : Math.min(Math.max(width - 48, 282), 370);
  const columnStride = columnWidth + spacing.sm;

  useEffect(() => {
    const focusCardId = route.params.focusCardId;
    if (!focusCardId || !snapshot?.cards.some((card) => card.id === focusCardId)) return;
    setSelectedCardId(focusCardId);
    navigation.setParams({ focusCardId: undefined });
  }, [navigation, route.params.focusCardId, snapshot?.cards]);

  async function saveAppearance(input: Parameters<typeof runtime.updateAppearance>[0]) {
    if (!canEdit || appearanceBusy) return;
    setAppearanceBusy(true);
    setAppearanceError(null);
    try {
      await runtime.updateAppearance(input);
      setAppearanceModal(false);
    } catch (error) {
      setAppearanceError(error instanceof Error
        ? error.message
        : 'Не удалось сохранить оформление доски.');
    } finally {
      setAppearanceBusy(false);
    }
  }

  async function submitCard() {
    if (!canEdit || !createCardColumnId || !newCardTitle.trim() || formBusy) return;
    setFormBusy(true);
    setFormError(null);
    try {
      await runtime.createCard({
        title: newCardTitle.trim(),
        description: newCardDescription || undefined,
        columnId: createCardColumnId,
      });
      setCreateCardColumnId(null);
      setNewCardTitle('');
      setNewCardDescription('');
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Не удалось создать карточку.');
    } finally {
      setFormBusy(false);
    }
  }

  async function submitColumn() {
    if (!canEdit || !newColumnName.trim() || formBusy) return;
    setFormBusy(true);
    setFormError(null);
    try {
      if (editingColumn) {
        await updateColumn(boardId, editingColumn.id, {
          name: newColumnName.trim(),
          description: newColumnDescription.trim() || null,
        });
      } else {
        await createColumn(boardId, {
          name: newColumnName.trim(),
          description: newColumnDescription.trim() || undefined,
          position: columns.reduce(
            (highest, column) => Math.max(highest, column.position),
            0,
          ) + 1000,
        });
      }
      setColumnModal(false);
      setEditingColumn(null);
      setNewColumnName('');
      setNewColumnDescription('');
      await runtime.refresh();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'Не удалось сохранить колонку.');
    } finally {
      setFormBusy(false);
    }
  }

  function openCreateColumn() {
    if (!canEdit) return;
    setFormError(null);
    setEditingColumn(null);
    setNewColumnName('');
    setNewColumnDescription('');
    setColumnModal(true);
  }

  function openColumnActions(column: BoardColumn) {
    if (!canEdit) return;
    Alert.alert(column.name, 'Выберите действие с колонкой.', [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Изменить',
        onPress: () => {
          setFormError(null);
          setEditingColumn(column);
          setNewColumnName(column.name);
          setNewColumnDescription(column.description || '');
          setColumnModal(true);
        },
      },
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          Alert.alert(
            'Удалить колонку?',
            'Колонку с карточками сервер удалить не позволит.',
            [
              { text: 'Отмена', style: 'cancel' },
              {
                text: 'Удалить',
                style: 'destructive',
                onPress: () => {
                  setFormError(null);
                  void deleteColumn(boardId, column.id)
                    .then(runtime.refresh)
                    .catch((error) => {
                      setFormError(error instanceof Error
                        ? error.message
                        : 'Не удалось удалить колонку.');
                    });
                },
              },
            ],
          );
        },
      },
    ]);
  }

  async function moveAdjacent(card:Card,direction:-1|1){
    if(!canEdit||prioritySort[card.columnId]||reorderBusy.current)return;
    try{reorderBusy.current=true;const position=getAdjacentPosition(runtime.snapshot?.cards||[],card.id,direction);if(position!==null)await runtime.moveCard(card.id,card.columnId,position);}
    catch(error){setFormError(error instanceof Error?error.message:'Не удалось изменить порядок.');}finally{reorderBusy.current=false;}
  }
  function updateDragState(next: typeof dragRef.current) {
    dragRef.current = next;
    setDragState(next);
  }

  function moveDrag(pageX: number, pageY: number) {
    if (!canEdit) return;
    const current = dragRef.current;
    if (!current || !columns.length) return;
    const targetIndex = getDropColumnIndex({
      scrollOffset: scrollOffsetRef.current,
      pointerX: pageX,
      contentInset: spacing.md,
      columnWidth,
      gap: spacing.sm,
      columnCount: columns.length,
    });
    const targetColumn = columns[targetIndex];
    if (targetColumn) {
      updateDragState({
        ...current,
        targetColumnId: targetColumn.id,
        pageX,
        pageY,
      });
    }

    const nextOffset = getEdgeScrollOffset({
      scrollOffset: scrollOffsetRef.current,
      pointerX: pageX,
      viewportWidth: width,
      columnWidth,
      gap: spacing.sm,
      columnCount: columns.length,
    });
    if (
      nextOffset !== null
      && Date.now() - lastEdgeScrollAtRef.current >= 340
    ) {
      lastEdgeScrollAtRef.current = Date.now();
      scrollOffsetRef.current = nextOffset;
      columnsScrollRef.current?.scrollTo({ x: nextOffset, animated: true });
      const nextColumn = columns[Math.round(nextOffset / columnStride)];
      if (nextColumn) {
        updateDragState({
          ...current,
          targetColumnId: nextColumn.id,
          pageX,
          pageY,
        });
      }
    }
  }

  function startDrag(card: Card, pageX: number, pageY: number) {
    if (!canEdit || prioritySort[card.columnId]) return;
    updateDragState({
      cardId: card.id,
      sourceColumnId: card.columnId,
      targetColumnId: card.columnId,
      pageX,
      pageY,
    });
  }

  async function finishDrag() {
    const current = dragRef.current;
    updateDragState(null);
    if (!canEdit || !current || prioritySort[current.targetColumnId] || current.targetColumnId === current.sourceColumnId) return;
    const latestCards = runtime.snapshot?.cards || [];
    const position = getAppendPosition(
      latestCards,
      current.targetColumnId,
      current.cardId,
    );
    try {
      await runtime.moveCard(current.cardId, current.targetColumnId, position);
    } catch (error) {
      setFormError(error instanceof Error
        ? error.message
        : 'Не удалось переместить карточку.');
    }
  }

  let syncText = 'Синхронизировано';
  let syncTone: 'neutral' | 'danger' | 'warning' | 'success' = 'success';
  if (runtime.failedCount) {
    syncText = `Требуют проверки: ${formatCountRu(runtime.failedCount, 'изменение', 'изменения', 'изменений')}`;
    syncTone = 'danger';
  } else if (runtime.flushing) {
    syncText = 'Отправляем сохранённые изменения';
    syncTone = 'neutral';
  } else if (runtime.pendingCount) {
    syncText = `Сохранено на устройстве: ${formatCountRu(runtime.pendingCount, 'изменение', 'изменения', 'изменений')}`;
    syncTone = 'warning';
  } else if (runtime.relayPendingCount) {
    syncText = `Реле приняло ${formatCountRu(runtime.relayPendingCount, 'изменение', 'изменения', 'изменений')} · восстанавливаем очередь публикации`;
    syncTone = 'warning';
  } else if (!isOnline) {
    syncText = runtime.syncMode === 'roaming'
      ? 'Нет интернета · доска работает локально'
      : 'Нет связи · изменения сохраняются на устройстве';
    syncTone = 'warning';
  } else if (runtime.syncMode === 'roaming') {
    syncText = `Независимая синхронизация · ${formatCountRu(runtime.relayCount, 'реле', 'реле', 'реле')}`;
    syncTone = 'success';
  }

  if (!runtime.hydrated && !snapshot) {
    return (
      <Screen>
        <ScreenHeader title={boardName} onBack={leaveBoard} />
        <StateView title="Открываем доску" busy />
      </Screen>
    );
  }

  if (!snapshot) {
    return (
      <Screen>
        <ScreenHeader title={boardName} onBack={leaveBoard} />
        <StateView
          title="Доска не сохранена на устройстве"
          description={isOnline
            ? runtime.lastError || 'Не удалось получить локальную или relay-копию доски.'
            : 'Подключитесь к интернету или откройте доску после первичной привязки.'}
          action={isOnline ? <Button label="Повторить" onPress={() => void runtime.refresh()} /> : undefined}
        />
      </Screen>
    );
  }

  return (
    <Screen
      contentStyle={styles.screen}
      backgroundColor={boardPalette.background}
      backgroundImage={boardPalette.imageUri}
    >
      <View style={[
        styles.boardChrome,
        { backgroundColor: boardPalette.column, borderColor: boardPalette.border },
      ]}>
        <ScreenHeader
          title={snapshot.board.name}
          subtitle={`${formatCountRu(columns.length, 'колонка', 'колонки', 'колонок')} · ${formatCountRu(displayedCards.length, 'карточка', 'карточки', 'карточек')}`}
          onBack={leaveBoard}
          palette={boardPalette}
          action={(
            <Button
              label="История"
              compact
              variant="ghost"
              foregroundColor={boardPalette.muted}
              onPress={() => navigation.navigate('Activity', {
                boardId,
                boardName: snapshot.board.name,
              })}
            />
          )}
        />

        <View style={styles.statusRow}>
          <View style={styles.statusNotice}>
            <InlineNotice text={syncText} tone={syncTone} />
          </View>
          {runtime.failedCount && canEdit ? (
            <Button label="Повторить" compact onPress={() => void runtime.retryFailed()} />
          ) : (
            <Button
              label="Обновить"
              compact
              loading={runtime.refreshing}
              disabled={!isOnline}
              onPress={() => void runtime.refresh()}
            />
          )}
        </View>

        <View style={styles.boardTools}>
          <Text style={[styles.dragHint, { color: boardPalette.muted }]}> 
            {canEdit
              ? 'Тяните карточку за ≡ к краю экрана, чтобы перейти в соседнюю колонку.'
              : 'Только чтение: роль гостя не изменяет общую доску.'}
          </Text>
          {canEdit ? <Button
            label="Оформление"
            compact
            variant="ghost"
            foregroundColor={boardPalette.muted}
            onPress={() => {
              setAppearanceError(null);
              setAppearanceModal(true);
            }}
          /> : null}
          <Button
            label={showArchived ? 'Скрыть архив' : 'Показать архив'}
            compact
            variant="ghost"
            foregroundColor={boardPalette.muted}
            onPress={() => setShowArchived((current) => !current)}
          />
          <Button
            label={`Скрытые здесь${runtime.locallyHiddenCards.length
              ? ` (${runtime.locallyHiddenCards.length})`
              : ''}`}
            compact
            variant="ghost"
            foregroundColor={boardPalette.muted}
            onPress={() => setShowLocallyHidden(true)}
          />
        </View>
      </View>

      {runtime.lastError && !runtime.failedCount ? (
        <InlineNotice text={runtime.lastError} tone={isOnline ? 'danger' : 'warning'} />
      ) : null}

      {!columns.length ? (
        <StateView
          title="На доске нет колонок"
          description={canEdit
            ? (isOnline ? 'Добавьте первую колонку.' : 'Создать колонку можно после подключения.')
            : 'Гостевой доступ: доска открыта только для чтения.'}
          action={isOnline && canEdit
            ? <Button label="Добавить колонку" variant="primary" onPress={openCreateColumn} />
            : undefined}
        />
      ) : (
        <ScrollView
          ref={columnsScrollRef}
          horizontal
          scrollEnabled={!dragState}
          showsHorizontalScrollIndicator={false}
          snapToInterval={columnWidth + spacing.sm}
          decelerationRate="fast"
          scrollEventThrottle={16}
          onScroll={(event) => {
            scrollOffsetRef.current = event.nativeEvent.contentOffset.x;
          }}
          contentContainerStyle={styles.columns}
          style={styles.columnsViewport}
        >
          {columns.map((column) => {
            const cards=orderCards(displayedCards.filter(card=>card.columnId===column.id),Boolean(prioritySort[column.id]));
            const isDropTarget = dragState?.targetColumnId === column.id;
            return (
              <View
                key={column.id}
                style={[
                  styles.column,
                  {
                    width: columnWidth,
                    backgroundColor: boardPalette.column,
                    borderColor: isDropTarget ? boardPalette.accent : boardPalette.border,
                    borderWidth: isDropTarget ? 2 : 1,
                  },
                ]}
              >
                <View style={styles.columnHeader}>
                  <Text style={[styles.columnTitle, { color: boardPalette.text }]} numberOfLines={1}>
                    {column.name}
                  </Text>
                  <Text style={[styles.columnCount, { color: boardPalette.muted }]}>{cards.length}</Text>
                  {canEdit ? <Pressable
                    onPress={() => openColumnActions(column)}
                    accessibilityRole="button"
                    accessibilityLabel={`Действия с колонкой ${column.name}`}
                    style={({ pressed }) => [
                      styles.columnMenu,
                      {
                        backgroundColor: boardPalette.card,
                        opacity: pressed ? 0.65 : 1,
                      },
                    ]}
                  >
                    <Text style={[styles.columnMenuText, { color: boardPalette.muted }]}>•••</Text>
                  </Pressable> : null}
                </View>
                <Button compact label={prioritySort[column.id]?'★ Сначала важные · вернуть ручной':'☆ По приоритету'} onPress={()=>{updateDragState(null);setPrioritySort(current=>({...current,[column.id]:!current[column.id]}));}}/>
                {canEdit ? <Button
                  label="Добавить карточку"
                  compact
                  variant="ghost"
                  onPress={() => {
                    setFormError(null);
                    setCreateCardColumnId(column.id);
                  }}
                /> : null}
                <ScrollView
                  style={styles.cardList}
                  contentContainerStyle={styles.cardListContent}
                  nestedScrollEnabled
                  showsVerticalScrollIndicator={false}
                >
                  {cards.map((card,index) => (
                    <CardPreview
                      key={card.id}
                      card={card}
                      appearance={appearance}
                      palette={boardPalette}
                      operationState={runtime.cardOperationState(card.id)}
                      draggable={canEdit&&!prioritySort[column.id]} onMoveUp={canEdit&&!prioritySort[column.id]&&index>0?()=>{void moveAdjacent(card,-1);}:undefined} onMoveDown={canEdit&&!prioritySort[column.id]&&index<cards.length-1?()=>{void moveAdjacent(card,1);}:undefined}
                      onPress={() => setSelectedCardId(card.id)}
                      onDragStart={(pageX, pageY) => startDrag(card, pageX, pageY)}
                      onDragMove={moveDrag}
                      onDragEnd={() => void finishDrag()}
                      onDragCancel={() => updateDragState(null)}
                    />
                  ))}
                  {!cards.length ? (
                    <Text style={[styles.emptyColumn, { color: boardPalette.muted }]}>
                      Карточек пока нет
                    </Text>
                  ) : null}
                </ScrollView>
              </View>
            );
          })}

          {canEdit ? <View
            style={[
              styles.addColumn,
              {
                width: columnWidth,
                borderColor: boardPalette.border,
                backgroundColor: boardPalette.column,
              },
            ]}
          >
            <Text style={[styles.addColumnTitle, { color: boardPalette.text }]}>Следующая колонка</Text>
            <Text style={[styles.addColumnText, { color: boardPalette.muted }]}>
              В этой версии колонки создаются через локальный узел; карточки уже
              синхронизируются независимо через зашифрованный журнал.
            </Text>
            <Button
              label="Добавить колонку"
              variant="primary"
              disabled={!isOnline}
              onPress={openCreateColumn}
            />
          </View> : null}
        </ScrollView>
      )}

      <FormModal
        visible={showLocallyHidden}
        title="Скрытые только здесь"
        onClose={() => setShowLocallyHidden(false)}
      >
        <InlineNotice
          text="Эти карточки остаются на других устройствах. Локальное скрытие не создаёт Nostr-событие."
          tone="neutral"
        />
        {runtime.locallyHiddenCards.map((card) => (
          <View key={card.id} style={styles.hiddenCardRow}>
            <Text style={[styles.hiddenCardTitle, { color: colors.text }]} numberOfLines={2}>
              {card.title}
            </Text>
            <Button
              label="Вернуть"
              compact
              variant="ghost"
              onPress={() => void runtime.restoreCardLocally(card.id)}
            />
          </View>
        ))}
        {!runtime.locallyHiddenCards.length ? (
          <Text style={[styles.emptyColumn, { color: colors.muted }]}>Скрытых карточек нет</Text>
        ) : null}
      </FormModal>

      <FormModal
        visible={Boolean(createCardColumnId)}
        title="Новая карточка"
        onClose={() => {
          if (!formBusy) setCreateCardColumnId(null);
        }}
      >
        <Field
          label="Название"
          value={newCardTitle}
          onChangeText={setNewCardTitle}
          autoFocus
          placeholder="Что нужно сделать"
        />
        <Field
          label="Описание"
          value={newCardDescription}
          onChangeText={setNewCardDescription}
          multiline
          placeholder="Необязательно"
        />
        {formError ? <InlineNotice text={formError} tone="danger" /> : null}
        <Button
          label={isOnline ? 'Создать' : 'Сохранить на устройстве'}
          variant="primary"
          loading={formBusy}
          disabled={!newCardTitle.trim()}
          onPress={() => void submitCard()}
        />
      </FormModal>

      <FormModal
        visible={columnModal}
        title={editingColumn ? 'Изменить колонку' : 'Новая колонка'}
        onClose={() => {
          if (!formBusy) {
            setColumnModal(false);
            setEditingColumn(null);
          }
        }}
      >
        <Field
          label="Название"
          value={newColumnName}
          onChangeText={setNewColumnName}
          autoFocus
          placeholder="В работе"
        />
        <Field
          label="Описание"
          value={newColumnDescription}
          onChangeText={setNewColumnDescription}
          multiline
          placeholder="Необязательно"
        />
        {formError ? <InlineNotice text={formError} tone="danger" /> : null}
        <Button
          label={editingColumn ? 'Сохранить' : 'Создать'}
          variant="primary"
          loading={formBusy}
          disabled={!newColumnName.trim() || !isOnline}
          onPress={() => void submitColumn()}
        />
      </FormModal>

      <BoardAppearanceModal
        visible={appearanceModal}
        appearance={appearance}
        online={isOnline}
        saving={appearanceBusy}
        error={appearanceError}
        onClose={() => {
          if (!appearanceBusy) setAppearanceModal(false);
        }}
        onSave={saveAppearance}
      />

      <ColorOverrideProvider colors={boardModalColors}>
        <CardDetailsModal
          card={selectedCard}
          columns={columns}
          runtime={runtime}
          readOnly={!canEdit}
          onClose={() => setSelectedCardId(null)}
        />
      </ColorOverrideProvider>

      {dragState ? (
        <View
          pointerEvents="none"
          style={[
            styles.dragOverlay,
            {
              left: Math.min(Math.max(dragState.pageX - 88, spacing.sm), width - 184),
              top: Math.min(Math.max(dragState.pageY - 118, 88), height - 120),
              backgroundColor: colors.accent,
            },
          ]}
        >
          <Text style={[styles.dragOverlayText, { color: colors.background }]}>
            {columns.find((column) => column.id === dragState.targetColumnId)?.name
              || 'Перемещение'}
          </Text>
        </View>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: {
    paddingBottom: spacing.sm,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  boardChrome: {
    gap: spacing.sm,
    padding: spacing.sm,
    borderWidth: 1,
    borderRadius: radius.md,
  },
  statusNotice: {
    flex: 1,
  },
  boardTools: {
    minHeight: 36,
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: spacing.sm,
  },
  dragHint: {
    flex: 1,
    minWidth: '100%',
    fontSize: 11,
    lineHeight: 15,
  },
  hiddenCardRow: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  hiddenCardTitle: {
    flex: 1,
    fontSize: 14,
    fontWeight: '700',
  },
  columnsViewport: {
    flex: 1,
    marginHorizontal: -spacing.md,
  },
  columns: {
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
    gap: spacing.sm,
  },
  column: {
    flex: 1,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.sm,
  },
  columnHeader: {
    minHeight: 40,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  columnTitle: {
    flex: 1,
    fontSize: 16,
    fontWeight: '800',
  },
  columnCount: {
    fontSize: 13,
    fontWeight: '700',
  },
  columnMenu: {
    minWidth: 34,
    minHeight: 30,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.sm,
  },
  columnMenuText: {
    fontSize: 13,
    fontWeight: '800',
    letterSpacing: -1,
  },
  cardList: {
    flex: 1,
  },
  cardListContent: {
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  card: {
    borderWidth: 1,
    borderRadius: radius.sm,
    padding: spacing.sm,
    gap: spacing.xs,
  },
  cardHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.xs,
  },
  cardOpenArea: {
    flex: 1,
    minHeight: 32,
    justifyContent: 'center',
  },
  cardBody: {
    gap: spacing.xs,
  },
  dragHandle: {
    width: 34,
    height: 34,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.sm,
  },
  dragHandleText: {
    fontSize: 24,
    lineHeight: 25,
    fontWeight: '800',
  },
  cardTitle: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: '700',
  },
  cardDescription: {
    fontSize: 13,
    lineHeight: 18,
  },
  cardMeta: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  cardProgress: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  cardProgressTrack: {
    flex: 1,
    height: 5,
    overflow: 'hidden',
    borderRadius: 999,
  },
  cardProgressFill: {
    height: '100%',
    borderRadius: 999,
  },
  cardProgressText: {
    minWidth: 30,
    textAlign: 'right',
    fontSize: 11,
    fontWeight: '700',
  },
  metaText: {
    fontSize: 11,
    fontWeight: '700',
  },
  emptyColumn: {
    paddingVertical: spacing.lg,
    textAlign: 'center',
    fontSize: 13,
  },
  addColumn: {
    flex: 1,
    justifyContent: 'center',
    gap: spacing.sm,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderRadius: radius.md,
    padding: spacing.lg,
  },
  addColumnTitle: {
    fontSize: 18,
    fontWeight: '800',
  },
  addColumnText: {
    fontSize: 13,
    lineHeight: 19,
  },
  dragOverlay: {
    position: 'absolute',
    zIndex: 50,
    width: 176,
    minHeight: 42,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
    elevation: 10,
  },
  dragOverlayText: {
    textAlign: 'center',
    fontSize: 13,
    fontWeight: '800',
  },
});
