import { useMemo } from 'react';
import { useBoardProductivityQuery } from '@/features/activity/hooks/useActivity';

function currentStreak(days: Array<{ actionCount: number }>) {
  let streak = 0;
  for (let index = days.length - 1; index >= 0; index -= 1) {
    if (days[index].actionCount <= 0) break;
    streak += 1;
  }
  return streak;
}

function intensity(count: number, maximum: number) {
  if (!count || !maximum) return 0;
  return Math.max(1, Math.min(4, Math.ceil((count / maximum) * 4)));
}

export function ProductivityGraph({ boardId }: { boardId: string }) {
  const query = useBoardProductivityQuery(boardId);
  const graph = useMemo(() => {
    const days = query.data?.days || [];
    const maximum = Math.max(0, ...days.map((day) => day.actionCount));
    const firstDate = days[0]
      ? new Date(`${days[0].date}T00:00:00Z`)
      : null;
    const mondayOffset = firstDate ? (firstDate.getUTCDay() + 6) % 7 : 0;
    return {
      cells: [
        ...Array.from({ length: mondayOffset }, () => null),
        ...days,
      ],
      activeDays: days.filter((day) => day.actionCount > 0).length,
      streak: currentStreak(days),
      maximum,
    };
  }, [query.data]);

  return (
    <details className="productivity-panel" open>
      <summary>
        <span>
          <strong>Продуктивность доски</strong>
          <span className="muted">84 дня · одно действие = изменение канбана</span>
        </span>
        {query.data ? (
          <span className="productivity-panel__total">
            {query.data.totalActions} действий
          </span>
        ) : null}
      </summary>
      {query.isLoading ? (
        <p className="muted">Считаем изменения…</p>
      ) : query.isError ? (
        <p className="muted">Статистика временно недоступна.</p>
      ) : (
        <>
          <div className="productivity-grid" aria-label="Сетка продуктивности за 84 дня">
            {graph.cells.map((day, index) => day ? (
              <span
                key={day.date}
                className={`productivity-cell productivity-cell--${intensity(day.actionCount, graph.maximum)}`}
                title={`${day.date}: ${day.actionCount} действий`}
                aria-label={`${day.date}: ${day.actionCount} действий`}
              />
            ) : <span key={`empty-${index}`} className="productivity-cell productivity-cell--empty" />)}
          </div>
          <div className="productivity-panel__facts">
            <span><strong>{graph.activeDays}</strong> активных дней</span>
            <span><strong>{graph.streak}</strong> дней подряд сейчас</span>
          </div>
        </>
      )}
    </details>
  );
}
