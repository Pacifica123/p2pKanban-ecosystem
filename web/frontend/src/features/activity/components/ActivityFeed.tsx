import type { ActivityEntry } from '@/shared/types/api';
import { formatDateTime } from '@/shared/lib/date';
import { EmptyState } from '@/shared/ui/EmptyState';
import { activityLabel, changedFieldsLabel } from '@/shared/lib/russian';

interface ActivityFeedProps {
  items: ActivityEntry[];
  emptyTitle?: string;
}

export function ActivityFeed({ items, emptyTitle = 'Пока нет событий' }: ActivityFeedProps) {
  if (!items.length) {
    return <EmptyState title={emptyTitle} compact description="Изменения появятся здесь автоматически." />;
  }

  return (
    <div className="activity-list">
      {items.map((item) => {
        const hasTechnicalDetails = Object.keys(item.payload || {}).length > 0;
        const changedFields = changedFieldsLabel(item.fieldMask);
        return (
          <article key={item.id} className="activity-item">
            <div className="activity-item__header">
              <strong>{activityLabel(item.kind)}</strong>
              <time className="muted">{formatDateTime(item.createdAt)}</time>
            </div>
            <p className="activity-item__actor">
              {item.actor.displayName || item.actor.userId || 'Система'}
              {changedFields ? ` · изменено: ${changedFields}` : ''}
            </p>
            {hasTechnicalDetails ? (
              <details className="activity-item__details">
                <summary>Технические детали</summary>
                <pre className="code-block">{JSON.stringify(item.payload, null, 2)}</pre>
              </details>
            ) : null}
          </article>
        );
      })}
    </div>
  );
}
