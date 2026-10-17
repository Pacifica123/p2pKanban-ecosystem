import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { DebugJournalPage } from '@/features/debug/DebugJournalPage';
import { resetDebugModeForTests, setDebugMode } from '@/shared/debug/debugMode';
import { renderDebugJournal } from '@/shared/debug/export';
import {
  DEBUG_CAPACITY,
  NORMAL_CAPACITY,
  journalEntries,
  journalLines,
  logLine,
  resetJournalForTests,
  trace,
} from '@/shared/errorReport/journal';

describe('debug journal in the web UI', () => {
  beforeEach(() => {
    resetJournalForTests();
    resetDebugModeForTests();
    window.localStorage.clear();
  });
  afterEach(() => window.localStorage.clear());

  it('records detailed lines only in the debug mode and keeps the switch in this browser', () => {
    trace('nav', () => 'страница /');
    expect(journalLines()).toEqual([]);
    setDebugMode(true);
    expect(window.localStorage.getItem('p2pkanban:debug-mode')).toBe('1');
    trace('nav', () => 'страница /settings/debug');
    expect(journalLines().at(-1)).toMatch(/ debug nav: страница \/settings\/debug$/);
    for (let index = 0; index < DEBUG_CAPACITY; index += 1) logLine('debug', 'api', `GET /api/v1/x ${index}`);
    expect(journalEntries()).toHaveLength(DEBUG_CAPACITY);
    setDebugMode(false);
    expect(journalEntries()).toHaveLength(NORMAL_CAPACITY);
    expect(window.localStorage.getItem('p2pkanban:debug-mode')).toBeNull();
  });

  it('shows lines live without secrets and switches the mode', async () => {
    logLine('warn', 'api', 'POST /api/v1/auth/sign-in → 401 password=hunter2');
    render(<DebugJournalPage />);
    const lines = screen.getByTestId('debug-journal-lines');
    expect(lines.textContent).toContain('password=[скрыто]');
    expect(lines.textContent).not.toContain('hunter2');
    fireEvent.click(screen.getByTestId('debug-mode-toggle'));
    expect(screen.getByTestId('debug-mode-toggle').textContent).toBe('Выключить режим отладки');
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 350)); });
    expect(lines.textContent).toContain('режим отладки включён');
  });

  it('exports Markdown of the same form as the other clients', () => {
    const { text, hidden } = renderDebugJournal({
      software: { direction: 'web', version: '2.1.0', build: 'f5d187667317', commit: null },
      platform: 'Firefox', exportedAt: '2026-10-17T03:10:00.000Z',
      lines: ['2026-10-17T03:09:59.000Z debug api: GET /api/v1/boards?access_token=abc → 200 за 9 мс'], debugMode: true,
    });
    expect(hidden).toBe(1);
    expect(text.split('\n').slice(0, 3)).toEqual(['# p2pKanban: журнал отладки', '', '- Программа: web 2.1.0 · сборка f5d187667317 · коммит неизвестен']);
    expect(text).not.toContain('abc →');
  });
});
