// Runs the steps of the «Проверка приёмки» button one after another.
// A step that throws is a FAIL with the error text; a step whose prerequisite
// did not pass is a SKIP that names it, so one broken thing does not hide the rest.
import { ApiError } from '@/shared/api/errors';
import type { StepResult, StepStatus } from './report';

export interface StepOutcome {
  status: StepStatus;
  detail?: string;
}

export interface StepDefinition<Ctx> {
  id: string;
  phase: string;
  title: string;
  covers?: string[];
  /** Ids of steps that must have passed (PASS, WARN or INFO) before this one runs. */
  needs?: string[];
  run: (ctx: Ctx) => Promise<StepOutcome | string | void>;
}

export const pass = (detail = ''): StepOutcome => ({ status: 'PASS', detail });
export const warn = (detail: string): StepOutcome => ({ status: 'WARN', detail });
export const fail = (detail: string): StepOutcome => ({ status: 'FAIL', detail });
export const info = (detail: string): StepOutcome => ({ status: 'INFO', detail });
export const skip = (detail: string): StepOutcome => ({ status: 'SKIP', detail });

/** An assertion inside a step: throws, and the runner turns it into FAIL. */
export function expectThat(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const http = error.http ? `${error.http.method} ${error.http.path} → ${error.status || 'нет ответа'}` : `HTTP ${error.status}`;
    return `${error.message} (${http}${error.code ? `, ${error.code}` : ''})`;
  }
  return error instanceof Error ? error.message : String(error);
}

const OK: StepStatus[] = ['PASS', 'WARN', 'INFO'];

export async function runSteps<Ctx>(
  steps: StepDefinition<Ctx>[],
  ctx: Ctx,
  options: { onStep?: (result: StepResult, index: number) => void; signal?: AbortSignal; now?: () => number } = {},
): Promise<StepResult[]> {
  const now = options.now ?? (() => Date.now());
  const results: StepResult[] = [];
  const statusOf = new Map<string, StepStatus>();
  for (const [index, step] of steps.entries()) {
    const started = now();
    let outcome: StepOutcome;
    const blocked = (step.needs ?? []).find((id) => !OK.includes(statusOf.get(id) ?? 'SKIP'));
    if (options.signal?.aborted) {
      outcome = skip('проверка остановлена');
    } else if (blocked) {
      const title = steps.find((candidate) => candidate.id === blocked)?.title ?? blocked;
      outcome = skip(`не выполнено: не прошёл шаг «${title}»`);
    } else {
      try {
        const value = await step.run(ctx);
        outcome = typeof value === 'string' ? pass(value) : value ?? pass();
      } catch (error) {
        outcome = fail(describeError(error));
      }
    }
    const result: StepResult = {
      id: step.id,
      phase: step.phase,
      title: step.title,
      status: outcome.status,
      covers: step.covers ?? [],
      detail: outcome.detail ?? '',
      ms: Math.max(0, Math.round(now() - started)),
    };
    statusOf.set(step.id, result.status);
    results.push(result);
    options.onStep?.(result, index);
  }
  return results;
}
