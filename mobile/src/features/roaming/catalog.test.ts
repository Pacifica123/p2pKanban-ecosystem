import type {Event} from 'nostr-tools/pure';
import {refreshDeviceCatalog,refreshWorkspaceCatalog} from './catalog';
import {decryptPayloadParts,verifyChain} from '../deviceLink/protocol';
import {fetchDeviceCatalogEvents} from './nostrRelay';
import {installRoamingCapability} from './service';
import {saveCachedBoards,saveCachedWorkspaces} from '../../shared/storage/storage';

const board={id:'board',workspaceId:'workspace',name:'Relay board',boardType:'kanban',isArchived:false,createdAt:'2026-01-01',updatedAt:'2026-01-01'};
const capability={formatVersion:1,protocolVersion:'p2p-kanban-roaming/1',workspaceId:'workspace',boardId:'board',boardTag:'tag',boardKey:'key',capabilityEpoch:1,canWrite:true,writerPublicKeys:['trusted'],relays:['wss://relay'],eventKind:30101,minimumRelayAcks:1,provisionedAt:'2026-01-01'};

jest.mock('./nostrRelay',()=>({fetchDeviceCatalogEvents:jest.fn()}));
jest.mock('./service',()=>({installRoamingCapability:jest.fn()}));
jest.mock('../deviceLink/protocol',()=>({decryptPayloadParts:jest.fn(),verifyChain:jest.fn()}));
jest.mock('./storage',()=>({
  getOrCreateRoamingDeviceSecret:async()=>new Uint8Array(32).fill(1),
  loadRoamingCatalogChannel:async()=>({relays:['wss://relay'],eventKind:30102,trustedPublishers:['trusted']}),
}));
jest.mock('../../shared/storage/storage',()=>({
  loadCachedBoards:jest.fn(async()=>[]),
  saveCachedBoards:jest.fn(),
  loadCachedWorkspaces:jest.fn(async()=>[]),
  saveCachedWorkspaces:jest.fn(),
}));

function event(pubkey:string,parts:string[],created_at=1):Event{return {
  id:parts.join('-'),pubkey,created_at,kind:30102,
  tags:[['p','1b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f']],
  content:JSON.stringify({protocol:'p2p-kanban-device-catalog/1',recipient:'1b84c5567b126440995d3ed5aaba0565d71e1834604819ff9c17f5e9d5dd078f',parts}),sig:'sig',
};}

test('restores a missing board and capability from a trusted direct relay catalog',async()=>{
  (fetchDeviceCatalogEvents as jest.Mock).mockResolvedValue({relayCount:1,events:[event('untrusted',['bad']),event('trusted',['good'],2)]});
  (decryptPayloadParts as jest.Mock).mockReturnValue({protocol:'p2p-kanban-device-catalog/1',workspaceId:'workspace',board,capability,publishedAt:'2026-01-01'});
  await expect(refreshDeviceCatalog('workspace')).resolves.toEqual([board]);
  expect(decryptPayloadParts).toHaveBeenCalledTimes(2);
  expect(installRoamingCapability).toHaveBeenCalledWith(capability);
  expect(saveCachedBoards).toHaveBeenCalledWith('workspace',[board]);
});

test('recovers a new workspace from an encrypted catalog with a verified delegation',async()=>{
  (fetchDeviceCatalogEvents as jest.Mock).mockResolvedValue({relayCount:1,events:[event('trusted',['workspace'],2)]});
  (decryptPayloadParts as jest.Mock).mockReturnValue({protocol:'p2p-kanban-device-catalog/1',
    workspaceId:'workspace',workspace:{id:'workspace',name:'New space',visibility:'private'},
    board,capability,publishedAt:'2026-01-01'});
  (verifyChain as jest.Mock).mockReturnValue({root:'trusted',grant:{userId:'user',boardId:'board',
    workspaceId:'workspace',epoch:1,canDelegate:true}});
  await expect(refreshWorkspaceCatalog('user')).resolves.toEqual([
    expect.objectContaining({id:'workspace',name:'New space',ownerUserId:'user'}),
  ]);
  expect(saveCachedBoards).toHaveBeenCalledWith('workspace',[board]);
  expect(saveCachedWorkspaces).toHaveBeenCalledWith([
    expect.objectContaining({id:'workspace',accessEpoch:1}),
  ]);
});
test('newest authenticated workspace catalog wins regardless of relay result order',async()=>{
  jest.clearAllMocks();
  (fetchDeviceCatalogEvents as jest.Mock).mockResolvedValue({relayCount:1,
    events:[event('trusted',['new'],3),event('trusted',['old'],2)]});
  (decryptPayloadParts as jest.Mock).mockImplementation((_secret,_sender,parts)=>({
    protocol:'p2p-kanban-device-catalog/1',workspaceId:'workspace',
    workspace:{id:'workspace',name:'Space',visibility:'private'},
    board:{...board,name:parts[0]==='new'?'Latest':'Stale'},capability,publishedAt:'2026-01-01'}));
  (verifyChain as jest.Mock).mockReturnValue({root:'trusted',grant:{userId:'user',boardId:'board',
    workspaceId:'workspace',epoch:1,canDelegate:true}});
  await refreshWorkspaceCatalog('user');
  expect(installRoamingCapability).toHaveBeenCalledTimes(1);
  expect(saveCachedBoards).toHaveBeenLastCalledWith('workspace',[expect.objectContaining({name:'Latest'})]);
});
test('an introduced laptop can publish new boards in an existing workspace without HTTP',async()=>{
  jest.clearAllMocks();
  (fetchDeviceCatalogEvents as jest.Mock).mockResolvedValue({relayCount:1,events:[event('laptop',['new'],4)]});
  const intro=[{id:'intro'}], delegated=[{id:'delegated'}];
  (decryptPayloadParts as jest.Mock).mockReturnValue({protocol:'p2p-kanban-device-catalog/1',
    workspaceId:'workspace',board,capability:{...capability,delegationChain:delegated},
    introductionChain:intro,publishedAt:'2026-01-01'});
  (verifyChain as jest.Mock).mockImplementation(chain=>chain===intro
    ?{root:'trusted',grant:{userId:'user',canDelegate:true}}
    :{root:'laptop',grant:{userId:'user',boardId:'board',workspaceId:'workspace',epoch:1}});
  await expect(refreshDeviceCatalog('workspace','user')).resolves.toEqual([board]);
  expect(installRoamingCapability).toHaveBeenCalledTimes(1);
  jest.clearAllMocks();
  await expect(refreshDeviceCatalog('workspace','other-user')).resolves.toEqual([]);
  expect(installRoamingCapability).not.toHaveBeenCalled();
});
