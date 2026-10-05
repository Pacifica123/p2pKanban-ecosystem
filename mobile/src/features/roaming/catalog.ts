import {generateSecretKey, getPublicKey, type Event} from 'nostr-tools/pure';
import type {Board, Workspace} from '../../shared/types/api';
import {loadCachedBoards, saveCachedBoards, loadCachedWorkspaces, saveCachedWorkspaces} from '../../shared/storage/storage';
import {decryptPayloadParts, verifyChain} from '../deviceLink/protocol';
import {fetchDeviceCatalogEvents} from './nostrRelay';
import {installRoamingCapability} from './service';
import {getOrCreateRoamingDeviceSecret, loadRoamingCatalogChannel, type RoamingCatalogChannel} from './storage';
import type {RoamingCapability} from './types';

export const DEVICE_CATALOG_PROTOCOL = 'p2p-kanban-device-catalog/1';
interface CatalogEnvelope {protocol:string; recipient:string; parts:string[]}
interface CatalogEntry {protocol:string;workspaceId:string;board:Board;capability:RoamingCapability;publishedAt:string;introductionChain?:Event[]}
function addressedTo(event: Event, recipient: string) {return event.tags.some(tag => tag[0] === 'p' && tag[1] === recipient);}
function validEntry(value: unknown, workspaceId: string): value is CatalogEntry {
  const item=value as Partial<CatalogEntry>;
  return item?.protocol===DEVICE_CATALOG_PROTOCOL && item.workspaceId===workspaceId
    && Boolean(item.board?.id) && item.board?.workspaceId===workspaceId
    && item.capability?.boardId===item.board?.id && item.capability?.workspaceId===workspaceId;
}
function trustedPublisher(channel: RoamingCatalogChannel, event: Event, entry: CatalogEntry, userId?: string) {
  if (channel.trustedPublishers.includes(event.pubkey.toLowerCase())) return true;
  if (!userId) return false;
  try {
    const intro = verifyChain(entry.introductionChain || [], event.pubkey);
    return channel.trustedPublishers.includes(intro.root.toLowerCase())
      && intro.grant.userId === userId && intro.grant.canDelegate;
  } catch { return false; }
}
/** Recover board metadata and keys without contacting the HTTP node. */
export async function refreshDeviceCatalog(workspaceId: string, userId?: string) {
  const channel=await loadRoamingCatalogChannel();
  if (!channel?.relays.length || !channel.trustedPublishers.length) return loadCachedBoards(workspaceId);
  const secret=await getOrCreateRoamingDeviceSecret(generateSecretKey), recipient=getPublicKey(secret);
  const response=await fetchDeviceCatalogEvents({relays:channel.relays,kind:channel.eventKind,recipient});
  const entries=new Map<string,{entry:CatalogEntry; createdAt:number; eventId:string}>();
  for(const event of response.events){
    try{
      if(!addressedTo(event,recipient))continue;
      const envelope=JSON.parse(event.content) as CatalogEnvelope;
      if(envelope.protocol!==DEVICE_CATALOG_PROTOCOL||envelope.recipient!==recipient||!Array.isArray(envelope.parts))continue;
      const entry=decryptPayloadParts(secret,event.pubkey,envelope.parts);
      if(!validEntry(entry,workspaceId) || !trustedPublisher(channel,event,entry,userId))continue;
      if (!channel.trustedPublishers.includes(event.pubkey.toLowerCase())) {
        const delegated = verifyChain(entry.capability.delegationChain || [],recipient);
        if (delegated.grant.userId !== userId || delegated.grant.boardId !== entry.board.id
          || delegated.grant.workspaceId !== workspaceId || delegated.grant.epoch !== entry.capability.capabilityEpoch) continue;
      }
      const current=entries.get(entry.board.id);
      if(!current || current.entry.capability.capabilityEpoch < entry.capability.capabilityEpoch
        || (current.entry.capability.capabilityEpoch === entry.capability.capabilityEpoch
          && (current.createdAt < event.created_at || (current.createdAt === event.created_at && current.eventId < event.id))))
        entries.set(entry.board.id,{entry,createdAt:event.created_at,eventId:event.id});
    }catch{/* another protocol version or incomplete relay write */}
  }
  const cached=await loadCachedBoards(workspaceId), boards=new Map(cached.map(board=>[board.id,board]));
  for(const {entry} of entries.values()){
    try {
      await installRoamingCapability(entry.capability);
      boards.set(entry.board.id,entry.board);
    } catch { /* A stale key/epoch cannot replace an installed newer capability. */ }
  }
  const result=[...boards.values()].sort((a,b)=>a.createdAt.localeCompare(b.createdAt)||a.id.localeCompare(b.id));
  await saveCachedBoards(workspaceId,result);
  return result;
}

/** Discover entire owned workspaces from signed, encrypted catalogs. */
export async function refreshWorkspaceCatalog(userId: string): Promise<Workspace[]> {
  const cached = await loadCachedWorkspaces();
  const channel = await loadRoamingCatalogChannel();
  if (!channel?.relays.length || !channel.trustedPublishers.length) return cached;
  const secret = await getOrCreateRoamingDeviceSecret(generateSecretKey), recipient = getPublicKey(secret);
  const response = await fetchDeviceCatalogEvents({relays:channel.relays,kind:channel.eventKind,recipient});
  const workspaces = new Map(cached.map(workspace => [workspace.id,workspace]));
  const boards = new Map<string, Map<string,Board>>();
  // Verify before deduplication, then apply only the newest authenticated entry.
  const entries = new Map<string, {entry: CatalogEntry & {
    workspace: {id:string;name:string;description?:string|null;visibility:string};
  }; signedAt:number; eventId:string}>();
  for (const event of response.events) {
    try {
      if (!addressedTo(event,recipient)) continue;
      const envelope=JSON.parse(event.content) as CatalogEnvelope;
      if(envelope.protocol!==DEVICE_CATALOG_PROTOCOL||envelope.recipient!==recipient||!Array.isArray(envelope.parts))continue;
      const entry=decryptPayloadParts(secret,event.pubkey,envelope.parts) as CatalogEntry & {
        workspace?:{id:string;name:string;description?:string|null;visibility:string};
        introductionChain?:Event[];
      };
      if (!validEntry(entry,entry.workspaceId) || !entry.workspace ||
        entry.workspace.id!==entry.workspaceId || !entry.workspace.name?.trim() ||
        !['private','shared'].includes(entry.workspace.visibility)) continue;
      if (!trustedPublisher(channel,event,entry,userId)) continue;
      const delegation=verifyChain(entry.capability.delegationChain || [],recipient);
      if(delegation.grant.userId!==userId || delegation.grant.boardId!==entry.board.id ||
        delegation.grant.workspaceId!==entry.workspaceId ||
        delegation.grant.epoch!==entry.capability.capabilityEpoch) continue;
      const current = entries.get(entry.board.id);
      if (!current || current.entry.capability.capabilityEpoch < entry.capability.capabilityEpoch
        || (current.entry.capability.capabilityEpoch === entry.capability.capabilityEpoch
          && (current.signedAt < event.created_at || (current.signedAt === event.created_at && current.eventId < event.id)))) {
        entries.set(entry.board.id, {entry: entry as NonNullable<typeof current>['entry'],
          signedAt: event.created_at, eventId:event.id});
      }
    } catch { /* malformed or stale catalog cannot change the local replica */ }
  }
  for (const {entry} of entries.values()) {
    try { await installRoamingCapability(entry.capability); }
    catch { continue; }
    const old = workspaces.get(entry.workspaceId);
    // Existing shared/member metadata must not be promoted to owner by a catalog.
    if (!old) workspaces.set(entry.workspaceId, {
      id:entry.workspaceId,name:entry.workspace.name,description:entry.workspace.description || null,
      visibility:entry.workspace.visibility as Workspace['visibility'],ownerUserId:userId,
      currentUserRole:'owner',isArchived:false,createdAt:entry.publishedAt,
      updatedAt:entry.publishedAt,accessEpoch:entry.capability.capabilityEpoch,
    });
    const group=boards.get(entry.workspaceId)||new Map<string,Board>();
    group.set(entry.board.id,entry.board);boards.set(entry.workspaceId,group);
  }
  for (const [workspaceId, entries] of boards) {
    const existing=await loadCachedBoards(workspaceId);
    await saveCachedBoards(workspaceId,[...new Map([...existing,...entries.values()].map(board=>[board.id,board])).values()]);
  }
  const result=[...workspaces.values()].sort((a,b)=>a.createdAt.localeCompare(b.createdAt)||a.id.localeCompare(b.id));
  await saveCachedWorkspaces(result);
  return result;
}
