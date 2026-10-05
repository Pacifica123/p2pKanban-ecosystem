import { useCallback, useEffect, useRef, useState } from 'react';
import {
  checkForSourceUpdate,
  getUpdateControlState,
  isLocalUpdateSurface,
  startSourceUpdate,
  revisionsMatch,
  type UpdateControlState,
} from '@/features/system/api/updateControl';
import { Button } from '@/shared/ui/Button';

const DISMISSED_COMMIT_KEY = 'p2pkanban:update-dismissed-commit';
const ACKNOWLEDGED_JOB_KEY = 'p2pkanban:update-acknowledged-job';
const CHECK_INTERVAL_MS = 10 * 60_000;
const JOB_POLL_MS = 1_000;

function firstCommitLine(message: string) {
  return message.split(/\r?\n/, 1)[0]?.trim() || 'Новый commit в main';
}

export function SourceUpdateSurface() {
  const [state, setState] = useState<UpdateControlState | null>(null);
  const [dismissedSha, setDismissedSha] = useState(
    () => window.localStorage.getItem(DISMISSED_COMMIT_KEY),
  );
  const [acknowledgedJobId, setAcknowledgedJobId] = useState(
    () => window.localStorage.getItem(ACKNOWLEDGED_JOB_KEY),
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const checkingRef = useRef(false);
  const localSurface = isLocalUpdateSurface();

  const refresh = useCallback(async (checkRemote = false) => {
    if (!localSurface || checkingRef.current) return;
    checkingRef.current = true;
    try {
      const current = await getUpdateControlState();
      const next = checkRemote && current.available && current.sessionToken
        ? await checkForSourceUpdate(current.sessionToken)
        : current;
      setState(next);
      setActionError(null);
    } catch {
      setState(null);
    } finally {
      checkingRef.current = false;
    }
  }, [localSurface]);

  useEffect(() => {
    if (!localSurface) return undefined;
    void refresh(true);
    const remoteInterval = window.setInterval(() => void refresh(true), CHECK_INTERVAL_MS);
    const visible = () => {
      if (document.visibilityState === 'visible') void refresh(true);
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      window.clearInterval(remoteInterval);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [localSurface, refresh]);

  const jobActive = state?.job.status === 'queued' || state?.job.status === 'running';
  useEffect(() => {
    if (!jobActive) return undefined;
    const poll = window.setInterval(() => void refresh(false), JOB_POLL_MS);
    return () => window.clearInterval(poll);
  }, [jobActive, refresh]);

  if (!state) return null;

  const latest = state.latest;
  const updateAvailable = Boolean(
    latest
    && !revisionsMatch(latest.sha, state.installedRevision)
    && latest.sha !== dismissedSha,
  );
  const jobFinished = state.job.status === 'succeeded' || state.job.status === 'failed';
  const showOverlay = jobActive || (jobFinished && state.job.id !== acknowledgedJobId);

  async function startUpdate() {
    if (!latest) return;
    setActionError(null);
    if (!state?.available || !state.sessionToken) {
      setActionError(
        'Commit найден напрямую в GitHub, но локальный установщик после перезапуска компьютера не запущен. Выполните `python bootstrap.py watch-updates`; контейнеры и данные затронуты не будут.',
      );
      return;
    }
    try {
      const next = await startSourceUpdate(state.sessionToken, latest.sha);
      setState(next);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Не удалось запустить обновление.');
    }
  }

  function dismiss() {
    if (!latest) return;
    window.localStorage.setItem(DISMISSED_COMMIT_KEY, latest.sha);
    setDismissedSha(latest.sha);
  }

  function acknowledgeAndReload() {
    window.localStorage.setItem(ACKNOWLEDGED_JOB_KEY, state!.job.id);
    setAcknowledgedJobId(state!.job.id);
    window.location.reload();
  }

  return (
    <>
      {updateAvailable && !showOverlay ? (
        <aside className="source-update-banner" role="status">
          <div className="source-update-banner__copy">
            <strong>В `main` появился новый commit</strong>
            <span>{firstCommitLine(latest!.message)}</span>
            <a href={latest!.url} target="_blank" rel="noreferrer">
              {latest!.shortSha}{latest!.committedAt ? ` · ${new Date(latest!.committedAt).toLocaleString()}` : ''}
            </a>
          </div>
          <div className="inline-actions">
            <Button type="button" variant="ghost" onClick={dismiss}>До следующего commit</Button>
            <Button type="button" variant="primary" onClick={() => void startUpdate()}>Обновить</Button>
          </div>
          {actionError ? <p className="form-error" role="alert">{actionError}</p> : null}
        </aside>
      ) : null}

      {showOverlay ? (
        <div className="source-update-overlay" role="dialog" aria-modal="true" aria-labelledby="source-update-title">
          <section className="source-update-card">
            <div>
              <p className="source-update-card__eyebrow">Локальное обновление</p>
              <h2 id="source-update-title">
                {state.job.status === 'succeeded'
                  ? 'Новая версия готова'
                  : state.job.status === 'failed'
                    ? 'Обновление остановлено'
                    : 'Обновляем p2pKanban'}
              </h2>
              <p className="muted">{state.job.message}</p>
            </div>
            <div className="source-update-progress" aria-label={`Прогресс: ${state.job.progress}%`}>
              <span style={{ width: `${state.job.progress}%` }} />
            </div>
            <div className="source-update-card__facts">
              <span>{state.job.phase}</span>
              <strong>{state.job.progress}%</strong>
            </div>
            {state.job.error ? <p className="form-error" role="alert">{state.job.error}</p> : null}
            {state.job.status === 'succeeded' ? (
              <Button
                type="button"
                variant="primary"
                disabled={!state.job.verified}
                onClick={acknowledgeAndReload}
              >
                Перезапустить интерфейс
              </Button>
            ) : null}
            {state.job.status === 'failed' ? (
              <div className="inline-actions">
                <Button type="button" onClick={() => void refresh(true)}>Проверить состояние</Button>
                <Button type="button" variant="ghost" onClick={acknowledgeAndReload}>Вернуться</Button>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </>
  );
}
