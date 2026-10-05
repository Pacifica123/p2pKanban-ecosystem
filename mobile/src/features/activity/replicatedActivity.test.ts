import {commonActivity,getCommonBoardActivity} from './replicatedActivity';
import type {RoamingBoardEvent} from '../roaming/types';
import {ROAMING_PROTOCOL_VERSION} from '../roaming/types';
import {getBoardActivity} from '../../shared/api/endpoints';
import {pullRoamingBoard} from '../roaming/service';

jest.mock('../../shared/api/endpoints',()=>({getBoardActivity:jest.fn()}));
jest.mock('../roaming/service',()=>({loadRoamingCapability:async()=>({boardId:'board'}),pullRoamingBoard:jest.fn(async()=>({}))}));
jest.mock('../roaming/journal',()=>({serializeReplica:async(task:()=>unknown)=>task(),loadJournal:async()=>({events:mockEvents})}));
const action={id:'shared-id',createdAt:'2026-10-01T10:00:00Z',kind:'comment.created',boardId:'board',cardId:'card',
 entityType:'comment',entityId:'comment',actor:{userId:'peer',displayName:'Peer'},fieldMask:['body']};
const event:RoamingBoardEvent={protocolVersion:ROAMING_PROTOCOL_VERSION,eventId:'transport-id',workspaceId:'workspace',
 boardId:'board',capabilityEpoch:1,replicaId:'peer-node',replicaSeq:1,logicalClock:1,entityType:'board',entityId:'board',
 operation:'board.activity',fieldMask:[],payload:{activity:action},occurredAt:action.createdAt};
let mockEvents=[event];
beforeEach(()=>{mockEvents=[event];jest.clearAllMocks();});
test('common history includes another peer and deduplicates activity ids, excludes snapshots',()=>{
 expect(commonActivity([event,{...event,eventId:'retry'},{...event,operation:'board.snapshot',payload:{}}],'board')).toEqual([action]);
 expect(commonActivity([event],'another-board')).toEqual([]);
});
test('provisioned board reads shared relay history without HTTP',async()=>{
 expect((await getCommonBoardActivity('board',true)).items).toEqual([action]);
 expect(pullRoamingBoard).toHaveBeenCalled();expect(getBoardActivity).not.toHaveBeenCalled();
});
test('offline cache preserves common peer history without transport',async()=>{
 expect(await getCommonBoardActivity('board',false)).toEqual({items:[action],nextCursor:null,stale:true});
 expect(pullRoamingBoard).not.toHaveBeenCalled();expect(getBoardActivity).not.toHaveBeenCalled();
});
test('failed relay pull retains cached history and exposes stale status',async()=>{
 (pullRoamingBoard as jest.Mock).mockRejectedValueOnce(new Error('relay down'));
 expect((await getCommonBoardActivity('board',true)).stale).toBe(true);
 expect(getBoardActivity).not.toHaveBeenCalled();
});
