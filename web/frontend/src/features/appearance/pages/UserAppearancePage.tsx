import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/shared/ui/Button';
import { ErrorState } from '@/shared/ui/ErrorState';
import { LoadingState } from '@/shared/ui/LoadingState';
import { Panel } from '@/shared/ui/Panel';
import { SelectField } from '@/shared/ui/Field';
import { Badge } from '@/shared/ui/Badge';
import { AppAppearancePreview } from '@/features/appearance/components/AppearancePreview';
import { useMyAppearanceQuery, useUpdateMyAppearanceMutation } from '@/features/appearance/hooks/useAppearance';
import { useAppearance } from '@/app/providers/AppearanceProvider';
import type { Density, UserAppearancePreferences } from '@/shared/types/api';
import { Icon } from '@/shared/ui/Icon';

export function UserAppearancePage() {
  const myAppearanceQuery = useMyAppearanceQuery();
  const updateAppearanceMutation = useUpdateMyAppearanceMutation();
  const { persistedUserAppearance, effectiveUserAppearance, setUserPreview, clearUserPreview } = useAppearance();
  const [draft, setDraft] = useState<UserAppearancePreferences | null>(null);

  useEffect(() => {
    if (!myAppearanceQuery.data) return;
    setDraft(myAppearanceQuery.data);
  }, [myAppearanceQuery.data]);

  useEffect(() => {
    if (draft) {
      setUserPreview({
        appTheme: draft.appTheme,
        density: draft.density,
        reduceMotion: draft.reduceMotion,
        checklistItemSubmitMode: draft.checklistItemSubmitMode,
        cardDetailsMode: draft.cardDetailsMode,
      });
    }
    return () => clearUserPreview();
  }, [clearUserPreview, draft, setUserPreview]);

  const hasUnsavedChanges = useMemo(() => {
    if (!draft || !persistedUserAppearance) return false;
    return draft.appTheme !== persistedUserAppearance.appTheme
      || draft.density !== persistedUserAppearance.density
      || draft.reduceMotion !== persistedUserAppearance.reduceMotion
      || draft.checklistItemSubmitMode !== persistedUserAppearance.checklistItemSubmitMode
      || draft.cardDetailsMode !== persistedUserAppearance.cardDetailsMode;
  }, [draft, persistedUserAppearance]);

  if (myAppearanceQuery.isLoading || !draft || !effectiveUserAppearance) {
    return <LoadingState label="Загружаем оформление…" />;
  }

  if (myAppearanceQuery.isError) {
    return <ErrorState title="Не удалось загрузить оформление" onRetry={() => void myAppearanceQuery.refetch()} />;
  }

  const currentDraft = draft;

  async function handleSave() {
    await updateAppearanceMutation.mutateAsync({
      appTheme: currentDraft.appTheme,
      density: currentDraft.density,
      reduceMotion: currentDraft.reduceMotion,
      checklistItemSubmitMode: currentDraft.checklistItemSubmitMode,
      cardDetailsMode: currentDraft.cardDetailsMode,
    });
    clearUserPreview();
  }

  function resetDraft() {
    if (!persistedUserAppearance) return;
    setDraft(persistedUserAppearance);
    clearUserPreview();
  }

  return (
    <div className="page-shell">
      <section className="page-header">
        <div>
          <h2>Вид приложения</h2>
          <p className="muted">Эти настройки видны только вам и не меняют чужой интерфейс.</p>
        </div>
        <div className="page-header__actions">
          <Badge tone={hasUnsavedChanges ? 'warning' : 'done'}>{hasUnsavedChanges ? 'есть изменения' : 'сохранено'}</Badge>
          <Button iconOnly onClick={resetDraft} disabled={!hasUnsavedChanges} title="Сбросить изменения" aria-label="Сбросить изменения"><Icon name="refresh" /></Button>
          <Button variant="primary" onClick={() => void handleSave()} disabled={updateAppearanceMutation.isPending || !hasUnsavedChanges}>
            {updateAppearanceMutation.isPending ? 'Сохраняем…' : <><Icon name="save" size={16} /> Сохранить</>}
          </Button>
        </div>
      </section>

      <div className="customization-layout customization-layout--two-columns">
        <div className="grid">
          <Panel title="Интерфейс" description="Тема, плотность элементов и анимация.">
            <div className="grid customization-form-grid">
              <SelectField label="Тема" value={currentDraft.appTheme} onChange={(event) => setDraft({ ...currentDraft, appTheme: event.target.value as UserAppearancePreferences['appTheme'] })}>
                <option value="system">Как в системе</option>
                <option value="light">Светлая</option>
                <option value="dark">Тёмная</option>
              </SelectField>
              <SelectField label="Плотность" value={currentDraft.density} onChange={(event) => setDraft({ ...currentDraft, density: event.target.value as Density })}>
                <option value="comfortable">Свободная</option>
                <option value="compact">Компактная</option>
              </SelectField>
            </div>

            <div className="setting-row-list">
              <label className="toggle-row">
                <span>
                  <strong>Меньше анимации</strong>
                  <span className="muted">Убирает плавные переходы и вращение индикаторов.</span>
                </span>
                <input type="checkbox" checked={currentDraft.reduceMotion} onChange={(event) => setDraft({ ...currentDraft, reduceMotion: event.target.checked })} />
              </label>
            </div>
          </Panel>

          <Panel title="Работа с карточками" description="Персональные привычки ввода и открытия карточки.">
            <div className="grid customization-form-grid">
              <SelectField
                label="Добавление пункта чек-листа"
                value={currentDraft.checklistItemSubmitMode}
                onChange={(event) => setDraft({
                  ...currentDraft,
                  checklistItemSubmitMode: event.target.value as UserAppearancePreferences['checklistItemSubmitMode'],
                })}
              >
                <option value="ctrl_enter">Ctrl+Enter</option>
                <option value="enter">Enter</option>
                <option value="button">Только кнопка «+»</option>
              </SelectField>
              <SelectField
                label="Раскрытие карточки"
                value={currentDraft.cardDetailsMode}
                onChange={(event) => setDraft({
                  ...currentDraft,
                  cardDetailsMode: event.target.value as UserAppearancePreferences['cardDetailsMode'],
                })}
              >
                <option value="drawer">Сбоку</option>
                <option value="modal">По центру</option>
              </SelectField>
            </div>
          </Panel>

          <Panel title="Как это работает">
            <ul className="rules-list">
              <li>Изменения сразу показываются в этой вкладке.</li>
              <li>Кнопка «Сохранить» переносит их на сервер.</li>
              <li>Режимы карточки и чек-листа действуют на всех ваших досках.</li>
              <li>Сброс возвращает последнее сохранённое состояние.</li>
            </ul>
          </Panel>
        </div>

        <AppAppearancePreview appearance={effectiveUserAppearance} />
      </div>
    </div>
  );
}
