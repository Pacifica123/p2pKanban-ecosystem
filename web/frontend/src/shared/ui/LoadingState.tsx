interface LoadingStateProps {
  label?: string;
  compact?: boolean;
}

export function LoadingState({ label = 'Загрузка…', compact = false }: LoadingStateProps) {
  return <div className={`loading-state ${compact ? 'loading-state--compact' : ''}`} data-testid="loading-state">{label}</div>;
}
