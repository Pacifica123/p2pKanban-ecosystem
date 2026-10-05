import type { CardPriority } from '@/shared/types/api';
import { priorityRank } from '@/shared/lib/cardOrder';
const levels = ['low', 'medium', 'high', 'urgent'] as const,
  labels = ['Низкий', 'Средний', 'Высокий', 'Срочный'];
export function PriorityStars({
  value,
  onChange,
  disabled = false,
}: {
  value: CardPriority;
  onChange?: (v: CardPriority) => void;
  disabled?: boolean;
}) {
  const rank = priorityRank[value || ''] || 0;
  if (!onChange)
    return (
      <span
        className="priority-stars"
        role="img"
        aria-label={`Приоритет: ${rank} из 4`}
      >
        {'★'.repeat(rank)}
        {'☆'.repeat(4 - rank)}
      </span>
    );
  return (
    <div className="toolbar" role="group" aria-label="Приоритет">
      <span>Приоритет</span>
      {levels.map((v, i) => (
        <button
          key={v}
          type="button"
          className="priority-stars"
          disabled={disabled}
          aria-label={`${labels[i]}, ${i + 1} из 4`}
          aria-pressed={value === v}
          onClick={() => onChange(value === v ? null : v)}
        >
          {i < rank ? '★' : '☆'}
        </button>
      ))}
      <button
        type="button"
        disabled={disabled || !value}
        onClick={() => onChange(null)}
      >
        Без приоритета
      </button>
    </div>
  );
}
