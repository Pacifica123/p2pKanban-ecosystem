import { fetchNearbyRequest, preparationInfo, prepareDeviceLink, resetPreparationMemoForTests } from './service';
import { apiRequest, ApiError } from '../../shared/api/client';
import { readSessionJson, writeSessionJson } from '../../shared/storage/storage';
import { decryptPackSliced, verifyChain } from './protocol';
jest.mock('../../shared/api/client', () => {
  class ApiError extends Error { status = 0; }
  return { apiRequest: jest.fn(), ApiError, isNetworkError: (e: unknown) => e instanceof ApiError };
});
jest.mock('../../shared/storage/storage', () => ({ readSessionJson: jest.fn(), writeSessionJson: jest.fn(), sessionStorageKey: () => 'test-scope' }));
jest.mock('../roaming/storage', () => ({ getOrCreateRoamingDeviceSecret: async () => new Uint8Array(32).fill(1) }));
jest.mock('../localFirst/repository', () => ({}));
jest.mock('../roaming/service', () => ({pullRoamingBoard: jest.fn()}));
jest.mock('../roaming/nostrRelay', () => ({fetchFromRelays: jest.fn()}));
jest.mock('../../shared/lib/stallWatch', () => ({ heavyWork: (_label: string, run: () => Promise<unknown>) => run() }));
jest.mock('expo-file-system', () => ({ File: jest.fn(), Paths: { cache: 'cache' } }));
jest.mock('expo-sharing', () => ({ shareAsync: jest.fn() }));
jest.mock('./protocol', () => ({ decryptPackSliced: jest.fn(), verifyChain: jest.fn(), checkRequest: jest.fn() }));
const future = 9999999999;
/** Storage with an old pack (no summary yet) unless a test says otherwise. */
let stored: Record<string, unknown>;
beforeEach(() => {
  jest.clearAllMocks();
  resetPreparationMemoForTests();
  stored = { 'device-link/prepared': { id: 'saved' } };
  (readSessionJson as jest.Mock).mockImplementation(async (key: string, fallback: unknown) => stored[key] ?? fallback);
  (decryptPackSliced as jest.Mock).mockResolvedValue({ snapshot: { exportedAt: 'saved-at' }, chains: { b: [] } });
  (verifyChain as jest.Mock).mockReturnValue({ grant: { expiresAt: future } });
});
const offline = () => new ApiError('offline', { status: 0 });
test('valid cached permission requires no fetch or replacement', async () => {
  await expect(prepareDeviceLink()).resolves.toBe('saved-at');
  expect(apiRequest).not.toHaveBeenCalled();
  // Only the summary of an old pack is written, the pack itself stays.
  expect(writeSessionJson).toHaveBeenCalledTimes(1);
  expect(writeSessionJson).toHaveBeenCalledWith('device-link/prepared-info', expect.objectContaining({ eventId: 'saved', boards: 1 }));
});
test('a stored summary answers without opening the pack', async () => {
  stored['device-link/prepared-info'] = { eventId: 'saved', exportedAt: 'summary-at', boards: 3, expiresAt: future };
  await expect(preparationInfo()).resolves.toMatchObject({ exportedAt: 'summary-at', boards: 3 });
  await expect(prepareDeviceLink()).resolves.toBe('summary-at');
  expect(decryptPackSliced).not.toHaveBeenCalled();
});
test('repeated taps share one opening of an old pack', async () => {
  await Promise.all([preparationInfo(), preparationInfo(), preparationInfo()]);
  await preparationInfo();
  expect(decryptPackSliced).toHaveBeenCalledTimes(1);
});
test('an expired summary is no permission', async () => {
  stored['device-link/prepared-info'] = { eventId: 'saved', exportedAt: 'old', boards: 1, expiresAt: 1 };
  await expect(preparationInfo()).resolves.toBeNull();
});
test('failed explicit refresh preserves permission and explains offline approval', async () => {
  (apiRequest as jest.Mock).mockRejectedValue(offline());
  await expect(prepareDeviceLink({ refresh: true })).rejects.toThrow('Сохранённое разрешение действует');
  expect(writeSessionJson).not.toHaveBeenCalledWith('device-link/prepared', expect.anything());
});
test('unprepared device cannot invent permission offline', async () => {
  stored = {}; (apiRequest as jest.Mock).mockRejectedValue(offline());
  await expect(prepareDeviceLink()).rejects.toThrow('действующего разрешения нет');
  expect(writeSessionJson).not.toHaveBeenCalled();
});
test('expired proof is not reused', async () => {
  (verifyChain as jest.Mock).mockImplementation(() => { throw new Error('expired'); });
  (apiRequest as jest.Mock).mockRejectedValue(offline());
  await expect(prepareDeviceLink()).rejects.toThrow('действующего разрешения нет');
});
describe('laptop in the local network', () => {
  const realFetch = globalThis.fetch;
  afterEach(() => { globalThis.fetch = realFetch; jest.useRealTimers(); });
  const hanging = () => jest.fn((_url: string, init: RequestInit) => new Promise((_resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(new Error('Aborted')));
  })) as unknown as typeof fetch;
  test('a silent laptop ends in 10 seconds instead of holding the panel', async () => {
    jest.useFakeTimers();
    globalThis.fetch = hanging();
    const pending = fetchNearbyRequest('192.168.1.42:8080');
    const outcome = expect(pending).rejects.toThrow('не ответил за 10 секунд');
    await jest.advanceTimersByTimeAsync(10_000);
    await outcome;
  });
  test('cancel stops the request at once', async () => {
    globalThis.fetch = hanging();
    const controller = new AbortController();
    const pending = fetchNearbyRequest('192.168.1.42:8080', controller.signal);
    controller.abort();
    await expect(pending).rejects.toThrow('экран закрыт');
  });
});
