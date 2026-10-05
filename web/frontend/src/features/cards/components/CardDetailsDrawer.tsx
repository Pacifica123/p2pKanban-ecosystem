import {MarkdownEditor} from '@/shared/markdown/MarkdownEditor';
import {PriorityStars} from '@/shared/ui/PriorityStars';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useAppearance } from '@/app/providers/AppearanceProvider';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import { useCardActivityQuery } from '@/features/activity/hooks/useActivity';
import { ActivityFeed } from '@/features/activity/components/ActivityFeed';
import {
  useArchiveCardMutation,
  useCardQuery,
  useDeleteCardMutation,
  useHideCardLocallyMutation,
  useMoveCardMutation,
  useUnarchiveCardMutation,
  useUpdateCardMutation,
} from '@/features/cards/hooks/useCards';
import {
  useCardChecklistsQuery,
  useCreateChecklistItemMutation,
  useCreateChecklistMutation,
  useDeleteChecklistItemMutation,
  useDeleteChecklistMutation,
  useUpdateChecklistItemMutation,
  useUpdateChecklistMutation,
} from '@/features/checklists/hooks/useChecklists';
import {
  useCardCommentsQuery,
  useCreateCommentMutation,
  useDeleteCommentMutation,
  useUpdateCommentMutation,
} from '@/features/comments/hooks/useComments';
import { useColumnsQuery } from '@/features/columns/hooks/useColumns';
import { useOptionalLocalFirstBoard } from '@/features/localFirst/context/LocalFirstBoardContext';
import { isLocalCardId, resolveLocalFirstCardId } from '@/features/localFirst/lib/localBoardStore';
import {
  useBoardLabelsQuery,
  useCreateBoardLabelMutation,
  useDeleteBoardLabelMutation,
  useReplaceCardLabelsMutation,
  useUpdateBoardLabelMutation,
} from '@/features/labels/hooks/useLabels';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { SelectField, TextAreaField, TextField } from '@/shared/ui/Field';
import { Icon } from '@/shared/ui/Icon';
import { LoadingState } from '@/shared/ui/LoadingState';
import { formatDateTime } from '@/shared/lib/date';
import { getBoardThemeStyle, type ResolvedThemeMode } from '@/shared/appearance/theme';
import type { BoardAppearanceSettings, BoardLabel, CardPriority, Checklist, ChecklistItem, Comment } from '@/shared/types/api';
import {
  checklistSubmitHint,
  shouldSubmitChecklistItem,
} from '@/features/checklists/lib/checklistComposer';
import {
  REMINDERS_CHANGED_EVENT,
  getLocalCardReminder,
  moveLocalCardReminder,
  removeLocalCardReminder,
  requestBrowserNotificationPermission,
  saveLocalCardReminder,
  toLocalDateTimeInput,
  updateLocalCardReminderTitle,
} from '@/features/reminders/lib/localReminders';

export function CardDetailsDrawer({
  boardAppearance,
  resolvedTheme,
  readOnly = false,
}: {
  boardAppearance?: BoardAppearanceSettings;
  resolvedTheme: ResolvedThemeMode;
  readOnly?: boolean;
}) {
  const navigate = useNavigate();
  const { boardId, workspaceId } = useParams();
  const [searchParams] = useSearchParams();
  const { effectiveUserAppearance } = useAppearance();
  const { user } = useAuthSession();
  const cardId = searchParams.get('card');
  const localFirst = useOptionalLocalFirstBoard();
  const effectiveCardId = cardId ? resolveLocalFirstCardId(cardId) : null;
  const cardQueryId = effectiveCardId && !isLocalCardId(effectiveCardId) ? effectiveCardId : undefined;

  const cardQuery = useCardQuery(cardQueryId || undefined);
  const columnsQuery = useColumnsQuery(boardId);
  const labelsQuery = useBoardLabelsQuery(boardId);
  const checklistsQuery = useCardChecklistsQuery(cardQueryId || undefined);
  const commentsQuery = useCardCommentsQuery(cardQueryId || undefined);
  const activityQuery = useCardActivityQuery(cardQueryId || undefined);
  const updateCardMutation = useUpdateCardMutation(boardId, cardQueryId || undefined);
  const moveCardMutation = useMoveCardMutation(boardId, cardQueryId || undefined);
  const archiveCardMutation = useArchiveCardMutation(boardId, cardQueryId || undefined);
  const unarchiveCardMutation = useUnarchiveCardMutation(boardId, cardQueryId || undefined);
  const deleteCardMutation = useDeleteCardMutation(boardId, cardQueryId || undefined);
  const hideCardLocallyMutation = useHideCardLocallyMutation(boardId, cardQueryId || undefined);
  const createLabelMutation = useCreateBoardLabelMutation(boardId);
  const updateLabelMutation = useUpdateBoardLabelMutation(boardId);
  const deleteLabelMutation = useDeleteBoardLabelMutation(boardId);
  const replaceCardLabelsMutation = useReplaceCardLabelsMutation(boardId, cardQueryId || undefined);
  const createChecklistMutation = useCreateChecklistMutation(boardId, cardQueryId || undefined);
  const updateChecklistMutation = useUpdateChecklistMutation(boardId, cardQueryId || undefined);
  const deleteChecklistMutation = useDeleteChecklistMutation(boardId, cardQueryId || undefined);
  const createChecklistItemMutation = useCreateChecklistItemMutation(boardId, cardQueryId || undefined);
  const updateChecklistItemMutation = useUpdateChecklistItemMutation(boardId, cardQueryId || undefined);
  const deleteChecklistItemMutation = useDeleteChecklistItemMutation(boardId, cardQueryId || undefined);
  const createCommentMutation = useCreateCommentMutation(boardId, cardQueryId || undefined);
  const updateCommentMutation = useUpdateCommentMutation(boardId, cardQueryId || undefined);
  const deleteCommentMutation = useDeleteCommentMutation(boardId, cardQueryId || undefined);

  const localCard = useMemo(() => {
    if (!effectiveCardId || !localFirst || localFirst.boardId !== boardId) return undefined;
    return localFirst.cards.find((item) => item.id === effectiveCardId);
  }, [boardId, effectiveCardId, localFirst]);
  const card = localCard || cardQuery.data;
  const cardSyncStatus = card ? localFirst?.getEntityStatus('card', card.id)?.status ?? 'synced' : 'synced';
  const isLocalPendingCard = Boolean(card && isLocalCardId(card.id));

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<CardPriority>(null);
  const [columnId, setColumnId] = useState('');
  const [newLabelName, setNewLabelName] = useState('');
  const [newLabelColor, setNewLabelColor] = useState('#60a5fa');
  const [newChecklistTitle, setNewChecklistTitle] = useState('');
  const [newItemByChecklist, setNewItemByChecklist] = useState<Record<string, string>>({});
  const [newCommentBody, setNewCommentBody] = useState('');
  const [reminderLocalDateTime, setReminderLocalDateTime] = useState('');
  const [reminderError, setReminderError] = useState<string | null>(null);
  const [reminderNotice, setReminderNotice] = useState<string | null>(null);
  const checklistItemSubmitMode = effectiveUserAppearance?.checklistItemSubmitMode ?? 'ctrl_enter';
  const cardDetailsMode = effectiveUserAppearance?.cardDetailsMode ?? 'drawer';

  useEffect(() => {
    if (!card) return;
    setTitle(card.title);
    setDescription(card.description || '');
    setPriority(card.priority || null);
    setColumnId(card.columnId);
    setReminderLocalDateTime(user ? getLocalCardReminder(card.id, user.id)?.localDateTime || '' : '');
    setReminderError(null);
    setReminderNotice(null);
  }, [card, user]);

  useEffect(() => {
    if (!card) return;
    const refreshReminder = () => {
      setReminderLocalDateTime(user ? getLocalCardReminder(card.id, user.id)?.localDateTime || '' : '');
    };
    window.addEventListener(REMINDERS_CHANGED_EVENT, refreshReminder);
    return () => window.removeEventListener(REMINDERS_CHANGED_EVENT, refreshReminder);
  }, [card?.id, user]);

  const columnOptions = useMemo(() => {
    if (localFirst && localFirst.boardId === boardId && localFirst.columns.length) {
      return localFirst.columns;
    }
    return columnsQuery.data?.items ?? [];
  }, [boardId, columnsQuery.data?.items, localFirst]);
  const selectedLabelIds = useMemo(() => card?.labelIds ?? [], [card?.labelIds]);

  useEffect(() => {
    if (!cardId || !effectiveCardId || cardId === effectiveCardId) return;
    if (user) moveLocalCardReminder(cardId, effectiveCardId, user.id);
    const next = new URLSearchParams(searchParams);
    next.set('card', effectiveCardId);
    navigate({ search: next.toString() }, { replace: true });
  }, [cardId, effectiveCardId, navigate, searchParams, user]);

  function closeDrawer() {
    navigate(workspaceId && boardId ? `/workspaces/${workspaceId}/boards/${boardId}` : '/', { replace: true });
  }

  useEffect(() => {
    if (!cardId) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeDrawer();
    };
    document.body.classList.add('has-card-dialog');
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.classList.remove('has-card-dialog');
      window.removeEventListener('keydown', closeOnEscape);
    };
  }, [boardId, cardId, workspaceId]);

  async function handleSave() {
    if (!card) return;

    const nextCardInput = {
      title: title.trim(),
      description: description || null,
      priority: priority || null,
    };

    if (localFirst && localFirst.boardId === boardId) {
      localFirst.enqueueUpdateCard(card.id, nextCardInput);
      if (columnId && columnId !== card.columnId) {
        localFirst.enqueueMoveCard(card.id, { targetColumnId: columnId });
      }
      if (user) updateLocalCardReminderTitle(card.id, nextCardInput.title, user.id);
      return;
    }

    await updateCardMutation.mutateAsync(nextCardInput);

    if (columnId && columnId !== card.columnId) {
      await moveCardMutation.mutateAsync({ targetColumnId: columnId });
    }
    if (user) updateLocalCardReminderTitle(card.id, nextCardInput.title, user.id);
  }

  async function handleSaveReminder() {
    if (!card || !boardId || !workspaceId || !user) return;
    setReminderError(null);
    setReminderNotice(null);
    try {
      const permission = await requestBrowserNotificationPermission();
      saveLocalCardReminder({
        userId: user.id,
        cardId: card.id,
        boardId,
        workspaceId,
        cardTitle: title.trim() || card.title,
        localDateTime: reminderLocalDateTime,
      });
      setReminderNotice(permission === 'granted'
        ? 'Напоминание запланировано в локальном времени этого компьютера.'
        : 'Напоминание запланировано внутри приложения; системные уведомления браузера недоступны.');
    } catch (error) {
      setReminderError(error instanceof Error ? error.message : 'Не удалось запланировать напоминание.');
    }
  }

  function handleRemoveReminder() {
    if (!card) return;
    if (user) removeLocalCardReminder(card.id, user.id);
    setReminderLocalDateTime('');
    setReminderError(null);
    setReminderNotice('Напоминание отключено.');
  }

  function setReminderOffset(milliseconds: number, tomorrowAtNine = false) {
    const next = new Date();
    if (tomorrowAtNine) {
      next.setDate(next.getDate() + 1);
      next.setHours(9, 0, 0, 0);
    } else {
      next.setTime(next.getTime() + milliseconds);
    }
    setReminderLocalDateTime(toLocalDateTimeInput(next));
    setReminderError(null);
    setReminderNotice(null);
  }

  async function handleArchiveToggle() {
    if (!card) return;
    if (card.isArchived) {
      await unarchiveCardMutation.mutateAsync();
      return;
    }
    await archiveCardMutation.mutateAsync();
  }

  async function handleDeleteEverywhere() {
    if (!card) return;
    if (!window.confirm(
      `Удалить карточку «${card.title}» на всех устройствах? Старые локальные копии не смогут восстановить её автоматически.`,
    )) return;
    await deleteCardMutation.mutateAsync();
    if (user) removeLocalCardReminder(card.id, user.id);
    closeDrawer();
  }

  async function handleHideLocally() {
    if (!card) return;
    if (!window.confirm(
      `Скрыть карточку «${card.title}» только на этом web-узле? На других устройствах она останется.`,
    )) return;
    await hideCardLocallyMutation.mutateAsync();
    if (user) removeLocalCardReminder(card.id, user.id);
    closeDrawer();
  }

  async function handleCreateLabel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = newLabelName.trim();
    const color = newLabelColor.trim();
    if (!name || !color) return;
    await createLabelMutation.mutateAsync({ name, color });
    setNewLabelName('');
  }

  async function handleToggleLabel(labelId: string) {
    const nextLabelIds = selectedLabelIds.includes(labelId)
      ? selectedLabelIds.filter((current) => current !== labelId)
      : [...selectedLabelIds, labelId];
    await replaceCardLabelsMutation.mutateAsync(nextLabelIds);
  }

  async function handleRenameLabel(label: BoardLabel) {
    const nextName = window.prompt('Новое название метки', label.name)?.trim();
    if (!nextName || nextName === label.name) return;
    await updateLabelMutation.mutateAsync({ labelId: label.id, input: { name: nextName } });
  }

  async function handleDeleteLabel(label: BoardLabel) {
    if (!window.confirm(`Удалить метку «${label.name}» и снять её со всех карточек?`)) return;
    await deleteLabelMutation.mutateAsync(label.id);
  }

  async function handleCreateChecklist(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const titleValue = newChecklistTitle.trim();
    if (!titleValue) return;
    await createChecklistMutation.mutateAsync({ title: titleValue });
    setNewChecklistTitle('');
  }

  async function handleRenameChecklist(checklist: Checklist) {
    const nextTitle = window.prompt('Новое название чек-листа', checklist.title)?.trim();
    if (!nextTitle || nextTitle === checklist.title) return;
    await updateChecklistMutation.mutateAsync({ checklistId: checklist.id, input: { title: nextTitle } });
  }

  async function handleDeleteChecklist(checklist: Checklist) {
    if (!window.confirm(`Удалить чек-лист «${checklist.title}»?`)) return;
    await deleteChecklistMutation.mutateAsync(checklist.id);
  }

  async function handleCreateChecklistItem(checklistId: string) {
    const titleValue = (newItemByChecklist[checklistId] || '').trim();
    if (!titleValue) return;
    await createChecklistItemMutation.mutateAsync({ checklistId, title: titleValue });
    setNewItemByChecklist((current) => ({ ...current, [checklistId]: '' }));
  }

  function handleChecklistItemKeyDown(
    checklistId: string,
    event: React.KeyboardEvent<HTMLInputElement>,
  ) {
    if (!shouldSubmitChecklistItem(checklistItemSubmitMode, {
      key: event.key,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
      altKey: event.altKey,
      shiftKey: event.shiftKey,
      isComposing: event.nativeEvent.isComposing,
    })) return;
    event.preventDefault();
    if (createChecklistItemMutation.isPending) return;
    void handleCreateChecklistItem(checklistId);
  }

  async function handleToggleChecklistItem(item: ChecklistItem) {
    await updateChecklistItemMutation.mutateAsync({ itemId: item.id, input: { isDone: !item.isDone } });
  }

  async function handleRenameChecklistItem(item: ChecklistItem) {
    const nextTitle = window.prompt('Новое название пункта', item.title)?.trim();
    if (!nextTitle || nextTitle === item.title) return;
    await updateChecklistItemMutation.mutateAsync({ itemId: item.id, input: { title: nextTitle } });
  }

  async function handleDeleteChecklistItem(item: ChecklistItem) {
    if (!window.confirm(`Удалить пункт «${item.title}»?`)) return;
    await deleteChecklistItemMutation.mutateAsync(item.id);
  }

  async function handleCreateComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = newCommentBody.trim();
    if (!body || readOnly || createCommentMutation.isPending) return;
    await createCommentMutation.mutateAsync(body);
    setNewCommentBody('');
  }

  async function handleEditComment(comment: Comment) {
    const nextBody = window.prompt('Новый текст комментария', comment.body)?.trim();
    if (!nextBody || nextBody === comment.body) return;
    await updateCommentMutation.mutateAsync({ commentId: comment.id, body: nextBody });
  }

  async function handleDeleteComment(comment: Comment) {
    if (!window.confirm('Удалить комментарий?')) return;
    await deleteCommentMutation.mutateAsync(comment.id);
  }

  if (!cardId) return null;

  return (
    <div
      className={`drawer drawer--${cardDetailsMode}`}
      onClick={closeDrawer}
      role="presentation"
      data-testid="card-details-overlay"
      style={boardAppearance ? getBoardThemeStyle(boardAppearance, resolvedTheme) : undefined}
    >
      <aside
        className="drawer__surface"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="card-details-title"
        data-testid="card-details-dialog"
      >
        <div className="drawer__header">
          <div>
            <h3 id="card-details-title">Карточка</h3>
            <p className="muted">Описание, метки, чек-листы, комментарии и история.</p>
          </div>
          <Button variant="ghost" iconOnly onClick={closeDrawer} title="Закрыть" aria-label="Закрыть">
            <Icon name="close" />
          </Button>
        </div>

        {cardQuery.isLoading && !card ? <LoadingState label="Загружаем карточку…" /> : null}
        {cardQuery.isError && !card ? <ErrorState title="Не удалось загрузить карточку" onRetry={() => void cardQuery.refetch()} /> : null}

        {card ? (
          <>
            {readOnly ? (
              <div className="inline-banner"><strong>Режим чтения.</strong><span>Изменения карточки недоступны для гостя; локальное напоминание остаётся доступно.</span></div>
            ) : null}
            <div className="grid" style={{ gap: 14 }}>
              <TextField label="Название" value={title} disabled={readOnly} onChange={(event) => setTitle(event.target.value)} />
              <MarkdownEditor value={description} onChange={setDescription} readOnly={readOnly}/>
              <PriorityStars value={priority} onChange={setPriority} disabled={readOnly}/>
              <SelectField label="Колонка · это статус карточки" value={columnId} disabled={readOnly} onChange={(event) => setColumnId(event.target.value)}>
                {columnOptions.map((column) => (
                  <option key={column.id} value={column.id}>
                    {column.name}
                  </option>
                ))}
              </SelectField>
            </div>

            <section className="panel reminder-panel">
              <div className="entity-header">
                <div>
                  <h4>Напоминание</h4>
                  <p className="muted">Одно локальное напоминание на карточку. Между устройствами оно не синхронизируется.</p>
                </div>
                <Badge tone={reminderLocalDateTime ? 'done' : 'default'}>
                  {reminderLocalDateTime ? 'запланировано' : 'выключено'}
                </Badge>
              </div>
              <TextField
                label="Локальные дата и время"
                type="datetime-local"
                value={reminderLocalDateTime}
                min={toLocalDateTimeInput(new Date(Date.now() + 60_000))}
                onChange={(event) => {
                  setReminderLocalDateTime(event.target.value);
                  setReminderError(null);
                  setReminderNotice(null);
                }}
              />
              <div className="inline-actions">
                <Button type="button" onClick={() => setReminderOffset(60 * 60_000)}>Через час</Button>
                <Button type="button" onClick={() => setReminderOffset(24 * 60 * 60_000, true)}>Завтра в 09:00</Button>
                <Button type="button" variant="primary" onClick={() => void handleSaveReminder()} disabled={!reminderLocalDateTime}>Сохранить</Button>
                {user && getLocalCardReminder(card.id, user.id) ? (
                  <Button type="button" variant="ghost" onClick={handleRemoveReminder}>Отключить</Button>
                ) : null}
              </div>
              {reminderError ? <p className="form-error" role="alert">{reminderError}</p> : null}
              {reminderNotice ? <p className="muted">{reminderNotice}</p> : null}
              <p className="muted reminder-panel__limit">
                Web показывает напоминание, пока вкладка открыта. Android-клиент использует системное уведомление и не требует открытой вкладки.
              </p>
            </section>

            <div className="grid">
              <div className="key-value"><span className="muted">Создана</span><span>{formatDateTime(card.createdAt)}</span></div>
              <div className="key-value"><span className="muted">Изменена</span><span>{formatDateTime(card.updatedAt)}</span></div>
              <div className="key-value"><span className="muted">Архив</span><span>{card.isArchived ? 'да' : 'нет'}</span></div>
              <div className="key-value"><span className="muted">Синхронизация</span><span><Badge tone={cardSyncStatus === 'failed' ? 'urgent' : cardSyncStatus === 'pending' ? 'warning' : 'done'}>{cardSyncStatus === 'pending' ? 'сохранено локально' : cardSyncStatus === 'failed' ? 'ошибка' : 'готово'}</Badge></span></div>
            </div>

            <div className="inline-actions">
              <Button variant="primary" iconOnly onClick={() => void handleSave()} disabled={readOnly || updateCardMutation.isPending || moveCardMutation.isPending} title="Сохранить карточку" aria-label="Сохранить карточку">
                {updateCardMutation.isPending || moveCardMutation.isPending ? '…' : <Icon name="save" />}
              </Button>
              <Button iconOnly onClick={() => void handleArchiveToggle()} disabled={readOnly || archiveCardMutation.isPending || unarchiveCardMutation.isPending || isLocalPendingCard} title={card.isArchived ? 'Разархивировать карточку' : 'Архивировать карточку'} aria-label={card.isArchived ? 'Разархивировать карточку' : 'Архивировать карточку'}>
                {archiveCardMutation.isPending || unarchiveCardMutation.isPending ? '…' : <Icon name="archive" />}
              </Button>
              <Button onClick={() => void handleHideLocally()} disabled={readOnly || hideCardLocallyMutation.isPending || isLocalPendingCard || cardSyncStatus !== 'synced'} title="Скрыть карточку только на этом узле">
                {hideCardLocallyMutation.isPending ? 'Скрываем…' : 'Скрыть здесь'}
              </Button>
              <Button variant="danger" onClick={() => void handleDeleteEverywhere()} disabled={readOnly || deleteCardMutation.isPending || isLocalPendingCard || cardSyncStatus !== 'synced'} title="Распространить tombstone на все устройства">
                {deleteCardMutation.isPending ? 'Удаляем…' : 'Удалить везде'}
              </Button>
            </div>

            <p className="muted">
              «Скрыть здесь» меняет только этот узел и допускает возврат. «Удалить везде»
              создаёт tombstone; старые копии карточки больше не смогут её воскресить.
            </p>

            {isLocalPendingCard ? (
              <div className="inline-banner">
                <strong>Карточка сохранена локально.</strong>
                <span>Метки, чек-листы, комментарии и история станут доступны после синхронизации.</span>
              </div>
            ) : null}

            {!isLocalPendingCard ? (
              <>
                <section className="panel">
                  <div className="entity-header">
                    <div>
                      <h4>Метки</h4>
                  <p className="muted">Создайте метку доски и назначьте её карточке.</p>
                </div>
              </div>
              <form className="inline-form__row inline-form__row--tight" onSubmit={handleCreateLabel}>
                <TextField label="Метка" value={newLabelName} disabled={readOnly} onChange={(event) => setNewLabelName(event.target.value)} placeholder="Например, Ошибка" />
                <TextField label="Цвет" value={newLabelColor} disabled={readOnly} onChange={(event) => setNewLabelColor(event.target.value)} placeholder="#60a5fa" />
                <Button type="submit" variant="primary" iconOnly disabled={readOnly || createLabelMutation.isPending} title="Добавить метку" aria-label="Добавить метку"><Icon name="plus" size={16} /></Button>
              </form>
              {labelsQuery.isLoading ? <LoadingState label="Загружаем метки…" compact /> : null}
              {labelsQuery.isError ? <ErrorState title="Не удалось загрузить метки" compact /> : null}
              {labelsQuery.data?.items.length ? (
                <div className="grid" style={{ gap: 8 }}>
                  {labelsQuery.data.items.map((label) => {
                    const isChecked = selectedLabelIds.includes(label.id);
                    return (
                      <div key={label.id} className="toggle-row">
                        <label className="inline-actions" style={{ alignItems: 'center' }}>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => void handleToggleLabel(label.id)}
                            disabled={readOnly || replaceCardLabelsMutation.isPending}
                          />
                          <span className="badge" style={{ borderColor: label.color }}>
                            {label.name}
                          </span>
                        </label>
                        <div className="row-actions">
                          <Button iconOnly onClick={() => void handleRenameLabel(label)} disabled={readOnly || updateLabelMutation.isPending} title="Переименовать метку" aria-label="Переименовать метку"><Icon name="edit" size={16} /></Button>
                          <Button variant="danger" iconOnly onClick={() => void handleDeleteLabel(label)} disabled={readOnly || deleteLabelMutation.isPending} title="Удалить метку" aria-label="Удалить метку"><Icon name="trash" size={16} /></Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {!labelsQuery.isLoading && !labelsQuery.isError && !labelsQuery.data?.items.length ? <EmptyState title="Меток пока нет" compact /> : null}
            </section>

            <section className="panel">
              <div className="entity-header">
                <div>
                  <h4>Чек-листы</h4>
                  <p className="muted">Создавайте списки и отмечайте выполненные пункты.</p>
                </div>
              </div>
              <form className="inline-form__row inline-form__row--tight" onSubmit={handleCreateChecklist}>
                <TextField label="Новый чек-лист" value={newChecklistTitle} disabled={readOnly} onChange={(event) => setNewChecklistTitle(event.target.value)} placeholder="Критерии готовности" />
                <Button type="submit" variant="primary" iconOnly disabled={readOnly || createChecklistMutation.isPending} title="Добавить чек-лист" aria-label="Добавить чек-лист"><Icon name="plus" size={16} /></Button>
              </form>
              {checklistsQuery.isLoading ? <LoadingState label="Загружаем чек-листы…" compact /> : null}
              {checklistsQuery.isError ? <ErrorState title="Не удалось загрузить чек-листы" compact /> : null}
              {checklistsQuery.data?.items.length ? (
                <div className="grid" style={{ gap: 14 }}>
                  {checklistsQuery.data.items.map((checklist) => (
                    <div key={checklist.id} className="activity-item">
                      <div className="entity-header">
                        <div>
                          <strong>{checklist.title}</strong>
                          <p className="muted">Выполнено: {checklist.items.filter((item) => item.isDone).length} из {checklist.items.length}</p>
                        </div>
                        <div className="row-actions">
                          <Button iconOnly onClick={() => void handleRenameChecklist(checklist)} disabled={readOnly || updateChecklistMutation.isPending} title="Переименовать чек-лист" aria-label="Переименовать чек-лист"><Icon name="edit" size={16} /></Button>
                          <Button variant="danger" iconOnly onClick={() => void handleDeleteChecklist(checklist)} disabled={readOnly || deleteChecklistMutation.isPending} title="Удалить чек-лист" aria-label="Удалить чек-лист"><Icon name="trash" size={16} /></Button>
                        </div>
                      </div>
                      <div className="grid" style={{ gap: 8 }}>
                        {checklist.items.map((item) => (
                          <div key={item.id} className="toggle-row">
                            <label className="inline-actions" style={{ alignItems: 'center' }}>
                              <input
                                type="checkbox"
                                checked={item.isDone}
                                onChange={() => void handleToggleChecklistItem(item)}
                                disabled={readOnly || updateChecklistItemMutation.isPending}
                              />
                              <span style={{ textDecoration: item.isDone ? 'line-through' : undefined }}>{item.title}</span>
                            </label>
                            <div className="row-actions">
                              <Button iconOnly onClick={() => void handleRenameChecklistItem(item)} disabled={readOnly || updateChecklistItemMutation.isPending} title="Переименовать пункт" aria-label="Переименовать пункт"><Icon name="edit" size={16} /></Button>
                              <Button variant="danger" iconOnly onClick={() => void handleDeleteChecklistItem(item)} disabled={readOnly || deleteChecklistItemMutation.isPending} title="Удалить пункт" aria-label="Удалить пункт"><Icon name="trash" size={16} /></Button>
                            </div>
                          </div>
                        ))}
                        <div className="inline-form__row inline-form__row--tight">
                          <TextField
                            label="Новый пункт"
                            value={newItemByChecklist[checklist.id] || ''}
                            disabled={readOnly}
                            onChange={(event) => setNewItemByChecklist((current) => ({ ...current, [checklist.id]: event.target.value }))}
                            onKeyDown={(event) => handleChecklistItemKeyDown(checklist.id, event)}
                            placeholder="Сделать smoke"
                            title={checklistSubmitHint(checklistItemSubmitMode)}
                          />
                          <Button type="button" variant="primary" iconOnly onClick={() => void handleCreateChecklistItem(checklist.id)} disabled={readOnly || createChecklistItemMutation.isPending} title="Добавить пункт" aria-label="Добавить пункт"><Icon name="plus" size={16} /></Button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
              {!checklistsQuery.isLoading && !checklistsQuery.isError && !checklistsQuery.data?.items.length ? <EmptyState title="Чек-листов пока нет" compact /> : null}
            </section>

            <section className="panel">
              <div className="entity-header">
                <div>
                  <h4>Комментарии</h4>
                  <p className="muted">Заметки и обсуждение внутри карточки.</p>
                </div>
              </div>
              <form className="grid" style={{ gap: 10 }} onSubmit={handleCreateComment}>
                <TextAreaField label="Новый комментарий" value={newCommentBody} disabled={readOnly} onKeyDown={event => { if (shouldSubmitChecklistItem(effectiveUserAppearance?.checklistItemSubmitMode || 'ctrl_enter', {...event,isComposing:event.nativeEvent.isComposing})) { event.preventDefault(); if(!createCommentMutation.isPending) event.currentTarget.form?.requestSubmit(); } }} onChange={(event) => setNewCommentBody(event.target.value)} placeholder="Оставить заметку по карточке…" />
                <Button type="submit" variant="primary" disabled={readOnly || createCommentMutation.isPending}><Icon name="plus" size={16} /> Добавить</Button>
              </form>
              {commentsQuery.isLoading ? <LoadingState label="Загружаем комментарии…" compact /> : null}
              {commentsQuery.isError ? <ErrorState title="Не удалось загрузить комментарии" compact /> : null}
              {commentsQuery.data?.items.length ? (
                <div className="grid" style={{ gap: 10 }}>
                  {commentsQuery.data.items.map((comment) => (
                    <article key={comment.id} className="activity-item">
                      <div className="activity-item__header">
                        <div>
                          <strong>Комментарий</strong>
                          <p className="muted">{formatDateTime(comment.createdAt)}{comment.editedAt ? ` · изменён ${formatDateTime(comment.editedAt)}` : ''}</p>
                        </div>
                        <div className="row-actions">
                          <Button iconOnly onClick={() => void handleEditComment(comment)} disabled={readOnly || updateCommentMutation.isPending} title="Редактировать комментарий" aria-label="Редактировать комментарий"><Icon name="edit" size={16} /></Button>
                          <Button variant="danger" iconOnly onClick={() => void handleDeleteComment(comment)} disabled={readOnly || deleteCommentMutation.isPending} title="Удалить комментарий" aria-label="Удалить комментарий"><Icon name="trash" size={16} /></Button>
                        </div>
                      </div>
                      <p>{comment.body}</p>
                    </article>
                  ))}
                </div>
              ) : null}
              {!commentsQuery.isLoading && !commentsQuery.isError && !commentsQuery.data?.items.length ? <EmptyState title="Комментариев пока нет" compact /> : null}
            </section>

            <section className="panel">
              <div className="entity-header">
                <div>
                  <h4>История карточки</h4>
                  <p className="muted">Последние понятные действия с карточкой.</p>
                </div>
              </div>
              {activityQuery.isLoading ? <LoadingState label="Загружаем историю карточки…" compact /> : null}
              {activityQuery.isError ? <ErrorState title="Не удалось загрузить историю карточки" compact /> : null}
              {activityQuery.data ? <ActivityFeed items={activityQuery.data.items} emptyTitle="История карточки пока пустая" /> : null}
              {!activityQuery.isLoading && !activityQuery.isError && !activityQuery.data ? <EmptyState title="История карточки пока пустая" compact /> : null}
            </section>
              </>
            ) : null}
          </>
        ) : null}
      </aside>
    </div>
  );
}
