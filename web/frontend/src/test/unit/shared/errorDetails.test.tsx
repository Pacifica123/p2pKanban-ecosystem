import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/shared/api/errors';
import { BoardImportExecutionError } from '@/features/integrations/lib/importBoardCopy';
import { collectReport } from '@/shared/errorReport/collect';
import { logLine, noteApiFailure, notePeer, resetJournalForTests } from '@/shared/errorReport/journal';
import { parseReportText, renderReport } from '@/shared/errorReport/report';
import { ErrorState } from '@/shared/ui/ErrorState';

describe('error report in the web UI', () => {
  beforeEach(() => resetJournalForTests());
  afterEach(() => vi.unstubAllGlobals());

  it('turns the import 502 into a report with the stage, the request and the node version', () => {
    notePeer(new Headers({ 'x-p2p-kanban-node': '2.1.0; build=8087da08253b; commit=unknown' }));
    logLine('info', 'import', 'создание комментария 2/6');
    const api = new ApiError('Request failed with 502', { status: 502,
      http: { method: 'POST', path: '/api/v1/cards/c1/comments', body: '<html>502 Bad Gateway</html>', errorId: null } });
    const error = new BoardImportExecutionError('Импорт остановлен на этапе «создание комментария 2/6»: Request failed with 502.',
      { cause: api, stage: 'создание комментария 2/6' });
    const report = collectReport({ message: error.message, error, operation: 'Создать копию доски' });
    expect(report.stage).toBe('создание комментария 2/6');
    expect(report.error.kind).toBe('http');
    expect(report.http).toMatchObject({ method: 'POST', status: 502, body: '<html>502 Bad Gateway</html>' });
    expect(report.peer).toEqual({ direction: 'web', version: '2.1.0', build: '8087da08253b', commit: null });
    expect(report.logs.at(-1)).toContain('создание комментария 2/6');
    const text = renderReport(report);
    expect(text).toContain('Где: ');
    expect(text).toContain('HTTP: POST /api/v1/cards/c1/comments → 502');
    expect(parseReportText(text)).toEqual(report);
  });

  it('hides secrets from the node answer and the journal', () => {
    logLine('warn', 'api', 'Authorization: Bearer abc.def.ghi');
    const api = new ApiError('boom', { status: 500,
      http: { method: 'POST', path: '/api/v1/auth/sign-in', body: '{"password":"hunter2","errorId":"x"}', errorId: '01a11200-0000-7000-8000-00000000e500' } });
    const report = collectReport({ message: 'Вход не удался', error: api });
    expect(report.http?.body).toBe('{"password":"[скрыто]","errorId":"x"}');
    expect(report.logs.join('\n')).not.toContain('abc.def.ghi');
    expect(report.redacted).toBe(2);
    expect(renderReport(report)).toContain('ошибка узла 01a11200-0000-7000-8000-00000000e500');
  });

  it('without an error object, the last failed request explains the screen', () => {
    noteApiFailure({ method: 'GET', path: '/api/v1/workspaces', status: 0, requestId: null, errorId: null, body: null });
    const report = collectReport({ message: 'Не удалось загрузить пространства' });
    expect(report.error.kind).toBe('network');
    expect(renderReport(report)).toContain('HTTP: GET /api/v1/workspaces → нет ответа');
  });

  it('copies through the clipboard when the page is secure', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
    vi.stubGlobal('isSecureContext', true);
    render(<ErrorState title="Не удалось загрузить доску" />);
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать подробности' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toContain('Сообщение: Не удалось загрузить доску');
    expect(await screen.findByText(/Скопировано/)).toBeInTheDocument();
  });

  it('shows the text to select by hand when a plain-http node blocks the clipboard', async () => {
    vi.stubGlobal('isSecureContext', false);
    render(<ErrorState title="Импорт не завершён" description="Request failed with 502" />);
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать подробности' }));
    const area = await screen.findByRole('textbox');
    expect((area as HTMLTextAreaElement).value).toContain('p2pKanban: подробности ошибки');
  });
});
