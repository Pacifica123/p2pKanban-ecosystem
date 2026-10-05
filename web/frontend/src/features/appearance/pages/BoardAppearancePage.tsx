import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { LoadingState } from '@/shared/ui/LoadingState';
import { Panel } from '@/shared/ui/Panel';
import { SelectField, TextField } from '@/shared/ui/Field';
import { Badge } from '@/shared/ui/Badge';
import { BoardAppearancePreview } from '@/features/appearance/components/AppearancePreview';
import { PresetPicker } from '@/features/appearance/components/PresetPicker';
import { useBoardAppearanceQuery, useUpdateBoardAppearanceMutation } from '@/features/appearance/hooks/useAppearance';
import { paths } from '@/app/router/paths';
import type { BoardAppearanceSettings, Density } from '@/shared/types/api';
import { Icon } from '@/shared/ui/Icon';
import { getBoardAccentColor } from '@/shared/appearance/theme';

const presetWallpaperOptions = ['aurora', 'blueprint', 'canopy', 'sunrise', 'nebula'];

export function BoardAppearancePage() {
  const { workspaceId, boardId } = useParams();
  const boardAppearanceQuery = useBoardAppearanceQuery(boardId);
  const updateBoardAppearanceMutation = useUpdateBoardAppearanceMutation(boardId);
  const [draft, setDraft] = useState<BoardAppearanceSettings | null>(null);

  useEffect(() => {
    if (!boardAppearanceQuery.data) return;
    setDraft(boardAppearanceQuery.data);
  }, [boardAppearanceQuery.data]);

  const hasUnsavedChanges = useMemo(() => JSON.stringify(draft) !== JSON.stringify(boardAppearanceQuery.data), [draft, boardAppearanceQuery.data]);

  if (!workspaceId || !boardId) {
    return <ErrorState title="Не удалось открыть оформление доски" />;
  }

  if (boardAppearanceQuery.isLoading || !draft) {
    return <LoadingState label="Загружаем оформление доски…" />;
  }

  if (boardAppearanceQuery.isError) {
    return <ErrorState title="Не удалось загрузить оформление доски" onRetry={() => void boardAppearanceQuery.refetch()} />;
  }

  const currentDraft = draft;
  const customAccentColor = getBoardAccentColor(currentDraft);

  function setCustomAccentColor(value: string | null) {
    const customProperties = { ...currentDraft.customProperties };
    if (value) customProperties.accentColor = value;
    else delete customProperties.accentColor;
    setDraft({ ...currentDraft, customProperties });
  }

  function changeWallpaperKind(kind: BoardAppearanceSettings['wallpaper']['kind']) {
    if (kind === 'none' || kind === 'accent') {
      setDraft({ ...currentDraft, wallpaper: { kind, value: null } });
      return;
    }
    if (kind === 'preset') {
      setDraft({ ...currentDraft, wallpaper: { kind, value: 'aurora' } });
      return;
    }
    if (kind === 'solid') {
      setDraft({ ...currentDraft, wallpaper: { kind, value: '#0f172a' } });
      return;
    }
    if (kind === 'gradient') {
      setDraft({
        ...currentDraft,
        wallpaper: { kind, value: 'linear-gradient(135deg, #1e293b, #0f172a)' },
      });
      return;
    }
    setDraft({ ...currentDraft, wallpaper: { kind, value: '' } });
  }

  async function handleSave() {
    await updateBoardAppearanceMutation.mutateAsync({
      themePreset: currentDraft.themePreset,
      wallpaper: currentDraft.wallpaper,
      columnDensity: currentDraft.columnDensity,
      cardPreviewMode: currentDraft.cardPreviewMode,
      showCardDescription: currentDraft.showCardDescription,
      showCardDates: currentDraft.showCardDates,
      showChecklistProgress: currentDraft.showChecklistProgress,
      customProperties: currentDraft.customProperties,
    });
  }

  function resetDraft() {
    if (!boardAppearanceQuery.data) return;
    setDraft(boardAppearanceQuery.data);
  }

  return (
    <div className="page-shell">
      <section className="page-header">
        <div>
          <h2>Вид доски</h2>
          <p className="muted">Общие настройки этой доски — их увидят все участники.</p>
        </div>
        <div className="page-header__actions">
          <Badge tone={hasUnsavedChanges ? 'warning' : 'done'}>{hasUnsavedChanges ? 'есть изменения' : 'сохранено'}</Badge>
          <Button iconOnly onClick={resetDraft} disabled={!hasUnsavedChanges} title="Сбросить изменения" aria-label="Сбросить изменения"><Icon name="refresh" /></Button>
          <Button variant="primary" onClick={() => void handleSave()} disabled={updateBoardAppearanceMutation.isPending || !hasUnsavedChanges}>
            {updateBoardAppearanceMutation.isPending ? 'Сохраняем…' : <><Icon name="save" size={16} /> Сохранить</>}
          </Button>
          <Link className="button" to={paths.board(workspaceId, boardId)}><Icon name="back" size={16} /> К доске</Link>
        </div>
      </section>

      <div className="customization-layout customization-layout--two-columns">
        <div className="grid">
          <Panel title="Цветовая схема" description="Готовая палитра для фона, колонок и карточек.">
            <PresetPicker value={currentDraft.themePreset} onChange={(next) => setDraft({ ...currentDraft, themePreset: next })} />
          </Panel>

          <Panel title="Акцентный цвет" description="Один цвет для колонок, карточек, прогресса и активных элементов.">
            <div className="grid customization-form-grid">
              <SelectField
                label="Источник акцента"
                value={customAccentColor ? 'custom' : 'preset'}
                onChange={(event) => setCustomAccentColor(event.target.value === 'custom' ? '#60a5fa' : null)}
              >
                <option value="preset">Из цветовой схемы</option>
                <option value="custom">Свой цвет</option>
              </SelectField>
              {customAccentColor ? (
                <TextField
                  label="Цвет"
                  type="color"
                  value={customAccentColor}
                  onChange={(event) => setCustomAccentColor(event.target.value)}
                />
              ) : null}
            </div>
            <p className="muted accent-color-note">
              В тёмной теме карточка становится темнее колонки, в светлой — светлее. Wallpaper при смене акцента сохраняется.
            </p>
          </Panel>

          <Panel title="Фон" description="Готовый фон, цвет, градиент или изображение по ссылке.">
            <div className="grid customization-form-grid">
              <SelectField
                label="Тип фона"
                value={currentDraft.wallpaper.kind}
                onChange={(event) => changeWallpaperKind(event.target.value as BoardAppearanceSettings['wallpaper']['kind'])}
              >
                <option value="none">По схеме</option>
                <option value="accent">От акцента</option>
                <option value="solid">Цвет</option>
                <option value="gradient">Градиент</option>
                <option value="preset">Готовый фон</option>
                <option value="image">Изображение по URL</option>
              </SelectField>

              {currentDraft.wallpaper.kind === 'preset' ? (
                <SelectField label="Готовый фон" value={currentDraft.wallpaper.value || 'aurora'} onChange={(event) => setDraft({ ...currentDraft, wallpaper: { kind: 'preset', value: event.target.value } })}>
                  {presetWallpaperOptions.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </SelectField>
              ) : currentDraft.wallpaper.kind !== 'none' && currentDraft.wallpaper.kind !== 'accent' ? (
                <TextField
                  label={currentDraft.wallpaper.kind === 'solid'
                    ? 'CSS-цвет'
                    : currentDraft.wallpaper.kind === 'image'
                      ? 'Ссылка на изображение'
                      : 'CSS-градиент'}
                  value={currentDraft.wallpaper.value || ''}
                  onChange={(event) => setDraft({ ...currentDraft, wallpaper: { kind: currentDraft.wallpaper.kind, value: event.target.value } })}
                  placeholder={currentDraft.wallpaper.kind === 'solid'
                    ? '#0f172a'
                    : currentDraft.wallpaper.kind === 'image'
                      ? 'https://example.org/wallpaper.jpg'
                      : 'linear-gradient(135deg, #1e293b, #0f172a)'}
                />
              ) : null}
            </div>
          </Panel>

          <Panel title="Отображение карточек">
            <div className="grid customization-form-grid">
              <SelectField label="Плотность колонок" value={currentDraft.columnDensity} onChange={(event) => setDraft({ ...currentDraft, columnDensity: event.target.value as Density })}>
                <option value="comfortable">Свободная</option>
                <option value="compact">Компактная</option>
              </SelectField>
              <SelectField label="Вид карточек" value={currentDraft.cardPreviewMode} onChange={(event) => setDraft({ ...currentDraft, cardPreviewMode: event.target.value as BoardAppearanceSettings['cardPreviewMode'] })}>
                <option value="compact">Компактный</option>
                <option value="expanded">Расширенный</option>
              </SelectField>
            </div>
            <div className="setting-row-list">
              <label className="toggle-row">
                <span>
                  <strong>Показывать описание</strong>
                </span>
                <input type="checkbox" checked={currentDraft.showCardDescription} onChange={(event) => setDraft({ ...currentDraft, showCardDescription: event.target.checked })} />
              </label>
              <label className="toggle-row">
                <span>
                  <strong>Показывать даты</strong>
                </span>
                <input type="checkbox" checked={currentDraft.showCardDates} onChange={(event) => setDraft({ ...currentDraft, showCardDates: event.target.checked })} />
              </label>
              <label className="toggle-row">
                <span>
                  <strong>Показывать прогресс чек-листа</strong>
                </span>
                <input type="checkbox" checked={currentDraft.showChecklistProgress} onChange={(event) => setDraft({ ...currentDraft, showChecklistProgress: event.target.checked })} />
              </label>
            </div>
          </Panel>
        </div>

        <BoardAppearancePreview appearance={currentDraft} />
      </div>
    </div>
  );
}
