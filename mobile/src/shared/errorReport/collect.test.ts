import { ApiError, apiRequest, setApiNodeOrigin } from '../api/client';
import { collectReport, mobileSoftware } from './collect';
import { logLine, resetJournalForTests } from './journal';
import { renderReport } from './report';

function response(status: number, body: string, headers: Record<string, string>) {
  return { ok: status < 400, status, headers: new Headers(headers), text: async () => body } as unknown as Response;
}

describe('error report on the phone', () => {
  const realFetch = globalThis.fetch;
  beforeEach(() => { resetJournalForTests(); setApiNodeOrigin('http://192.168.1.42:8080'); });
  afterEach(() => { globalThis.fetch = realFetch; });

  it('names the APK build and the node it talked to, so an old APK against a new node is visible', async () => {
    globalThis.fetch = jest.fn().mockResolvedValue(response(500,
      '{"error":{"code":"internal_error","message":"Internal server error","details":null,"errorId":"01a11200-0000-7000-8000-00000000e500"}}',
      { 'x-p2p-kanban-node': '2.1.0; build=8087da08253b; commit=unknown', 'x-p2p-error-id': '01a11200-0000-7000-8000-00000000e500' }));
    const error = await apiRequest('/boards/b1/cards', { method: 'POST', body: '{}' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    const report = collectReport({ message: 'Карточка не создана', error, screen: 'Доска' });
    expect(report.software).toEqual(mobileSoftware());
    expect(report.software.build).toBe('25');
    expect(report.peer).toEqual({ direction: 'web', version: '2.1.0', build: '8087da08253b', commit: null });
    expect(report.http).toMatchObject({ method: 'POST', path: '/api/v1/boards/b1/cards', status: 500, errorId: '01a11200-0000-7000-8000-00000000e500' });
    expect(renderReport(report)).toContain('ошибка узла 01a11200-0000-7000-8000-00000000e500');
  });

  it('a node that does not answer is a network error with status 0, and the token never reaches the report', async () => {
    logLine('warn', 'auth', 'refresh with Bearer abc.def');
    globalThis.fetch = jest.fn().mockRejectedValue(new TypeError('Network request failed'));
    const error = await apiRequest('/workspaces').catch((e: unknown) => e);
    const report = collectReport({ message: 'Пространства недоступны', error });
    expect(report.error.kind).toBe('network');
    expect(report.http?.status).toBe(0);
    expect(renderReport(report)).toContain('HTTP: GET /api/v1/workspaces → нет ответа');
    expect(renderReport(report)).not.toContain('abc.def');
  });

  it('a state without an error object explains itself with the last failed request', async () => {
    globalThis.fetch = jest.fn().mockResolvedValue(response(404, '{"error":{"code":"not_found","message":"Board not found"}}', {}));
    await apiRequest('/boards/b2').catch(() => undefined);
    const report = collectReport({ message: 'Доска не сохранена на устройстве' });
    expect(report.http).toMatchObject({ status: 404, path: '/api/v1/boards/b2' });
    expect(report.peer).toBeNull();
  });
});
