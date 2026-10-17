// Debug journal as a Markdown file (docs/architecture/debug-mode-20261017.md). Pure: the screen
// passes in what it has, tests check the text. Every line goes through the
// same redaction as an error report (contracts/error-report/1).
import { redact, type ErrorReport } from '../errorReport/report';

export type DebugExportInput = {
  software: ErrorReport['software'];
  platform: string | null;
  exportedAt: string;
  /** Lines of this run, old first. */
  lines: string[];
  /** Redacted tail kept from the previous run, old first. */
  previous?: string[];
  /** Whether the debug mode was on while these lines were written. */
  debugMode: boolean;
};

export function softwareLabel(software: ErrorReport['software']) {
  return [
    `${software.direction} ${software.version ?? 'версия неизвестна'}`,
    software.build ? `сборка ${software.build}` : null,
    software.commit ? `коммит ${software.commit.slice(0, 7)}` : 'коммит неизвестен',
  ].filter(Boolean).join(' · ');
}

/** Redact every line; returns the clean lines and how many values were hidden. */
export function redactLines(lines: string[]): [string[], number] {
  let hidden = 0;
  const clean = lines.map((line) => {
    const [text, count] = redact(line.replace(/\r\n|\r|\n/g, ' '));
    hidden += count;
    return text;
  });
  return [clean, hidden];
}

/** A fence longer than any backtick run inside, so a line cannot close it. */
function fenceFor(lines: string[]) {
  const longest = Math.max(2, ...lines.map((line) => Math.max(0, ...(line.match(/`+/g) || []).map((run) => run.length))));
  return '`'.repeat(longest + 1);
}

function block(lines: string[]) {
  const fence = fenceFor(lines);
  return [`${fence}text`, ...lines, fence].join('\n');
}

function period(lines: string[]) {
  const first = lines[0]?.split(' ', 1)[0];
  const last = lines[lines.length - 1]?.split(' ', 1)[0];
  return first && last ? `с ${first} по ${last}` : 'пусто';
}

export function renderDebugJournal(input: DebugExportInput): { text: string; hidden: number } {
  const [current, hiddenNow] = redactLines(input.lines);
  const [previous, hiddenBefore] = redactLines(input.previous ?? []);
  const hidden = hiddenNow + hiddenBefore;
  const out = [
    '# p2pKanban: журнал отладки',
    '',
    `- Программа: ${softwareLabel(input.software)}`,
    ...(input.platform ? [`- Платформа: ${input.platform}`] : []),
    `- Выгружен: ${input.exportedAt}`,
    `- Режим отладки: ${input.debugMode ? 'включён' : 'выключен (только запросы и ошибки)'}`,
    `- Строк: ${current.length} (${period(current)})`,
    `- Скрыто значений: ${hidden}`,
    '',
    '## Этот запуск',
    '',
    current.length ? block(current) : 'Строк нет.',
  ];
  if (previous.length) {
    out.push('', '## Прошлый запуск, последние строки', '', block(previous));
  }
  return { text: `${out.join('\n')}\n`, hidden };
}

export function debugJournalFilename(direction: string, at: string) {
  return `p2pkanban-${direction}-debug-${at.replace(/[:.]/g, '-')}.md`;
}
