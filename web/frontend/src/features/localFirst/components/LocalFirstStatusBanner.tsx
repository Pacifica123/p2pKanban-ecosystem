import type { LocalFirstBoardRuntime } from '@/features/localFirst/types';
import { Button } from '@/shared/ui/Button';
import { Icon } from '@/shared/ui/Icon';
import { formatCountRu } from '@/shared/lib/russian';

interface LocalFirstStatusBannerProps {
  runtime: LocalFirstBoardRuntime;
}

export function LocalFirstStatusBanner({ runtime }: LocalFirstStatusBannerProps) {
  const hasPending = runtime.pendingCount > 0;
  const hasFailed = runtime.failedCount > 0;
  const isOffline = !runtime.isOnline;

  if (!isOffline && !hasPending && !hasFailed && !runtime.isFlushing) return null;

  if (!hasFailed) {
    let label = 'Изменения сохранены';
    if (isOffline) label = 'Работаем без сети — изменения сохранены на устройстве';
    else if (runtime.isFlushing) label = 'Синхронизируем изменения…';
    else if (hasPending) label = `Сохранено локально: ${formatCountRu(runtime.pendingCount, 'изменение', 'изменения', 'изменений')}`;

    return (
      <div className={`sync-notice ${runtime.isFlushing ? 'sync-notice--progress' : ''}`} data-testid="local-first-status">
        {runtime.isFlushing ? <span className="sync-notice__spinner" /> : <Icon name="check" size={16} />}
        <span>{label}</span>
        {hasPending && !runtime.isFlushing && runtime.isOnline ? (
          <Button variant="ghost" onClick={() => void runtime.flushPendingOperations()}>
            Отправить сейчас
          </Button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="inline-banner inline-banner--error local-first-banner" data-testid="local-first-status">
      <div>
        <strong>Часть изменений пока не синхронизирована</strong>
        <span>Они остаются на этом устройстве и не потеряны.</span>
        {runtime.lastError ? (
          <details className="technical-details">
            <summary>Техническая причина</summary>
            <code>{runtime.lastError}</code>
          </details>
        ) : null}
      </div>
      <Button variant="primary" onClick={() => void runtime.retryFailedOperations()} disabled={runtime.isFlushing || !runtime.isOnline}>
        <Icon name="refresh" size={16} />
        Повторить
      </Button>
    </div>
  );
}
