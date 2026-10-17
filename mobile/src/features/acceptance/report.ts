// p2p-kanban-acceptance-report/1 (docs/ecosystem/self-acceptance.md): the
// report of the «Проверка приёмки» button, byte for byte the form web writes.
// Markdown for a person first, then the marker and canonical JSON for a
// machine — the same shape as error-report/1.
import { canonical, redact, truncate, type NodeIdentity, type Software } from '../../shared/errorReport/report';

export const ACCEPTANCE_REPORT = 'p2p-kanban-acceptance-report/1';
export const MAX_DETAIL = 1500;

export type StepStatus = 'PASS' | 'WARN' | 'FAIL' | 'SKIP' | 'INFO';
export const STATUSES: StepStatus[] = ['PASS', 'WARN', 'FAIL', 'SKIP', 'INFO'];

export interface StepResult {
  id: string;
  phase: string;
  title: string;
  status: StepStatus;
  covers: string[];
  detail: string;
  ms: number;
}

export interface AcceptanceReport {
  protocol: string;
  runId: string;
  startedAt: string;
  finishedAt: string;
  software: Software;
  platform: string | null;
  node: null | ({ origin: string | null } & NodeIdentity);
  steps: StepResult[];
  summary: Record<StepStatus, number> & { verdict: 'PASS' | 'FAIL' };
  remaining: string[];
}

/** Secrets out, newlines kept, length bounded: the detail may quote a node answer. */
export function cleanDetail(text: string): string {
  return truncate(redact(text.replace(/\r\n?/g, '\n'))[0], MAX_DETAIL);
}

export function summarize(steps: StepResult[]): AcceptanceReport['summary'] {
  const counts = Object.fromEntries(STATUSES.map((status) => [status, 0])) as Record<StepStatus, number>;
  for (const step of steps) counts[step.status] += 1;
  return { ...counts, verdict: counts.FAIL ? 'FAIL' : 'PASS' };
}

export function buildAcceptanceReport(input: Omit<AcceptanceReport, 'protocol' | 'summary'>): AcceptanceReport {
  const steps = input.steps.map((step) => ({ ...step, detail: cleanDetail(step.detail) }));
  return { protocol: ACCEPTANCE_REPORT, ...input, steps, summary: summarize(steps) };
}

const MARK: Record<StepStatus, string> = { PASS: '✅ PASS', WARN: '⚠️ WARN', FAIL: '❌ FAIL', SKIP: '⏭ SKIP', INFO: 'ℹ️ INFO' };
const cell = (text: string) => text.replace(/\|/g, '\\|').replace(/\n/g, '<br>');
const who = (sw: Software) => `${sw.direction} ${sw.version} · сборка ${sw.build || 'неизвестна'} · коммит ${sw.commit ? sw.commit.slice(0, 12) : 'неизвестен'}`;

/** The text behind «Скопировать отчёт» and the .md file. */
export function renderAcceptanceMarkdown(report: AcceptanceReport): string {
  const s = report.summary;
  const lines = [
    `# p2pKanban: проверка приёмки — ${who(report.software)}`,
    '',
    `Прогон ${report.runId} · ${report.startedAt} → ${report.finishedAt}`,
  ];
  if (report.platform) lines.push(`Платформа: ${report.platform}`);
  const node = report.node;
  lines.push(node
    ? `Узел: ${node.origin || 'этот же адрес'} · web ${node.version || '?'} · сборка ${node.build || 'неизвестна'} · коммит ${node.commit ? node.commit.slice(0, 12) : 'неизвестен'}`
    : 'Узел: не ответил');
  lines.push('', `**Итог: ${s.verdict}** — PASS ${s.PASS}, WARN ${s.WARN}, FAIL ${s.FAIL}, SKIP ${s.SKIP}, INFO ${s.INFO}`, '');
  const failed = report.steps.filter((step) => step.status === 'FAIL');
  if (failed.length) {
    lines.push('## Что не прошло', '');
    for (const step of failed) lines.push(`- **${step.title}** (${step.id}): ${step.detail.split('\n')[0]}`);
    lines.push('');
  }
  lines.push('## Шаги', '', '| Фаза | Шаг | Итог | Вопрос приёмки | Подробности | мс |', '|---|---|---|---|---|---|');
  for (const step of report.steps) {
    lines.push(`| ${cell(step.phase)} | ${cell(step.title)} | ${MARK[step.status]} | ${step.covers.join(', ') || '—'} | ${cell(step.detail) || '—'} | ${step.ms} |`);
  }
  if (report.remaining.length) {
    lines.push('', '## Осталось человеку (D)', '');
    for (const item of report.remaining) lines.push(`- ${item}`);
  }
  lines.push('', `--- ${ACCEPTANCE_REPORT} ---`, canonical(report));
  return `${lines.join('\n')}\n`;
}

/** Read a report back from its text: the JSON after the marker is the source of truth. */
export function parseAcceptanceReport(text: string): AcceptanceReport {
  const marker = `--- ${ACCEPTANCE_REPORT} ---\n`;
  const at = text.indexOf(marker);
  if (at < 0) throw new Error(`в тексте нет отчёта ${ACCEPTANCE_REPORT}`);
  return JSON.parse(text.slice(at + marker.length)) as AcceptanceReport;
}

/** `p2pkanban-acceptance-web-20261017T030000Z.md` */
export function reportFileName(report: AcceptanceReport): string {
  const stamp = report.startedAt.replace(/[-:]/g, '').replace(/\.\d+/, '');
  return `p2pkanban-acceptance-${report.software.direction}-${stamp}.md`;
}
