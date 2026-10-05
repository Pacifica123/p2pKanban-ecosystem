import { useAppearance } from '@/app/providers/AppearanceProvider';
import { BOARD_THEME_PRESETS, getBoardPresetPreview } from '@/shared/appearance/theme';
import { Badge } from '@/shared/ui/Badge';

interface PresetPickerProps {
  value: string;
  onChange: (next: string) => void;
}

export function PresetPicker({ value, onChange }: PresetPickerProps) {
  const { resolvedTheme } = useAppearance();

  return (
    <div className="preset-grid">
      {BOARD_THEME_PRESETS.map((preset) => {
        const isActive = preset.id === value;
        return (
          <button
            key={preset.id}
            type="button"
            className={`preset-card ${isActive ? 'is-active' : ''}`}
            onClick={() => onChange(preset.id)}
          >
            <span className="preset-card__swatch" style={{ background: getBoardPresetPreview(preset.id, resolvedTheme) }} />
            <span className="preset-card__title-row">
              <strong>{preset.label}</strong>
              {isActive ? <Badge tone="default">выбрано</Badge> : null}
            </span>
            <span className="muted">{preset.description}</span>
          </button>
        );
      })}
    </div>
  );
}
