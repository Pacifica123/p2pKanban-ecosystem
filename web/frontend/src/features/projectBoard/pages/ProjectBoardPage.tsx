import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getProjectBoard, getProjectBoardSummary } from '@/features/projectBoard/api/projectBoard';
import {
  cardChecklists, cardComments, cardLabels, cardProgress, describeProjectBoard, projectBoardColumns,
} from '@/features/projectBoard/lib/projectBoard';
import type { BoardBundlePreview, ImportedCardSource } from '@/features/integrations/lib/boardBundle';
import { formatCountRu } from '@/shared/lib/russian';
import { MarkdownView } from '@/shared/markdown/MarkdownEditor';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Icon } from '@/shared/ui/Icon';
import { LoadingState } from '@/shared/ui/LoadingState';
import { PriorityStars } from '@/shared/ui/PriorityStars';

// contracts/project-board/1: the ecosystem's own board, read-only and outside
// the user's workspaces, so linking nodes never duplicates it.
export function ProjectBoardPage() {
  const summaryQuery = useQuery({ queryKey: ['project-board', 'summary'], queryFn: getProjectBoardSummary, staleTime: 60_000 });
  const boardQuery = useQuery({
    queryKey: ['project-board', 'board', summaryQuery.data?.served.summary.sha256 ?? null],
    queryFn: getProjectBoard,
    enabled: summaryQuery.isSuccess,
    staleTime: Number.POSITIVE_INFINITY,
  });
  const [openCardId, setOpenCardId] = useState<string | null>(null);

  if (summaryQuery.isLoading || (summaryQuery.isSuccess && boardQuery.isLoading)) {
    return <LoadingState label="Загружаем доску проекта…" />;
  }
  if (summaryQuery.isError || boardQuery.isError) {
    return (
      <ErrorState
        title="Не удалось загрузить доску проекта"
        error={summaryQuery.error ?? boardQuery.error}
        onRetry={() => void (summaryQuery.isError ? summaryQuery.refetch() : boardQuery.refetch())}
      />
    );
  }
  const preview = boardQuery.data;
  const summary = summaryQuery.data;
  if (!preview || !summary) return null;
  const { line, notes } = describeProjectBoard(summary);
  const columns = projectBoardColumns(preview);
  const openCard = openCardId ? preview.cards.find((card) => card.id === openCardId) ?? null : null;

  return (
    <div className="page-shell" data-testid="project-board-page">
      <header className="page-header">
        <div>
          <h2>Доска проекта</h2>
          <p className="muted" data-testid="project-board-revision">{line}</p>
        </div>
      </header>
      <p className="inline-banner" role="note">
        Только чтение. Это доска, на которой p2pKanban ведёт собственную разработку: она встроена в приложение и не
        входит в ваши пространства, поэтому подключение узлов её не размножает. Правки приходят патчами в репозиторий.
      </p>
      {notes.map((note) => <p key={note} className="muted" data-testid="project-board-note">{note}</p>)}
      <div className="board-main">
        <div className="columns-strip columns-strip--board-surface">
          {columns.map((column) => (
            <section key={column.id} className="column-card" data-testid="project-board-column">
              <div className="column-card__header">
                <div>
                  <h3>{column.name}</h3>
                  <p className="muted">{formatCountRu(column.cards.length, 'карточка', 'карточки', 'карточек')}</p>
                </div>
              </div>
              <div className="card-list">
                {column.cards.map((card) => (
                  <ProjectBoardCardTile key={card.id} preview={preview} card={card} onOpen={() => setOpenCardId(card.id)} />
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
      {openCard ? <ProjectBoardCardDetails preview={preview} card={openCard} onClose={() => setOpenCardId(null)} /> : null}
    </div>
  );
}

function LabelBadges({ preview, cardId }: { preview: BoardBundlePreview; cardId: string }) {
  const labels = cardLabels(preview, cardId);
  if (!labels.length) return null;
  return (
    <div className="project-board-labels">
      {labels.map((label) => (
        <span key={label.id} className="project-board-label" style={{ borderColor: label.color }}>
          <span className="project-board-label__dot" style={{ background: label.color }} />
          {label.name}
        </span>
      ))}
    </div>
  );
}

function ProjectBoardCardTile({ preview, card, onOpen }: { preview: BoardBundlePreview; card: ImportedCardSource; onOpen: () => void }) {
  const progress = cardProgress(preview, card.id);
  const comments = cardComments(preview, card.id).length;
  return (
    <article
      className="card-tile"
      data-testid="project-board-card"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <div className="card-tile__header"><strong>{card.title}</strong></div>
      <LabelBadges preview={preview} cardId={card.id} />
      {progress ? (
        <div className="card-checklist-progress" aria-label={`Чек-лист выполнен на ${progress.percent}%`}>
          <div className="card-checklist-progress__track">
            <span className={progress.percent === 100 ? 'is-complete' : ''} style={{ width: `${progress.percent}%` }} />
          </div>
          <span className="card-checklist-progress__value">{progress.done}/{progress.total}</span>
        </div>
      ) : null}
      <div className="card-tile__footer">
        <PriorityStars value={card.priority} />
        {comments ? <Badge tone="default">{formatCountRu(comments, 'комментарий', 'комментария', 'комментариев')}</Badge> : null}
      </div>
    </article>
  );
}

function ProjectBoardCardDetails({ preview, card, onClose }: { preview: BoardBundlePreview; card: ImportedCardSource; onClose: () => void }) {
  const column = preview.columns.find((item) => item.id === card.columnId);
  const checklists = cardChecklists(preview, card.id);
  const comments = cardComments(preview, card.id);
  return (
    <div className="drawer" onClick={onClose} role="presentation">
      <aside
        className="drawer__surface"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="project-board-card-title"
        data-testid="project-board-card-details"
      >
        <div className="drawer__header">
          <div>
            <h3 id="project-board-card-title">{card.title}</h3>
            <p className="muted">{column?.name ?? 'Без колонки'} · только чтение</p>
          </div>
          <Button variant="ghost" iconOnly onClick={onClose} title="Закрыть" aria-label="Закрыть">
            <Icon name="close" />
          </Button>
        </div>
        <LabelBadges preview={preview} cardId={card.id} />
        {card.description ? <MarkdownView source={card.description} /> : <p className="muted">Без описания.</p>}
        {checklists.map((checklist) => (
          <section key={checklist.id} className="project-board-checklist">
            <h4>{checklist.title}</h4>
            <ul>
              {checklist.items.map((item) => (
                <li key={item.id} className={item.isDone ? 'is-done' : ''}>
                  <span aria-hidden="true">{item.isDone ? '✓' : '○'}</span> {item.title}
                </li>
              ))}
            </ul>
          </section>
        ))}
        {comments.length ? (
          <section className="project-board-comments">
            <h4>Комментарии</h4>
            {comments.map((comment) => (
              <article key={comment.id} className="project-board-comment">
                {comment.createdAt ? <p className="muted">{comment.createdAt.slice(0, 10)}</p> : null}
                <MarkdownView source={comment.body} />
              </article>
            ))}
          </section>
        ) : null}
      </aside>
    </div>
  );
}
