import {CatalogChannelMissing,catalogProblemText,refreshDeviceCatalog,refreshWorkspaceCatalog} from './catalog';
import {fetchDeviceCatalogEvents} from './nostrRelay';

jest.mock('./nostrRelay',()=>({fetchDeviceCatalogEvents:jest.fn()}));
jest.mock('./service',()=>({installRoamingCapability:jest.fn()}));
jest.mock('./storage',()=>({
  getOrCreateRoamingDeviceSecret:async()=>new Uint8Array(32).fill(1),
  loadRoamingCatalogChannel:async()=>null,
}));
jest.mock('../../shared/storage/storage',()=>({
  loadCachedBoards:jest.fn(async()=>[]),saveCachedBoards:jest.fn(),
  loadCachedWorkspaces:jest.fn(async()=>[]),saveCachedWorkspaces:jest.fn(),
}));

test('a phone without relay addresses says so instead of silently showing the cache',async()=>{
  await expect(refreshDeviceCatalog('workspace','user')).rejects.toBeInstanceOf(CatalogChannelMissing);
  await expect(refreshWorkspaceCatalog('user')).rejects.toBeInstanceOf(CatalogChannelMissing);
  expect(fetchDeviceCatalogEvents).not.toHaveBeenCalled();
  expect(catalogProblemText(new CatalogChannelMissing())).toContain('ещё не получил их адреса');
});

test('an unreachable relay catalog names the relays and keeps the cached boards in view',()=>{
  const text=catalogProblemText(new Error('Каталог досок недоступен: ни один релей не ответил. wss://nos.lol: сеть не пускает.'));
  expect(text).toContain('только через релеи');
  expect(text).toContain('Видны сохранённые раньше.');
  expect(text).toContain('wss://nos.lol');
});
