import { prepareDeviceLink } from './service';
import { apiRequest, ApiError } from '../../shared/api/client';
import { readSessionJson, writeSessionJson } from '../../shared/storage/storage';
import { decryptPack, verifyChain } from './protocol';
jest.mock('../../shared/api/client', () => {
  class ApiError extends Error { status = 0; }
  return { apiRequest: jest.fn(), ApiError, isNetworkError: (e: unknown) => e instanceof ApiError };
});
jest.mock('../../shared/storage/storage', () => ({ readSessionJson: jest.fn(), writeSessionJson: jest.fn(), sessionStorageKey: () => 'test-scope' }));
jest.mock('../roaming/storage', () => ({ getOrCreateRoamingDeviceSecret: async () => new Uint8Array(32).fill(1) }));
jest.mock('../localFirst/repository', () => ({}));
jest.mock('../roaming/service', () => ({pullRoamingBoard: jest.fn()}));
jest.mock('../roaming/nostrRelay', () => ({fetchFromRelays: jest.fn()}));
jest.mock('expo-file-system', () => ({ File: jest.fn(), Paths: { cache: 'cache' } }));
jest.mock('expo-sharing', () => ({ shareAsync: jest.fn() }));
jest.mock('./protocol', () => ({ decryptPack: jest.fn(), verifyChain: jest.fn() }));
beforeEach(() => {
  jest.clearAllMocks();
  (readSessionJson as jest.Mock).mockResolvedValue({ id: 'saved' });
  (decryptPack as jest.Mock).mockReturnValue({ snapshot: { exportedAt: 'saved-at' }, chains: { b: [] } });
  (verifyChain as jest.Mock).mockReturnValue({ grant: { expiresAt: 9999999999 } });
});
const offline = () => new ApiError('offline', { status: 0 });
test('valid cached permission requires no fetch or replacement', async () => {
  await expect(prepareDeviceLink()).resolves.toBe('saved-at');
  expect(apiRequest).not.toHaveBeenCalled(); expect(writeSessionJson).not.toHaveBeenCalled();
});
test('failed explicit refresh preserves permission and explains offline approval', async () => {
  (apiRequest as jest.Mock).mockRejectedValue(offline());
  await expect(prepareDeviceLink({ refresh: true })).rejects.toThrow('Сохранённое разрешение действует');
  expect(writeSessionJson).not.toHaveBeenCalled();
});
test('unprepared device cannot invent permission offline', async () => {
  (readSessionJson as jest.Mock).mockResolvedValue(null); (apiRequest as jest.Mock).mockRejectedValue(offline());
  await expect(prepareDeviceLink()).rejects.toThrow('действующего разрешения нет');
  expect(writeSessionJson).not.toHaveBeenCalled();
});
test('expired proof is not reused', async () => {
  (verifyChain as jest.Mock).mockImplementation(() => { throw new Error('expired'); });
  (apiRequest as jest.Mock).mockRejectedValue(offline());
  await expect(prepareDeviceLink()).rejects.toThrow('действующего разрешения нет');
});
