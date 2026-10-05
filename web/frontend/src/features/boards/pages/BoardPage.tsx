import {DevctlPanel} from '@/features/integrations/components/DevctlPanel';
import {orderCards} from '@/shared/lib/cardOrder';
import {PriorityStars} from '@/shared/ui/PriorityStars';
import { DragEvent, FormEvent, ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { paths } from '@/app/router/paths';
import { useAppearance } from '@/app/providers/AppearanceProvider';
import { ActivityFeed } from '@/features/activity/components/ActivityFeed';
import { ProductivityGraph } from '@/features/activity/components/ProductivityGraph';
import { useBoardActivityQuery } from '@/features/activity/hooks/useActivity';
import { useBoardAppearanceQuery } from '@/features/appearance/hooks/useAppearance';
import { BoardColumnSection } from '@/features/boards/components/BoardColumnSection';
import { BoardOverviewPanel } from '@/features/boards/components/BoardOverviewPanel';
import { useBoardQuery, useUpdateBoardMutation } from '@/features/boards/hooks/useBoards';
import {
  buildColumnReorderItems,
  CardMoveIntent,
  getDropPositionValue,
  groupCardsByColumn,
  reorderBoardPreview,
  sortCardsByPosition,
} from '@/features/boards/lib/cardDnd';
import { getChecklistProgress } from '@/features/boards/lib/checklistProgress';
import { useColumnsQuery, useCreateColumnMutation, useDeleteColumnMutation, useUpdateColumnMutation } from '@/features/columns/hooks/useColumns';
import { CardDetailsDrawer } from '@/features/cards/components/CardDetailsDrawer';
import { useCardsQuery, useUnhideCardLocallyMutation } from '@/features/cards/hooks/useCards';
import { LocalFirstStatusBanner } from '@/features/localFirst/components/LocalFirstStatusBanner';
import { SyncBaselineStatus } from '@/features/sync/components/SyncBaselineStatus';
import { useSyncBaseline } from '@/features/sync/hooks/useSyncBaseline';
import { LocalFirstBoardProvider } from '@/features/localFirst/context/LocalFirstBoardContext';
import { createPortableExport } from '@/features/integrations/api/importExport';
import { useLocalFirstBoardRuntime } from '@/features/localFirst/hooks/useLocalFirstBoard';
import { getBoardSurfaceStyle } from '@/shared/appearance/theme';
import { formatDateTime } from '@/shared/lib/date';
import { formatCountRu } from '@/shared/lib/russian';
import type { BoardColumn, Card } from '@/shared/types/api';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Icon } from '@/shared/ui/Icon';
import { LoadingState } from '@/shared/ui/LoadingState';
import { useWorkspacesQuery } from '@/features/workspaces/hooks/useWorkspaces';

interface DragSessionState extends CardMoveIntent {
  overColumnId: string;
  overIndex: number;
}

export function BoardPage() {
  const navigate = useNavigate();
  const { workspaceId, boardId } = useParams();
  const [, setSearchParams] = useSearchParams();

  const { resolvedTheme } = useAppearance();
  const boardQuery = useBoardQuery(boardId);
  const workspacesQuery = useWorkspacesQuery();
  const workspace = workspacesQuery.data?.items.find((item) => item.id === workspaceId);
  const canEdit = workspace?.currentUserRole === 'owner' || workspace?.currentUserRole === 'member';
  const columnsQuery = useColumnsQuery(boardId);
  const cardsQuery = useCardsQuery(boardId);
  const hiddenCardsQuery = useCardsQuery(boardId, 'hidden');
  const unhideCardMutation = useUnhideCardLocallyMutation(boardId);
  const boardActivityQuery = useBoardActivityQuery(boardId);
  const boardAppearanceQuery = useBoardAppearanceQuery(boardId);
  const createColumnMutation = useCreateColumnMutation(boardId);
  const updateColumnMutation = useUpdateColumnMutation(boardId);
  const deleteColumnMutation = useDeleteColumnMutation(boardId);
  const updateBoardMutation = useUpdateBoardMutation(workspaceId, boardId);
  const localFirst = useLocalFirstBoardRuntime({
    workspaceId,
    boardId,
    board: boardQuery.data,
    columns: columnsQuery.data?.items,
    cards: cardsQuery.data?.items,
    onRemoteFlush: async () => {
      await Promise.all([cardsQuery.refetch(), boardActivityQuery.refetch()]);
    },
  });
  const syncBaseline = useSyncBaseline(workspaceId);

  const [newColumnName, setNewColumnName] = useState('');
  const [dragSession, setDragSession] = useState<DragSessionState | null>(null);
  const [optimisticCards, setOptimisticCards] = useState<Card[] | null>(null);
  const [moveError, setMoveError] = useState<string | null>(null);
  const [exportStatus, setExportStatus] = useState<string | null>(null);
  const [isExporting, setIsExporting] = useState(false);
  const [isColumnComposerOpen, setColumnComposerOpen] = useState(false);
  const [isActivityOpen, setActivityOpen] = useState(false);
  const [isHiddenCardsOpen, setHiddenCardsOpen] = useState(false);
  const [prioritySort,setPrioritySort]=useState<Record<string,boolean>>({});
  const dropHandledRef = useRef(false);

  const hasPendingCardMove = localFirst.isFlushing;
  const boardAppearance = boardAppearanceQuery.data;

  const orderedColumns = useMemo(
    () => [...localFirst.columns].sort((left, right) => left.position - right.position),
    [localFirst.columns],
  );

  const currentCards = useMemo(
    () => sortCardsByPosition(optimisticCards || localFirst.cards),
    [localFirst.cards, optimisticCards],
  );

  const groupedCards = useMemo(() => {
    const map = new Map<string, Card[]>();
    orderedColumns.forEach((column) => map.set(column.id, []));
    currentCards.forEach((card) => {
      const items = map.get(card.columnId) || [];
      items.push(card);
      map.set(card.columnId, items);
    });
    return map;
  }, [currentCards, orderedColumns]);

  useEffect(() => {
    if (!isActivityOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActivityOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [isActivityOpen]);

  function handleCreateColumn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEdit || !newColumnName.trim()) return;
    createColumnMutation.mutate(
      { name: newColumnName.trim() },
      {
        onSuccess: () => {
          setNewColumnName('');
          setColumnComposerOpen(false);
        },
      },
    );
  }

  async function handleRenameColumn(column: BoardColumn) {
    const next = window.prompt('Новое название колонки', column.name)?.trim();
    if (!next || next === column.name) return;
    await updateColumnMutation.mutateAsync({ columnId: column.id, input: { name: next } });
  }

  async function handleDeleteColumn(column: BoardColumn) {
    if (!window.confirm(`Удалить колонку «${column.name}»?`)) return;
    await deleteColumnMutation.mutateAsync(column.id);
  }

  async function handleRenameBoard() {
    if (!boardQuery.data) return;
    const next = window.prompt('Новое название доски', boardQuery.data.name)?.trim();
    if (!next || next === boardQuery.data.name) return;
    await updateBoardMutation.mutateAsync({ input: { name: next } });
  }

  async function handleExportBoardBackup() {
    if (!workspaceId || !boardId || isExporting) return;
    setIsExporting(true);
    setExportStatus(null);
    try {
      const response = await createPortableExport({
        scopeKind: 'board',
        workspaceId,
        boardId,
        exportMode: 'backup_snapshot',
        includeArchived: true,
        includeActivityHistory: true,
        includeAppearance: true,
      });
      const blob = new Blob([JSON.stringify(response.bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = response.suggestedFileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      const counts = response.bundleManifest.summary.entityCounts;
      setExportStatus(`Резервная копия готова: ${formatCountRu(counts.columns, 'колонка', 'колонки', 'колонок')}, ${formatCountRu(counts.cards, 'карточка', 'карточки', 'карточек')}.`);
    } catch (error) {
      setExportStatus(error instanceof Error ? error.message : 'Не удалось создать резервную копию.');
    } finally {
      setIsExporting(false);
    }
  }

  function handleCardDragStart(card: Card, cardsInColumn: Card[], event: DragEvent<HTMLElement>) {
    if (!canEdit || hasPendingCardMove) return;
    const sourceIndex = cardsInColumn.findIndex((item) => item.id === card.id);
    if (sourceIndex === -1) return;

    dropHandledRef.current = false;
    setMoveError(null);
    setDragSession({
      cardId: card.id,
      sourceColumnId: card.columnId,
      sourceIndex,
      targetColumnId: card.columnId,
      targetIndex: sourceIndex,
      overColumnId: card.columnId,
      overIndex: sourceIndex,
    });

    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', card.id);
  }

  function handleCardDragOver(columnId: string, visibleIndex: number, event: DragEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();

    const bounds = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect();
    if (!bounds) return;

    const shouldInsertAfter = event.clientY > bounds.top + bounds.height / 2;
    const nextIndex = visibleIndex + (shouldInsertAfter ? 1 : 0);

    setDragSession((current) => {
      if (!current) return current;
      if (current.overColumnId === columnId && current.overIndex === nextIndex) {
        return current;
      }
      return {
        ...current,
        targetColumnId: columnId,
        targetIndex: nextIndex,
        overColumnId: columnId,
        overIndex: nextIndex,
      };
    });
  }

  function handleColumnDragOver(columnId: string, itemCount: number, event: DragEvent<HTMLElement>) {
    event.preventDefault();
    setDragSession((current) => {
      if (!current) return current;
      if (current.overColumnId === columnId && current.overIndex === itemCount) {
        return current;
      }
      return {
        ...current,
        targetColumnId: columnId,
        targetIndex: itemCount,
        overColumnId: columnId,
        overIndex: itemCount,
      };
    });
  }

  function handleCardDragEnd() {
    if (dropHandledRef.current) {
      dropHandledRef.current = false;
      return;
    }
    setDragSession(null);
  }

  async function handleCardDrop(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!canEdit) return;
    dropHandledRef.current = true;

    const session = dragSession;
    if (!session || !boardId) {
      setDragSession(null);
      return;
    }

    setDragSession(null);

    if (session.sourceColumnId === session.targetColumnId && session.sourceIndex === session.targetIndex) {
      return;
    }

    const serverCards = sortCardsByPosition(localFirst.cards);
    const optimistic = reorderBoardPreview(serverCards, session);
    setOptimisticCards(optimistic);
    setMoveError(null);

    try {
      if (session.sourceColumnId === session.targetColumnId) {
        const reorderedColumnCards = groupCardsByColumn(optimistic).get(session.targetColumnId) || [];
        localFirst.enqueueReorderColumnCards(session.targetColumnId, {
          items: buildColumnReorderItems(reorderedColumnCards),
        });
      } else {
        const targetCardsWithoutDragged = (groupCardsByColumn(serverCards).get(session.targetColumnId) || [])
          .filter((card) => card.id !== session.cardId);
        localFirst.enqueueMoveCard(session.cardId, {
          targetColumnId: session.targetColumnId,
          position: getDropPositionValue(targetCardsWithoutDragged, session.targetIndex),
        });
      }

      setOptimisticCards(null);
    } catch (error) {
      setOptimisticCards(null);
      setMoveError(error instanceof Error ? error.message : 'Не удалось сохранить новое положение карточки.');
    }
  }

  function renderColumnCards(columnId: string, cards: Card[]): ReactNode {
    if (!cards.length && !dragSession) {
      return <div className="column-empty">Перетащите карточку сюда или создайте новую.</div>;
    }

    const dragCardId = dragSession?.cardId;
    const dropIndex = dragSession?.overColumnId === columnId ? dragSession.overIndex : -1;
    const rows: ReactNode[] = [];
    let visibleIndex = 0;

    orderCards(cards, Boolean(prioritySort[columnId])).forEach((card) => {
      const isDraggedCard = dragCardId === card.id;
      if (!isDraggedCard && dropIndex === visibleIndex) {
        rows.push(<div key={`drop-${columnId}-${visibleIndex}`} className="card-drop-indicator">Переместить сюда</div>);
      }

      const currentVisibleIndex = visibleIndex;
      const checklistProgress = getChecklistProgress(card);
      rows.push(
        <div key={card.id} className="card-slot">
          <article
            draggable={Boolean(canEdit && !hasPendingCardMove && !prioritySort[columnId])}
            className={`card-tile ${boardAppearance?.cardPreviewMode === 'compact' ? 'card-tile--compact' : ''} ${isDraggedCard ? 'card-tile--ghosted' : ''}`}
            data-testid="card-tile"
            onDragStart={(event) => handleCardDragStart(card, cards, event)}
            onDragOver={event=>{if(!prioritySort[columnId])handleCardDragOver(columnId,currentVisibleIndex,event);}}
            onDragEnd={handleCardDragEnd}
            onClick={() => {
              if (dragSession) return;
              setSearchParams((prev) => {
                const next = new URLSearchParams(prev);
                next.set('card', card.id);
                return next;
              });
            }}
          >
            <div className="card-tile__header">
              <strong>{card.title}</strong>
              {card.isArchived ? <Badge tone="warning">в архиве</Badge> : null}
            </div>
            {(boardAppearance?.showCardDescription ?? true) && boardAppearance?.cardPreviewMode !== 'compact' && card.description ? (
              <p className="muted">{card.description}</p>
            ) : null}
            {(boardAppearance?.showChecklistProgress ?? true) && checklistProgress ? (
              <div
                className="card-checklist-progress"
                aria-label={`Чек-лист выполнен на ${checklistProgress.percent}%`}
              >
                <div className="card-checklist-progress__track">
                  <span
                    className={checklistProgress.percent === 100 ? 'is-complete' : ''}
                    style={{ width: `${checklistProgress.percent}%` }}
                  />
                </div>
                <span className="card-checklist-progress__value">
                  {checklistProgress.completed}/{checklistProgress.total}
                </span>
              </div>
            ) : null}
            <div className="card-tile__footer">
              <PriorityStars value={card.priority}/>
              {localFirst.getEntityStatus('card', card.id)?.status === 'pending' ? <Badge tone="warning">сохранено локально</Badge> : null}
              {localFirst.getEntityStatus('card', card.id)?.status === 'failed' ? <Badge tone="urgent">ошибка синхронизации</Badge> : null}
              {(boardAppearance?.showCardDates ?? true) && card.dueAt ? <Badge tone="default">до {formatDateTime(card.dueAt)}</Badge> : null}
              {(boardAppearance?.showCardDates ?? true) && !card.dueAt && card.startAt ? <Badge tone="default">с {formatDateTime(card.startAt)}</Badge> : null}
            </div>
          </article>
        </div>,
      );

      if (!isDraggedCard) {
        visibleIndex += 1;
      }
    });

    if (dropIndex === visibleIndex) {
      rows.push(<div key={`drop-${columnId}-end`} className="card-drop-indicator">Переместить сюда</div>);
    }

    return <div className={`card-list ${dragSession ? 'card-list--dragging' : ''}`}>{rows}</div>;
  }

  if (!boardId || !workspaceId) {
    return <ErrorState title="Доска не выбрана" description="Выберите доску в боковой панели." />;
  }

  const hasLocalSnapshot = Boolean(localFirst.snapshot);
  const isLoading = !hasLocalSnapshot && (boardQuery.isLoading || columnsQuery.isLoading || cardsQuery.isLoading);
  const isError = !hasLocalSnapshot && (boardQuery.isError || columnsQuery.isError || cardsQuery.isError);

  return (
    <LocalFirstBoardProvider value={localFirst}>
      <div className="page-shell" data-testid="board-page">
        <section className="page-header">
          <div>
            <h2 data-testid="board-title">{localFirst.board?.name || 'Доска'}</h2>
            {localFirst.board?.description ? <p className="muted">{localFirst.board.description}</p> : null}
          </div>
          <div className="page-header__actions">
            <Button variant="ghost" onClick={() => navigate(paths.workspaceBoards(workspaceId))}>
              <Icon name="back" size={16} />
              К доскам
            </Button>
            <Button variant="ghost" onClick={() => setActivityOpen(true)} title="Открыть историю доски">
              <Icon name="history" size={16} />
              История
            </Button>
            <Button variant="ghost" onClick={() => setHiddenCardsOpen((current) => !current)} title="Карточки, скрытые только на этом узле">
              Скрытые здесь{hiddenCardsQuery.data?.items.length ? ` (${hiddenCardsQuery.data.items.length})` : ''}
            </Button>
            {canEdit ? <Button iconOnly variant="ghost" onClick={() => navigate(paths.boardAppearance(workspaceId, boardId))} title="Оформление доски" aria-label="Оформление доски">
              <Icon name="palette" />
            </Button> : null}
            <Button iconOnly variant="ghost" onClick={() => void handleExportBoardBackup()} disabled={isExporting} title="Скачать резервную копию JSON" aria-label="Скачать резервную копию JSON">
              <Icon name="download" />
            </Button>
            {canEdit ? <Button iconOnly variant="ghost" onClick={() => void handleRenameBoard()} disabled={updateBoardMutation.isPending || !boardQuery.data} title="Переименовать доску" aria-label="Переименовать доску">
              <Icon name="edit" />
            </Button> : null}
            <Button iconOnly variant="ghost" onClick={() => void Promise.all([boardQuery.refetch(), columnsQuery.refetch(), cardsQuery.refetch(), boardActivityQuery.refetch(), boardAppearanceQuery.refetch(), localFirst.flushPendingOperations(), syncBaseline.pullWorkspace(), syncBaseline.refreshStatus()])} title="Обновить данные доски" aria-label="Обновить данные доски">
              <Icon name="refresh" />
            </Button>
          </div>
        </section>

        <LocalFirstStatusBanner runtime={localFirst} />
        <SyncBaselineStatus runtime={syncBaseline} />
        {workspace?.currentUserRole === 'guest' ? (
          <div className="inline-banner"><strong>Режим чтения.</strong><span>Гость не может изменять доску.</span></div>
        ) : null}

        {isHiddenCardsOpen ? (
          <section className="panel" data-testid="locally-hidden-cards">
            <div className="entity-header">
              <div>
                <h3>Скрытые только на этом узле</h3>
                <p className="muted">Эти карточки остаются на других устройствах и не создают событий в Nostr.</p>
              </div>
            </div>
            {hiddenCardsQuery.isLoading ? <LoadingState label="Загружаем скрытые карточки…" compact /> : null}
            {hiddenCardsQuery.data?.items.length ? (
              <div className="grid">
                {hiddenCardsQuery.data.items.map((card) => (
                  <div className="key-value" key={card.id}>
                    <span>{card.title}</span>
                    <Button
                      variant="ghost"
                      disabled={unhideCardMutation.isPending}
                      onClick={() => void unhideCardMutation.mutateAsync(card.id)}
                    >
                      Вернуть на этот узел
                    </Button>
                  </div>
                ))}
              </div>
            ) : hiddenCardsQuery.isSuccess ? <p className="muted">Локально скрытых карточек нет.</p> : null}
          </section>
        ) : null}

        {exportStatus ? (
          <div className="inline-banner">
            <strong>Резервная копия</strong>
            <span>{exportStatus}</span>
            <Button variant="ghost" iconOnly onClick={() => setExportStatus(null)} title="Скрыть сообщение" aria-label="Скрыть сообщение">
              <Icon name="close" size={16} />
            </Button>
          </div>
        ) : null}

        {moveError ? (
          <div className="inline-banner inline-banner--error">
            <strong>Перемещение карточки не сохранилось.</strong>
            <span>{moveError}</span>
            <Button variant="ghost" iconOnly onClick={() => setMoveError(null)} title="Скрыть сообщение" aria-label="Скрыть сообщение">
              <Icon name="close" size={16} />
            </Button>
          </div>
        ) : null}

        {isLoading ? <LoadingState label="Загружаем доску…" /> : null}
        {isError ? <ErrorState title="Не удалось загрузить доску" description="Проверьте соединение с сервером и повторите попытку." /> : null}

        {!isLoading && !isError ? (
          <div
            className={`board-themed-surface ${boardAppearance?.wallpaper.kind === 'image' ? 'board-themed-surface--wallpaper-image' : ''}`}
            style={boardAppearance ? getBoardSurfaceStyle(boardAppearance, resolvedTheme) : undefined}
          >
            <BoardOverviewPanel
              board={localFirst.board || undefined}
              boardAppearance={boardAppearance}
              columnCount={orderedColumns.length}
              cardCount={currentCards.length}
            />
            <ProductivityGraph boardId={boardId} />
            <DevctlPanel key={boardId} boardId={boardId} canCreate={workspace?.currentUserRole==='owner'} canImport={canEdit}/>
            <div className="board-main">
              {orderedColumns.length ? (
                <div className="columns-strip columns-strip--board-surface">
                  {orderedColumns.map((column) => {
                    const cards = groupedCards.get(column.id) || [];
                    const cardsWithoutDragged = dragSession ? cards.filter((card) => card.id !== dragSession.cardId) : cards;

                    return (
                      <BoardColumnSection
                        key={column.id}
                        boardId={boardId}
                        column={column}
                        cards={cards}
                        cardsWithoutDragged={cardsWithoutDragged}
                        isDropTarget={dragSession?.overColumnId === column.id}
                        isMutating={updateColumnMutation.isPending || deleteColumnMutation.isPending}
                        readOnly={!canEdit}
                        onRename={(item) => void handleRenameColumn(item)}
                        onDelete={(item) => void handleDeleteColumn(item)}
                        prioritySorted={Boolean(prioritySort[column.id])} onTogglePriority={()=>{setDragSession(null);setPrioritySort(current=>({...current,[column.id]:!current[column.id]}));}} onColumnDragOver={(id,count,event)=>{if(!prioritySort[id])handleColumnDragOver(id,count,event);}}
                        onDrop={(event) => void handleCardDrop(event)}
                        cardsContent={renderColumnCards(column.id, cards)}
                      />
                    );
                  })}

                  {canEdit ? <section className={`add-column-card ${isColumnComposerOpen ? 'is-open' : ''}`}>
                    {isColumnComposerOpen ? (
                      <form className="add-column-card__form" data-testid="column-create-form" onSubmit={handleCreateColumn}>
                        <label htmlFor="new-column-name">Новая колонка</label>
                        <input
                          autoFocus
                          id="new-column-name"
                          data-testid="column-name-input"
                          className="field__input"
                          value={newColumnName}
                          onChange={(event) => setNewColumnName(event.target.value)}
                          placeholder="Например, На проверке"
                        />
                        <div className="row-actions">
                          <Button data-testid="column-create-submit" type="submit" variant="primary" disabled={createColumnMutation.isPending || !newColumnName.trim()}>
                            {createColumnMutation.isPending ? 'Создаём…' : 'Добавить'}
                          </Button>
                          <Button type="button" variant="ghost" onClick={() => {
                            setNewColumnName('');
                            setColumnComposerOpen(false);
                          }}>
                            Отмена
                          </Button>
                        </div>
                      </form>
                    ) : (
                      <button type="button" className="add-column-card__button" data-testid="open-column-composer" onClick={() => setColumnComposerOpen(true)}>
                        <Icon name="plus" size={17} />
                        Добавить колонку
                      </button>
                    )}
                  </section> : null}
                </div>
              ) : (
                <section className="first-column-state">
                  <Icon name="board" size={28} />
                  <strong>На доске пока нет колонок</strong>
                  <span className="muted">{canEdit ? 'Создайте первую, чтобы добавить карточки.' : 'В этой доске пока нет колонок.'}</span>
                  {canEdit ? <Button variant="primary" data-testid="open-column-composer" onClick={() => setColumnComposerOpen(true)}>
                    <Icon name="plus" size={16} />
                    Создать колонку
                  </Button> : null}
                  {canEdit && isColumnComposerOpen ? (
                    <form className="add-column-card__form add-column-card__form--first" data-testid="column-create-form" onSubmit={handleCreateColumn}>
                      <input
                        autoFocus
                        data-testid="column-name-input"
                        className="field__input"
                        value={newColumnName}
                        onChange={(event) => setNewColumnName(event.target.value)}
                        placeholder="Название колонки"
                        aria-label="Название новой колонки"
                      />
                      <Button data-testid="column-create-submit" type="submit" variant="primary" disabled={createColumnMutation.isPending || !newColumnName.trim()}>
                        {createColumnMutation.isPending ? 'Создаём…' : 'Добавить'}
                      </Button>
                    </form>
                  ) : null}
                </section>
              )}
            </div>
          </div>
        ) : null}

        {isActivityOpen ? (
          <div className="activity-drawer" role="presentation" onMouseDown={(event) => {
            if (event.currentTarget === event.target) setActivityOpen(false);
          }}>
            <aside className="activity-drawer__surface" role="dialog" aria-modal="true" aria-labelledby="activity-title" data-testid="activity-feed">
              <div className="activity-drawer__header">
                <div>
                  <h3 id="activity-title">История доски</h3>
                  <p className="muted">Последние понятные действия. Технические данные скрыты внутри события.</p>
                </div>
                <Button iconOnly variant="ghost" onClick={() => setActivityOpen(false)} title="Закрыть историю" aria-label="Закрыть историю">
                  <Icon name="close" />
                </Button>
              </div>
              {boardActivityQuery.isLoading ? <LoadingState label="Загружаем историю…" compact /> : null}
              {boardActivityQuery.isError ? <ErrorState title="Не удалось загрузить историю" compact onRetry={() => void boardActivityQuery.refetch()} /> : null}
              {boardActivityQuery.data ? <ActivityFeed items={boardActivityQuery.data.items} emptyTitle="История пока пустая" /> : null}
            </aside>
          </div>
        ) : null}

        <CardDetailsDrawer boardAppearance={boardAppearance} resolvedTheme={resolvedTheme} readOnly={!canEdit} />
      </div>
    </LocalFirstBoardProvider>
  );
}
