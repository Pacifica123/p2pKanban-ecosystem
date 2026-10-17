import { useMemo, useState } from 'react';
import type { ProjectBoardPayload } from '../../shared/api/types';
import { ErrorDetails } from '../../shared/errorReport/ErrorDetails';
import { getProjectBoard } from './api';
import { projectBoardColumns, projectBoardLine, type ProjectBoardCard } from './model';

// contracts/project-board/1: the board the ecosystem develops on, compiled into
// abl, read-only and outside the profile, so connecting devices never copies it.
export function ProjectBoardPanel() {
  const [board, setBoard] = useState<ProjectBoardPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openCardId, setOpenCardId] = useState<string | null>(null);
  const columns = useMemo(() => (board ? projectBoardColumns(board.raw) : []), [board]);

  function load(open: boolean) {
    if (!open || board) return;
    getProjectBoard()
      .then((value) => { setBoard(value); setError(null); })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)));
  }

  return (
    <details className="project-board" onToggle={(event) => load(event.currentTarget.open)}>
      <summary>
        <span className="kicker">Доска проекта · только чтение</span>
        <strong>{board ? projectBoardLine(board) : 'Встроена в abl, открывается без сети'}</strong>
      </summary>
      <p className="project-board__note">
        Доска, на которой p2pKanban ведёт свою разработку. Она встроена в приложение и не входит в ваши пространства,
        поэтому подключение устройств её не размножает. Правки приходят патчами в репозиторий.
      </p>
      {error ? <div className="error-banner" role="alert">{error}<ErrorDetails message={error} /></div> : null}
      {board && !error ? (
        <div className="project-board__columns">
          {columns.map((column) => (
            <section key={column.id} className="project-board__column" aria-label={column.name}>
              <h3>{column.name} <span className="count">{column.cards.length}</span></h3>
              {column.cards.map((card) => (
                <ProjectBoardTile
                  key={card.id}
                  card={card}
                  open={openCardId === card.id}
                  onToggle={() => setOpenCardId((current) => (current === card.id ? null : card.id))}
                />
              ))}
            </section>
          ))}
        </div>
      ) : null}
    </details>
  );
}

function ProjectBoardTile({ card, open, onToggle }: { card: ProjectBoardCard; open: boolean; onToggle: () => void }) {
  return (
    <article className="project-board__card">
      <button type="button" className="project-board__card-title" aria-expanded={open} onClick={onToggle}>{card.title}</button>
      {card.labels.length ? (
        <div className="project-board__labels">
          {card.labels.map((label) => (
            <span key={label.name} style={{ borderColor: label.color }}><i style={{ background: label.color }} />{label.name}</span>
          ))}
        </div>
      ) : null}
      <small>
        {card.total ? `чек-лист ${card.done}/${card.total}` : ''}
        {card.total && card.comments.length ? ' · ' : ''}
        {card.comments.length ? `комментариев: ${card.comments.length}` : ''}
      </small>
      {open ? (
        <div className="project-board__details">
          <p className="project-board__body">{card.description || 'Без описания.'}</p>
          {card.checklists.map((checklist) => (
            <div key={checklist.id}>
              <strong>{checklist.title}</strong>
              <ul>
                {checklist.items.map((item) => (
                  <li key={item.id} className={item.isDone ? 'is-done' : ''}>{item.isDone ? '✓' : '○'} {item.title}</li>
                ))}
              </ul>
            </div>
          ))}
          {card.comments.map((comment) => (
            <p key={comment.id} className="project-board__comment">
              {comment.createdAt ? <small>{comment.createdAt.slice(0, 10)}</small> : null}
              {comment.body}
            </p>
          ))}
        </div>
      ) : null}
    </article>
  );
}
