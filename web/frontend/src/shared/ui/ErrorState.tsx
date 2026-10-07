import { Button } from '@/shared/ui/Button';
import { Icon } from '@/shared/ui/Icon';
import { ErrorDetails } from '@/shared/ui/ErrorDetails';

interface ErrorStateProps {
  title: string;
  description?: string;
  compact?: boolean;
  onRetry?: () => void;
  /** The error behind it; without one the report takes the last failed request. */
  error?: unknown;
  operation?: string;
}

export function ErrorState({ title, description, compact = false, onRetry, error, operation }: ErrorStateProps) {
  return (
    <div className={`error-state ${compact ? 'error-state--compact' : ''}`} data-testid="error-state">
      <strong>{title}</strong>
      {description ? <p className="muted">{description}</p> : null}
      {onRetry ? <Button iconOnly onClick={onRetry} title="Повторить" aria-label="Повторить"><Icon name="refresh" size={16} /></Button> : null}
      <ErrorDetails message={description ? `${title}. ${description}` : title} error={error} operation={operation} />
    </div>
  );
}
