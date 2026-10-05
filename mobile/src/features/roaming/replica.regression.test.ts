import {getPublicKey, finalizeEvent} from 'nostr-tools/pure';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {commitLocalOperation, publishLocalOperation, pullRoamingBoard, flushReplicaJournal, recoverLocalReplica} from './service';
import {deriveBoardTag, roamingBase64, sealRoamingEvent} from './codec';
import {primeBoard} from './primeBoards';
import {applyOperation, LOCAL_SCHEMA_VERSION, type LocalBoardSnapshot, type LocalOperation} from '../localFirst/model';
import {defaultBoardAppearance} from '../appearance/boardTheme';
import {ROAMING_PROTOCOL_VERSION, type RoamingCapability} from './types';
import * as endpoints from '../../shared/api/endpoints';
import {publishToRelays} from './nostrRelay';

let mockPeer = 'A';
let mockOnline = true;
const mockRelay: any[] = [];
const mockSeeds: Record<string, LocalBoardSnapshot | null> = {};
const mockKey = new Uint8Array(32).fill(1);
const mockSecrets = {A: new Uint8Array(32).fill(2), P: new Uint8Array(32).fill(3)};

jest.mock('@react-native-async-storage/async-storage', () => require('@react-native-async-storage/async-storage/jest/async-storage-mock'));
jest.mock('expo-crypto', () => ({randomUUID: () => require('crypto').randomUUID(), getRandomBytes: (n: number) => new Uint8Array(require('crypto').randomBytes(n))}));
jest.mock('../../shared/storage/storage', () => ({sessionStorageKey: (key: string) => `${mockPeer}/${key}`}));
jest.mock('./storage', () => ({
  getOrCreateRoamingDeviceSecret: async () => mockSecrets[mockPeer as 'A'|'P'],
  loadRoamingCapability: async () => mockCap,
  saveRoamingCapability: jest.fn(),
}));
jest.mock('../../shared/api/endpoints', () => ({provisionRoamingBoard: jest.fn(() => { throw new Error('PC must remain offline'); })}));
jest.mock('../localFirst/snapshot', () => ({fetchBoardSnapshot: jest.fn(() => { throw new Error('PC must remain offline'); })}));
jest.mock('../localFirst/repository', () => ({
  serializeLocalState: async (task: () => Promise<unknown>) => task(),
  loadBoardSnapshot: async () => mockSeeds[mockPeer],
  loadOperationQueue: async () => [],
  persistServerSnapshot: async (value: LocalBoardSnapshot) => { mockSeeds[mockPeer] = value; return value; },
}));
jest.mock('./nostrRelay', () => ({
  createSignedNostrEvent: (v: any) => require('nostr-tools/pure').finalizeEvent({kind:v.kind,created_at:Math.floor(Date.now()/1000),tags:[['d',v.boardTag]],content:v.content},v.secretKey),
  publishToRelays: jest.fn(async (_relays: string[], event: any) => {
    if (!mockOnline) throw new Error('relay offline');
    mockRelay.push(event); return {acceptedRelays:['r1','r2'],failedRelays:[]};
  }),
  fetchFromRelays: async () => {
    if (!mockOnline) throw new Error('relay offline');
    return {events:[...mockRelay].reverse(),relayCount:2};
  },
}));

const boardId='00000000-0000-4000-8000-000000000001';
const workspaceId='00000000-0000-4000-8000-000000000002';
const mockCap: RoamingCapability={formatVersion:1,protocolVersion:ROAMING_PROTOCOL_VERSION,boardId,workspaceId,
  boardKey:roamingBase64.encode(mockKey),boardTag:deriveBoardTag(mockKey,boardId),capabilityEpoch:1,canWrite:true,
  writerPublicKeys:Object.values(mockSecrets).map(getPublicKey),relays:['r1','r2'],eventKind:1979,minimumRelayAcks:2,provisionedAt:'2026-09-01T00:00:00Z'};
function seed(): LocalBoardSnapshot { return {schemaVersion:LOCAL_SCHEMA_VERSION,workspaceId,
  board:{id:boardId,workspaceId,name:'board',boardType:'kanban',isArchived:false,createdAt:'2026-09-01',updatedAt:'2026-09-01'},
  columns:[],cards:[],checklistsByCardId:{},checklistsHydratedAt:'2026-09-01',appearance:defaultBoardAppearance(boardId),cachedAt:'2026-09-01',lastServerRefreshAt:null}; }
function create(title='local'): LocalOperation { const at=new Date().toISOString(); return {
  id:require('crypto').randomUUID(),boardId,entityId:'00000000-0000-4000-8000-000000000003',kind:'card.create',status:'pending',accessEpoch:1,createdAt:at,attempts:0,lastError:null,
  payload:{input:{title,columnId:'00000000-0000-4000-8000-000000000004'},tempCard:{id:'00000000-0000-4000-8000-000000000003',boardId,columnId:'00000000-0000-4000-8000-000000000004',title,position:1000,priority:null,isArchived:false,createdAt:at,updatedAt:at}}}; }
function update(title: string, base: LocalOperation): LocalOperation {return {...base,id:require('crypto').randomUUID(),kind:'card.update',payload:{input:{title}}};}
beforeEach(async () => {mockPeer='A';mockOnline=true;mockRelay.length=0;mockSeeds.A=seed();mockSeeds.P=seed();await AsyncStorage.clear();jest.clearAllMocks();});

test('P offline: local create survives restart and relay failure, then propagates without HTTP', async () => {
  const op=create(), original=seed(), changed=applyOperation(original,op);
  mockOnline=false;
  const event=await commitLocalOperation(mockCap,op,changed,original);
  expect((await recoverLocalReplica(mockCap,null))?.cards[0]?.title).toBe('local');
  await expect(flushReplicaJournal(mockCap)).rejects.toThrow('relay offline');
  mockOnline=true;
  await flushReplicaJournal(mockCap);
  expect((await pullRoamingBoard(mockCap,null)).snapshot?.cards[0]?.title).toBe('local');
  mockPeer='P';
  expect((await pullRoamingBoard(mockCap,seed())).snapshot?.cards[0]?.id).toBe(op.entityId);
  expect(endpoints.provisionRoamingBoard).not.toHaveBeenCalled();
  expect(event.eventId).toBe(op.id);
});

test('retry freezes event content and logical clock, never substitutes a later snapshot', async () => {
  const op=create(), changed=applyOperation(seed(),op);
  const first=await commitLocalOperation(mockCap,op,changed,seed());
  const second=await commitLocalOperation(mockCap,op,{...changed,cards:[{...changed.cards[0]!,title:'later'}]});
  expect(second).toEqual(first);
  await publishLocalOperation(mockCap,op,changed);
  expect(publishToRelays).toHaveBeenCalledTimes(1);
  await flushReplicaJournal(mockCap);
  expect(publishToRelays).toHaveBeenCalledTimes(1);
});

test('temporarily diverged replicas converge; local clocks advance after receiving peer work', async () => {
  const op=create(), base=applyOperation(seed(),op);
  await publishLocalOperation(mockCap,op,base);
  mockPeer='P'; await pullRoamingBoard(mockCap,seed());
  const p=update('P',op);await commitLocalOperation(mockCap,p,applyOperation(base,p),base);
  mockPeer='A';const a=update('A',op);await commitLocalOperation(mockCap,a,applyOperation(base,a),base);
  await flushReplicaJournal(mockCap);mockPeer='P';await flushReplicaJournal(mockCap);
  const pResult=await pullRoamingBoard(mockCap,base);
  mockPeer='A';const aResult=await pullRoamingBoard(mockCap,base);
  expect(aResult.snapshot?.cards).toEqual(pResult.snapshot?.cards);
  const after=update('after observing',op);
  const event=await commitLocalOperation(mockCap,after,applyOperation(aResult.snapshot!,after));
  expect(event.logicalClock).toBeGreaterThan(Math.max(...Object.values(aResult.applyState.fieldVersions).map(v=>v.logicalClock)));
});

test('already synchronized board preparation does not call a peer, even without relay', async () => {
  mockOnline=false;
  expect(await primeBoard(workspaceId,seed().board)).toBe('ready');
  expect(endpoints.provisionRoamingBoard).not.toHaveBeenCalled();
});

test('deltas received before baseline are retained; later relay baseline reconstructs without HTTP', async () => {
  const op=create('from P');mockPeer='P';await publishLocalOperation(mockCap,op,applyOperation(seed(),op));
  mockPeer='A';expect((await pullRoamingBoard(mockCap,null)).snapshot).toBeNull();
  const event={protocolVersion:ROAMING_PROTOCOL_VERSION,eventId:require('crypto').randomUUID(),workspaceId,boardId,capabilityEpoch:1,
    replicaId:'00000000-0000-4000-8000-000000000005',replicaSeq:1,logicalClock:1,entityType:'board' as const,entityId:boardId,
    operation:'board.snapshot' as const,fieldMask:['*'],payload:{snapshot:seed()},occurredAt:'2026-09-01T00:00:00Z'};
  mockRelay.push(finalizeEvent({kind:1979,created_at:Math.floor(Date.now()/1000),tags:[['d',mockCap.boardTag]],content:sealRoamingEvent(event,mockKey,mockCap.boardTag,new Uint8Array(24))},mockSecrets.P));
  expect((await pullRoamingBoard(mockCap,null)).snapshot?.cards[0]?.title).toBe('from P');
  mockSeeds.A=null;
  expect(await primeBoard(workspaceId,seed().board)).toBe('prepared');
  expect(endpoints.provisionRoamingBoard).not.toHaveBeenCalled();
});

test('a PostgreSQL-frozen event crosses the signed encrypted relay and applies without HTTP', async () => {
  const event = require('./fixtures/frozen-card.json');
  const cap = {...mockCap, boardId:event.boardId, workspaceId:event.workspaceId, boardTag:deriveBoardTag(mockKey,event.boardId)};
  const baseline = {...seed(),workspaceId:event.workspaceId,board:{...seed().board,id:event.boardId,workspaceId:event.workspaceId}};
  mockRelay.push(finalizeEvent({kind:cap.eventKind,created_at:Math.floor(Date.now()/1000),tags:[['d',cap.boardTag]],
    content:sealRoamingEvent(event,mockKey,cap.boardTag,new Uint8Array(24))},mockSecrets.P));
  const result=await pullRoamingBoard(cap,baseline);
  expect(result.snapshot?.cards[0]?.title).toBe('first');
  expect(endpoints.provisionRoamingBoard).not.toHaveBeenCalled();
});

test('retry reuses the exact encrypted signed event after relay failure',async()=>{
  const op=create();await commitLocalOperation(mockCap,op,applyOperation(seed(),op),seed());
  mockOnline=false;await expect(flushReplicaJournal(mockCap)).rejects.toThrow();
  const first=(publishToRelays as jest.Mock).mock.calls[0][1];
  mockOnline=true;await flushReplicaJournal(mockCap);
  expect(JSON.stringify((publishToRelays as jest.Mock).mock.calls[1][1])).toBe(JSON.stringify(first));
});

test('a relay baseline carries deletion evidence even when the delete event is no longer retained',async()=>{
  const op=create();mockPeer='P';const put=await commitLocalOperation(mockCap,op,applyOperation(seed(),op),seed());
  await flushReplicaJournal(mockCap);
  const deletedStamp={logicalClock:put.logicalClock+1,replicaId:put.replicaId,eventId:require('crypto').randomUUID()};
  const event={...put,eventId:require('crypto').randomUUID(),entityType:'board' as const,entityId:boardId,
    operation:'board.snapshot' as const,logicalClock:1,replicaSeq:1,
    payload:{snapshot:seed(),fieldVersions:{[op.entityId+':__lifecycle']:deletedStamp}}};
  mockRelay.push(finalizeEvent({kind:1979,created_at:Math.floor(Date.now()/1000),tags:[['d',mockCap.boardTag]],
    content:sealRoamingEvent(event,mockKey,mockCap.boardTag,new Uint8Array(24))},mockSecrets.P));
  mockPeer='A';const result=await pullRoamingBoard(mockCap,null);
  expect(result.snapshot?.cards).toEqual([]);
  expect(result.applyState.tombstones[op.entityId]).toEqual(deletedStamp);
});

test('history-first empty journal accepts a later cached board seed',async()=>{
 await pullRoamingBoard(mockCap,null); // Activity can open before Board.
 const original=applyOperation(seed(),create('cached card'));
 const op=update('edited card',create());
 await commitLocalOperation(mockCap,op,applyOperation(original,op),original);
 expect((await recoverLocalReplica(mockCap,null))?.cards[0]?.title).toBe('edited card');
});
