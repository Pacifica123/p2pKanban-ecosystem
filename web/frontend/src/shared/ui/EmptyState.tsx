import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  description?: string;
  compact?: boolean;
  action?: ReactNode;
}

export function EmptyState({ title, description, compact = false, action }: EmptyStateProps) {
  return (
    <div className={`empty-state ${compact ? 'empty-state--compact' : ''}`}>
      <strong>{title}</strong>
      {description ? <p className="muted">{description}</p> : null}
      {action}
    </div>
  );
}
