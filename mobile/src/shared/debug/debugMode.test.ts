import {
  DEBUG_CAPACITY,
  NORMAL_CAPACITY,
  journalEntries,
  journalLines,
  logLine,
  resetJournalForTests,
  setJournalDebugMode,
  subscribeJournal,
  trace,
} from '../errorReport/journal';
import { debugJournalFilename, renderDebugJournal } from './export';

const software = { direction: 'mobile' as const, version: '2.1.0', build: '28', commit: 'c3bc6f61a3a0' };

describe('debug mode journal', () => {
  beforeEach(() => resetJournalForTests());

  it('keeps detailed lines only while the debug mode is on', () => {
    let built = 0;
    trace('board', () => { built += 1; return 'не должно попасть'; });
    expect(built).toBe(0);
    expect(journalLines()).toEqual([]);
    setJournalDebugMode(true);
    trace('board', () => 'доска 01a10d38: открыта');
    expect(journalLines()).toHaveLength(1);
    expect(journalLines()[0]).toMatch(/^\d{4}-\d\d-\d\dT[\d:.]+Z debug board: доска 01a10d38: открыта$/);
  });

  it('grows to the debug capacity and shrinks back when the mode is off', () => {
    setJournalDebugMode(true);
    for (let index = 0; index < DEBUG_CAPACITY + 10; index += 1) logLine('debug', 'api', `запрос ${index}`);
    expect(journalEntries()).toHaveLength(DEBUG_CAPACITY);
    setJournalDebugMode(false);
    expect(journalEntries()).toHaveLength(NORMAL_CAPACITY);
    expect(journalLines().at(-1)).toContain(`запрос ${DEBUG_CAPACITY + 9}`);
  });

  it('tells subscribers about every new line', () => {
    const seen: number[] = [];
    const stop = subscribeJournal(() => seen.push(journalEntries().length));
    logLine('info', 'net', 'сеть: wifi');
    stop();
    logLine('info', 'net', 'сеть: cellular');
    expect(seen).toEqual([1]);
  });

  it('a broken description does not throw into the caller', () => {
    setJournalDebugMode(true);
    expect(() => trace('board', () => { throw new Error('нет снимка'); })).not.toThrow();
    expect(journalLines()[0]).toContain('строка не собрана: Error: нет снимка');
  });
});

describe('debug journal export', () => {
  it('renders Markdown with redacted lines and the previous run', () => {
    const { text, hidden } = renderDebugJournal({
      software,
      platform: 'Android 12 (API 31) · M2010J19SY',
      exportedAt: '2026-10-17T03:00:00.000Z',
      lines: [
        '2026-10-17T02:59:58.000Z info auth: Authorization: Bearer abc.def',
        '2026-10-17T02:59:59.000Z debug api: GET /api/v1/boards?token=s3cr3t → 200 за 12 мс',
      ],
      previous: ['2026-10-16T22:00:00.000Z warn ui: JS-поток не отвечал 2.0 с'],
      debugMode: true,
    });
    expect(hidden).toBe(2);
    expect(text).not.toContain('abc.def');
    expect(text).not.toContain('s3cr3t');
    expect(text).toContain('- Программа: mobile 2.1.0 · сборка 28 · коммит c3bc6f6');
    expect(text).toContain('- Строк: 2 (с 2026-10-17T02:59:58.000Z по 2026-10-17T02:59:59.000Z)');
    expect(text).toContain('## Прошлый запуск, последние строки');
    expect(text.endsWith('```\n')).toBe(true);
  });

  it('a line with backticks cannot close the fence', () => {
    const { text } = renderDebugJournal({
      software, platform: null, exportedAt: '2026-10-17T03:00:00.000Z',
      lines: ['2026-10-17T02:59:58.000Z error js: ```boom```'], debugMode: false,
    });
    expect(text).toContain('````text\n');
    expect(text).toContain('- Режим отладки: выключен (только запросы и ошибки)');
  });

  it('names the file by direction and time without colons', () => {
    expect(debugJournalFilename('mobile', '2026-10-17T03:00:00.000Z')).toBe('p2pkanban-mobile-debug-2026-10-17T03-00-00-000Z.md');
  });
});
