import { DragEvent, ReactNode } from 'react';
import { CreateCardInlineForm } from '@/features/boards/components/CreateCardInlineForm';
import type { BoardColumn, Card } from '@/shared/types/api';
import { Button } from '@/shared/ui/Button';
import { Icon } from '@/shared/ui/Icon';
import { formatCountRu } from '@/shared/lib/russian';

interface BoardColumnSectionProps {
  boardId: string;
  column: BoardColumn;
  cards: Card[];
  cardsWithoutDragged: Card[];
  isDropTarget: boolean;
  isMutating: boolean;
  readOnly?: boolean;
  prioritySorted:boolean; onTogglePriority:()=>void;
  onRename: (column: BoardColumn) => void;
  onDelete: (column: BoardColumn) => void;
  onColumnDragOver: (columnId: string, itemCount: number, event: DragEvent<HTMLElement>) => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  cardsContent: ReactNode;
}

export function BoardColumnSection({
  boardId,
  column,
  cards,
  cardsWithoutDragged,
  isDropTarget,
  isMutating,
  readOnly = false, prioritySorted, onTogglePriority,
  onRename,
  onDelete,
  onColumnDragOver,
  onDrop,
  cardsContent,
}: BoardColumnSectionProps) {
  return (
    <section
      className={`column-card ${isDropTarget ? 'column-card--drop-target' : ''}`}
      data-testid="board-column"
      onDragOver={readOnly ? undefined : (event) => onColumnDragOver(column.id, cardsWithoutDragged.length, event)}
      onDrop={readOnly ? undefined : onDrop}
    >
      <div className="column-card__header">
        <div>
          <h3>{column.name}</h3>
          <p className="muted">{formatCountRu(cards.length, 'карточка', 'карточки', 'карточек')}</p>
        </div>
        {!readOnly ? <div className="row-actions">
          <Button iconOnly onClick={() => onRename(column)} disabled={isMutating} title="Переименовать колонку" aria-label="Переименовать колонку">
            <Icon name="edit" size={16} />
          </Button>
          <Button iconOnly variant="danger" onClick={() => onDelete(column)} disabled={isMutating} title="Удалить колонку" aria-label="Удалить колонку">
            <Icon name="trash" size={16} />
          </Button>
        </div> : null}
      </div>

      <Button aria-pressed={prioritySorted} onClick={onTogglePriority} title="Ручной порядок сохранён">{prioritySorted?'★ Сначала важные · вернуть ручной':'☆ По приоритету'}</Button>
      {!readOnly ? <div className="column-card__composer">
        <CreateCardInlineForm columnId={column.id} boardId={boardId} />
      </div> : null}
      {cardsContent}
    </section>
  );
}
