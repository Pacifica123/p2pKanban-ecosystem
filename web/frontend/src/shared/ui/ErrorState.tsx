import { Button } from '@/shared/ui/Button';
import { Icon } from '@/shared/ui/Icon';

interface ErrorStateProps {
  title: string;
  description?: string;
  compact?: boolean;
  onRetry?: () => void;
}

export function ErrorState({ title, description, compact = false, onRetry }: ErrorStateProps) {
  return (
    <div className={`error-state ${compact ? 'error-state--compact' : ''}`} data-testid="error-state">
      <strong>{title}</strong>
      {description ? <p className="muted">{description}</p> : null}
      {onRetry ? <Button iconOnly onClick={onRetry} title="Повторить" aria-label="Повторить"><Icon name="refresh" size={16} /></Button> : null}
    </div>
  );
}
