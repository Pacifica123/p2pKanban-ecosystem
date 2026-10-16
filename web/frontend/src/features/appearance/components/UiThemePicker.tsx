import { useAppearance } from '@/app/providers/AppearanceProvider';
import { UI_THEMES } from '@/shared/appearance/uiThemes';
import { Badge } from '@/shared/ui/Badge';

export function UiThemePicker() {
  const { uiTheme, setUiTheme } = useAppearance();

  return (
    <div className="preset-grid" role="radiogroup" aria-label="Тема приложения">
      {UI_THEMES.map((theme) => {
        const isActive = theme.id === uiTheme;
        return (
          <button
            key={theme.id}
            type="button"
            role="radio"
            aria-checked={isActive}
            data-ui-theme-option={theme.id}
            className={`preset-card ${isActive ? 'is-active' : ''}`}
            onClick={() => setUiTheme(theme.id)}
          >
            <span className="ui-theme-swatch" style={{ background: theme.swatches.background }} aria-hidden="true">
              <span className="ui-theme-swatch__sidebar" style={{ background: theme.swatches.surface }} />
              <span className="ui-theme-swatch__lines">
                <span style={{ background: theme.swatches.text }} />
                <span style={{ background: theme.swatches.text }} />
                <span className="ui-theme-swatch__accent" style={{ background: theme.swatches.accent }} />
              </span>
            </span>
            <span className="preset-card__title-row">
              <strong>{theme.label}</strong>
              {isActive ? <Badge tone="default">выбрано</Badge> : null}
            </span>
            <span className="muted">{theme.description}</span>
          </button>
        );
      })}
    </div>
  );
}
