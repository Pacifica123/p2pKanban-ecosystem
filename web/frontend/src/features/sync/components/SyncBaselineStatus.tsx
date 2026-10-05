import type { SyncBaselineRuntime } from '@/features/sync/hooks/useSyncBaseline';
import { Button } from '@/shared/ui/Button';
import { Icon } from '@/shared/ui/Icon';

interface SyncBaselineStatusProps {
  runtime: SyncBaselineRuntime;
}

function friendlyError(error: string | null) {
  const normalized = (error || '').toLowerCase();
  if (normalized.includes('too many requests') || normalized.includes('429')) {
    return 'Сервер получил слишком много запросов. Подождите немного и повторите.';
  }
  if (normalized.includes('network') || normalized.includes('fetch')) {
    return 'Сервер временно недоступен. Локальные изменения не потеряны.';
  }
  return 'Не удалось связаться с сервером. Локальные изменения не потеряны.';
}

export function SyncBaselineStatus({ runtime }: SyncBaselineStatusProps) {
  if (runtime.state === 'idle' || runtime.state === 'ready') return null;

  if (runtime.state === 'offline') {
    return (
      <div className="sync-notice" data-testid="sync-baseline-status">
        <span className="sync-notice__dot" />
        <span>Нет сети. Можно продолжать работу — изменения сохраняются локально.</span>
      </div>
    );
  }

  if (runtime.state === 'registering' || runtime.state === 'pulling') {
    return (
      <div className="sync-notice sync-notice--progress" data-testid="sync-baseline-status">
        <span className="sync-notice__spinner" />
        <span>{runtime.state === 'registering' ? 'Подключаем устройство…' : 'Синхронизируем изменения…'}</span>
      </div>
    );
  }

  return (
    <div className="inline-banner inline-banner--error sync-baseline-banner" data-testid="sync-baseline-status">
      <div>
        <strong>Синхронизация приостановлена</strong>
        <span>{friendlyError(runtime.lastError)}</span>
        {runtime.lastError ? (
          <details className="technical-details">
            <summary>Техническая причина</summary>
            <code>{runtime.lastError}</code>
          </details>
        ) : null}
      </div>
      <Button variant="ghost" onClick={() => void runtime.pullWorkspace()} disabled={!runtime.replica?.id}>
        <Icon name="refresh" size={16} />
        Повторить
      </Button>
    </div>
  );
}
