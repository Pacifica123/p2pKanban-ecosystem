import type { Board, BoardAppearanceSettings } from '@/shared/types/api';
import { formatDateTime } from '@/shared/lib/date';
import { Icon } from '@/shared/ui/Icon';

interface BoardOverviewPanelProps {
  board: Board | undefined;
  boardAppearance?: BoardAppearanceSettings;
  columnCount: number;
  cardCount: number;
}

function plural(value: number, one: string, few: string, many: string) {
  const modulo100 = value % 100;
  const modulo10 = value % 10;
  if (modulo100 >= 11 && modulo100 <= 19) return many;
  if (modulo10 === 1) return one;
  if (modulo10 >= 2 && modulo10 <= 4) return few;
  return many;
}

export function BoardOverviewPanel({ board, boardAppearance, columnCount, cardCount }: BoardOverviewPanelProps) {
  return (
    <details className="board-overview">
      <summary className="board-overview__summary">
        <span>О доске</span>
        <span className="board-overview__facts">
          {columnCount} {plural(columnCount, 'колонка', 'колонки', 'колонок')}
          <span aria-hidden="true">·</span>
          {cardCount} {plural(cardCount, 'карточка', 'карточки', 'карточек')}
          <span aria-hidden="true">·</span>
          изменена {formatDateTime(board?.updatedAt)}
        </span>
        <Icon name="chevron" size={15} />
      </summary>

      <div className="board-overview__details">
        <div>
          <span className="meta-line">Описание</span>
          <p>{board?.description || 'Описание не добавлено.'}</p>
        </div>
        {boardAppearance ? (
          <div>
            <span className="meta-line">Оформление</span>
            <p>
              {boardAppearance.themePreset} · {boardAppearance.columnDensity} · {boardAppearance.cardPreviewMode}
            </p>
          </div>
        ) : null}
      </div>
    </details>
  );
}
