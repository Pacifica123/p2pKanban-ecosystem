import { useAppearance } from '@/app/providers/AppearanceProvider';
import { Badge } from '@/shared/ui/Badge';
import { getBoardAccentColor, getBoardPresetDefinition, getBoardSurfaceStyle } from '@/shared/appearance/theme';
import type { BoardAppearanceSettings, UserAppearancePreferences } from '@/shared/types/api';

const themeLabels: Record<string, string> = {
  dark: 'тёмная',
  light: 'светлая',
  system: 'системная',
};

const densityLabels: Record<string, string> = {
  comfortable: 'свободная',
  compact: 'компактная',
};

const cardModeLabels: Record<string, string> = {
  compact: 'компактные',
  expanded: 'подробные',
};

const checklistSubmitModeLabels: Record<string, string> = {
  ctrl_enter: 'Ctrl+Enter',
  enter: 'Enter',
  button: 'только «+»',
};

const cardDetailsModeLabels: Record<string, string> = {
  drawer: 'сбоку',
  modal: 'по центру',
};

export function AppAppearancePreview({ appearance }: { appearance: UserAppearancePreferences }) {
  const { resolvedTheme } = useAppearance();

  return (
    <div className="appearance-preview-card">
      <div className="appearance-preview-card__header">
        <div>
          <h4>Предпросмотр приложения</h4>
          <p className="muted">Так будет выглядеть интерфейс после сохранения.</p>
        </div>
        <div className="row-actions">
          <Badge tone={appearance.appTheme}>{themeLabels[appearance.appTheme] || appearance.appTheme}</Badge>
          <Badge tone={resolvedTheme}>{resolvedTheme === 'dark' ? 'тёмная' : 'светлая'}</Badge>
          <Badge tone={appearance.density}>{densityLabels[appearance.density] || appearance.density}</Badge>
        </div>
      </div>
      <div className="app-preview-shell">
        <aside className="app-preview-shell__sidebar">
          <strong>p2pKanban</strong>
          <span className="muted">Навигация</span>
        </aside>
        <div className="app-preview-shell__main">
          <div className="app-preview-shell__topbar">
            <strong>Вид приложения</strong>
            <span className="muted">анимация: {appearance.reduceMotion ? 'снижена' : 'обычная'}</span>
          </div>
          <div className="app-preview-shell__content">
            <div className="app-preview-shell__panel">
              <strong>Рабочая панель</strong>
              <p className="muted">Тема и плотность применяются сразу.</p>
            </div>
            <div className="app-preview-shell__panel">
              <strong>Карточка</strong>
              <div className="app-preview-shell__chips">
                <span className="badge badge--default">
                  {cardDetailsModeLabels[appearance.cardDetailsMode] || appearance.cardDetailsMode}
                </span>
                <span className="badge badge--default">
                  пункт: {checklistSubmitModeLabels[appearance.checklistItemSubmitMode] || appearance.checklistItemSubmitMode}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function BoardAppearancePreview({ appearance }: { appearance: BoardAppearanceSettings }) {
  const { resolvedTheme } = useAppearance();
  const preset = getBoardPresetDefinition(appearance.themePreset);
  const accentColor = getBoardAccentColor(appearance);
  const cards = appearance.cardPreviewMode === 'compact' ? 2 : 3;
  return (
    <div className="appearance-preview-card">
      <div className="appearance-preview-card__header">
        <div>
          <h4>Предпросмотр доски</h4>
          <p className="muted">Фон, колонки и карточки до сохранения.</p>
        </div>
        <div className="row-actions">
          <Badge tone="default">{preset.label}</Badge>
          {accentColor ? <Badge tone="default">акцент {accentColor}</Badge> : null}
          <Badge tone={resolvedTheme}>{resolvedTheme === 'dark' ? 'тёмная' : 'светлая'}</Badge>
        </div>
      </div>
      <div
        className={`board-preview-surface ${appearance.wallpaper.kind === 'image' ? 'board-preview-surface--wallpaper-image' : ''}`}
        style={getBoardSurfaceStyle(appearance, resolvedTheme)}
      >
        <div className="board-preview-surface__topbar">
          <strong>План</strong>
          <div className="row-actions">
            <Badge tone={appearance.columnDensity}>{densityLabels[appearance.columnDensity] || appearance.columnDensity}</Badge>
            <Badge tone={appearance.cardPreviewMode}>{cardModeLabels[appearance.cardPreviewMode] || appearance.cardPreviewMode}</Badge>
          </div>
        </div>
        <div className="board-preview-columns">
          {['Будущее', 'Настоящее', 'Готово'].map((title, index) => (
            <section key={title} className="board-preview-column">
              <div className="column-card__header">
                <strong>{title}</strong>
                <span className="muted">{index + 2}</span>
              </div>
              <div className="card-list">
                {Array.from({ length: cards }).map((_, cardIndex) => (
                  <article key={`${title}-${cardIndex}`} className="card-tile">
                    <strong>{cardIndex === 0 ? 'Черновик оформления' : 'Карточка'}</strong>
                    {appearance.showCardDescription ? <p className="muted">Описание карточки.</p> : null}
                    <div className="card-tile__footer">
                      {appearance.showCardDates ? <Badge tone="default">дата</Badge> : null}
                      {appearance.showChecklistProgress ? <Badge tone="done">чек-лист</Badge> : null}
                    </div>
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
