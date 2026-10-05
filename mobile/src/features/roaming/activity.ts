import type {ActivityEntry} from '../../shared/types/api';
import type {LocalOperation} from '../localFirst/model';
import type {RoamingBoardEvent} from './types';

export function operationActivity(operation: LocalOperation, event: RoamingBoardEvent): ActivityEntry {
  const delta = event.payload.checklistDelta as {kind?:string;checklistId?:string;itemId?:string} | undefined;
  const kinds: Record<string,string> = {'card.create':'card.created','card.update':'card.updated',
    'card.move':'card.moved','card.archive':'card.archived','card.unarchive':'card.restored',
    'card.delete':'card.deleted','board.appearance.update':'board.appearance.updated',
    'checklist.create':'checklist.created','checklist.update':'checklist.updated','checklist.delete':'checklist.deleted',
    'checklist.item.create':'checklist_item.created','checklist.item.delete':'checklist_item.deleted'};
  const kind = operation.kind === 'checklist.item.update'
    ? (operation.payload.input.isDone === true ? 'checklist_item.completed'
      : operation.payload.input.isDone === false ? 'checklist_item.reopened' : 'checklist_item.updated')
    : kinds[operation.kind];
  return {id:event.eventId,createdAt:event.occurredAt,kind:kind || 'card.updated',boardId:event.boardId,
    cardId:event.entityType === 'card' ? event.entityId : null,
    entityType:delta?.itemId ? 'checklist_item' : delta ? 'checklist' : event.entityType,
    entityId:delta?.itemId || delta?.checklistId || event.entityId,
    actor:operation.actor || {userId:null,displayName:null},
    fieldMask:delta ? ((event.payload.checklistDelta as {fieldMask:string[]}).fieldMask) : event.fieldMask};
}

