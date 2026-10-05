import { invoke } from '@tauri-apps/api/core';
import { ApiError } from '../api/errors';
import type {
  ActivitySummary,
  AppearanceSummary,
  BackendVersion,
  BoardSummary,
  CardSummary,
  ChecklistItemSummary,
  ChecklistSummary,
  ColumnSummary,
  CommentSummary,
  DeepLinkIntentSummary,
  IntegrationCapabilities,
  LabelSummary,
  LanBridgeStartResult,
  LanBridgeStatus,
  ParityUnsyncedCount,
  PendingChangeCount,
  ProfileDiagnostics,
  VaultStatus,
  WorkspaceSummary,
} from '../api/types';
import type { ApiTransport } from './types';
import { requestMethod } from './types';

const DESKTOP_HEALTH_COMMAND = 'desktop_api_health' as const;
const DESKTOP_PROFILE_DIAGNOSTICS_COMMAND = 'desktop_api_profile_diagnostics' as const;
const DESKTOP_VAULT_STATUS_COMMAND = 'desktop_api_vault_status' as const;
const DESKTOP_INTEGRATION_CAPABILITIES_COMMAND = 'desktop_api_integration_capabilities' as const;
const DESKTOP_TAKE_DEEP_LINK_INTENTS_COMMAND = 'desktop_api_take_deep_link_intents' as const;
const DESKTOP_LAN_BRIDGE_ADDRESSES_COMMAND = 'desktop_api_lan_bridge_addresses' as const;
const DESKTOP_LAN_BRIDGE_STATUS_COMMAND = 'desktop_api_lan_bridge_status' as const;
const DESKTOP_START_LAN_BRIDGE_COMMAND = 'desktop_api_start_lan_bridge' as const;
const DESKTOP_STOP_LAN_BRIDGE_COMMAND = 'desktop_api_stop_lan_bridge' as const;
const DESKTOP_LIST_WORKSPACES_COMMAND = 'desktop_api_list_workspaces' as const;
const DESKTOP_CREATE_WORKSPACE_COMMAND = 'desktop_api_create_workspace' as const;
const DESKTOP_LIST_BOARDS_COMMAND = 'desktop_api_list_boards' as const;
const DESKTOP_CREATE_BOARD_COMMAND = 'desktop_api_create_board' as const;
const DESKTOP_OPEN_BOARD_COMMAND = 'desktop_api_open_board' as const;

const DESKTOP_LIST_COLUMNS_COMMAND = 'desktop_api_list_columns' as const;
const DESKTOP_CREATE_COLUMN_COMMAND = 'desktop_api_create_column' as const;
const DESKTOP_LIST_CARDS_COMMAND = 'desktop_api_list_cards' as const;
const DESKTOP_CREATE_CARD_COMMAND = 'desktop_api_create_card' as const;
const DESKTOP_MOVE_CARD_COMMAND = 'desktop_api_move_card' as const;
const DESKTOP_SWAP_CARD_ORDER_COMMAND = 'desktop_api_swap_card_order' as const;
const DESKTOP_SET_CARD_ARCHIVED_COMMAND = 'desktop_api_set_card_archived' as const;
const DESKTOP_DELETE_CARD_COMMAND = 'desktop_api_delete_card' as const;
const DESKTOP_LIST_CHECKLISTS_COMMAND = 'desktop_api_list_checklists' as const;
const DESKTOP_CREATE_CHECKLIST_COMMAND = 'desktop_api_create_checklist' as const;
const DESKTOP_DELETE_CHECKLIST_COMMAND = 'desktop_api_delete_checklist' as const;
const DESKTOP_LIST_CHECKLIST_ITEMS_COMMAND = 'desktop_api_list_checklist_items' as const;
const DESKTOP_CREATE_CHECKLIST_ITEM_COMMAND = 'desktop_api_create_checklist_item' as const;
const DESKTOP_SET_CHECKLIST_ITEM_DONE_COMMAND = 'desktop_api_set_checklist_item_done' as const;
const DESKTOP_DELETE_CHECKLIST_ITEM_COMMAND = 'desktop_api_delete_checklist_item' as const;
const DESKTOP_PENDING_CHANGE_COUNT_COMMAND = 'desktop_api_pending_change_count' as const;

const DESKTOP_LIST_LABELS_COMMAND = 'desktop_api_list_labels' as const;
const DESKTOP_CREATE_LABEL_COMMAND = 'desktop_api_create_label' as const;
const DESKTOP_DELETE_LABEL_COMMAND = 'desktop_api_delete_label' as const;
const DESKTOP_LIST_CARD_LABEL_IDS_COMMAND = 'desktop_api_list_card_label_ids' as const;
const DESKTOP_SET_CARD_LABEL_COMMAND = 'desktop_api_set_card_label' as const;
const DESKTOP_LIST_COMMENTS_COMMAND = 'desktop_api_list_comments' as const;
const DESKTOP_CREATE_COMMENT_COMMAND = 'desktop_api_create_comment' as const;
const DESKTOP_DELETE_COMMENT_COMMAND = 'desktop_api_delete_comment' as const;
const DESKTOP_GET_APPEARANCE_COMMAND = 'desktop_api_get_appearance' as const;
const DESKTOP_SET_APPEARANCE_COMMAND = 'desktop_api_set_appearance' as const;
const DESKTOP_LIST_ACTIVITY_COMMAND = 'desktop_api_list_activity' as const;
const DESKTOP_UNSYNCED_PARITY_COUNT_COMMAND = 'desktop_api_unsynced_parity_count' as const;

function unsupported(path: string, method: string): never {
  throw new ApiError(`Desktop route is not implemented yet: ${method} ${path}`, {
    status: 0,
    code: 'DESKTOP_ROUTE_UNSUPPORTED',
  });
}

function jsonBody<T extends Record<string, unknown>>(init?: RequestInit): T {
  if (typeof init?.body !== 'string') {
    throw new ApiError('Desktop JSON request body is required.', {
      status: 0,
      code: 'DESKTOP_BODY_REQUIRED',
    });
  }
  try {
    const parsed = JSON.parse(init.body) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('body is not an object');
    }
    return parsed as T;
  } catch {
    throw new ApiError('Desktop JSON request body is invalid.', {
      status: 0,
      code: 'DESKTOP_BODY_INVALID',
    });
  }
}

export const desktopTransport: ApiTransport = {
  kind: 'desktop',
  async request<T>(path: string, init?: RequestInit) {
    const method = requestMethod(init);
    if (method === 'GET' && path === '/health') {
      return (await invoke<BackendVersion>(DESKTOP_HEALTH_COMMAND)) as T;
    }
    if (method === 'GET' && path === '/system/profile-diagnostics') {
      return (await invoke<ProfileDiagnostics>(DESKTOP_PROFILE_DIAGNOSTICS_COMMAND)) as T;
    }
    if (method === 'GET' && path === '/system/vault-status') {
      return (await invoke<VaultStatus>(DESKTOP_VAULT_STATUS_COMMAND)) as T;
    }
    if (method === 'GET' && path === '/system/integration-capabilities') {
      return (await invoke<IntegrationCapabilities>(DESKTOP_INTEGRATION_CAPABILITIES_COMMAND)) as T;
    }
    if (method === 'POST' && path === '/system/deep-link-intents/take') {
      return (await invoke<DeepLinkIntentSummary[]>(DESKTOP_TAKE_DEEP_LINK_INTENTS_COMMAND)) as T;
    }
    if (method === 'GET' && path === '/system/lan-bridge/addresses') {
      return (await invoke<string[]>(DESKTOP_LAN_BRIDGE_ADDRESSES_COMMAND)) as T;
    }
    if (method === 'GET' && path === '/system/lan-bridge/status') {
      return (await invoke<LanBridgeStatus>(DESKTOP_LAN_BRIDGE_STATUS_COMMAND)) as T;
    }
    if (method === 'POST' && path === '/system/lan-bridge/start') {
      const body = jsonBody<{ bindAddress: string; ttlSeconds: number }>(init);
      return (await invoke<LanBridgeStartResult>(DESKTOP_START_LAN_BRIDGE_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/system/lan-bridge/stop') {
      return (await invoke<LanBridgeStatus>(DESKTOP_STOP_LAN_BRIDGE_COMMAND)) as T;
    }
    if (method === 'GET' && path === '/planner/workspaces') {
      return (await invoke<WorkspaceSummary[]>(DESKTOP_LIST_WORKSPACES_COMMAND)) as T;
    }
    if (method === 'POST' && path === '/planner/workspaces') {
      const body = jsonBody<{ title: string }>(init);
      return (await invoke<WorkspaceSummary>(DESKTOP_CREATE_WORKSPACE_COMMAND, {
        title: body.title,
      })) as T;
    }
    if (method === 'POST' && path === '/planner/boards/list') {
      const body = jsonBody<{ workspaceId: string }>(init);
      return (await invoke<BoardSummary[]>(DESKTOP_LIST_BOARDS_COMMAND, {
        workspaceId: body.workspaceId,
      })) as T;
    }
    if (method === 'POST' && path === '/planner/boards') {
      const body = jsonBody<{ workspaceId: string; title: string }>(init);
      return (await invoke<BoardSummary>(DESKTOP_CREATE_BOARD_COMMAND, {
        workspaceId: body.workspaceId,
        title: body.title,
      })) as T;
    }
    if (method === 'POST' && path === '/planner/boards/open') {
      const body = jsonBody<{ workspaceId: string; boardId: string }>(init);
      return (await invoke<BoardSummary>(DESKTOP_OPEN_BOARD_COMMAND, {
        workspaceId: body.workspaceId,
        boardId: body.boardId,
      })) as T;
    }

    if (method === 'POST' && path === '/planner/columns/list') {
      const body = jsonBody<{ workspaceId: string; boardId: string }>(init);
      return (await invoke<ColumnSummary[]>(DESKTOP_LIST_COLUMNS_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/columns') {
      const body = jsonBody<{ workspaceId: string; boardId: string; title: string }>(init);
      return (await invoke<ColumnSummary>(DESKTOP_CREATE_COLUMN_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/cards/list') {
      const body = jsonBody<{ workspaceId: string; boardId: string; includeArchived: boolean }>(init);
      return (await invoke<CardSummary[]>(DESKTOP_LIST_CARDS_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/cards') {
      const body = jsonBody<{ workspaceId: string; boardId: string; columnId: string; title: string }>(init);
      return (await invoke<CardSummary>(DESKTOP_CREATE_CARD_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/cards/move') {
      const body = jsonBody<{ workspaceId: string; cardId: string; targetColumnId: string }>(init);
      return (await invoke<CardSummary>(DESKTOP_MOVE_CARD_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/cards/swap-order') {
      const body = jsonBody<{ workspaceId: string; cardId: string; otherCardId: string }>(init);
      return (await invoke<void>(DESKTOP_SWAP_CARD_ORDER_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/cards/archive') {
      const body = jsonBody<{ workspaceId: string; cardId: string; archived: boolean }>(init);
      return (await invoke<CardSummary>(DESKTOP_SET_CARD_ARCHIVED_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/cards/delete') {
      const body = jsonBody<{ workspaceId: string; cardId: string }>(init);
      return (await invoke<void>(DESKTOP_DELETE_CARD_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/checklists/list') {
      const body = jsonBody<{ workspaceId: string; cardId: string }>(init);
      return (await invoke<ChecklistSummary[]>(DESKTOP_LIST_CHECKLISTS_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/checklists') {
      const body = jsonBody<{ workspaceId: string; cardId: string; title: string }>(init);
      return (await invoke<ChecklistSummary>(DESKTOP_CREATE_CHECKLIST_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/checklists/delete') {
      const body = jsonBody<{ workspaceId: string; checklistId: string }>(init);
      return (await invoke<void>(DESKTOP_DELETE_CHECKLIST_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/checklist-items/list') {
      const body = jsonBody<{ workspaceId: string; checklistId: string }>(init);
      return (await invoke<ChecklistItemSummary[]>(DESKTOP_LIST_CHECKLIST_ITEMS_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/checklist-items') {
      const body = jsonBody<{ workspaceId: string; checklistId: string; title: string }>(init);
      return (await invoke<ChecklistItemSummary>(DESKTOP_CREATE_CHECKLIST_ITEM_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/checklist-items/done') {
      const body = jsonBody<{ workspaceId: string; itemId: string; done: boolean }>(init);
      return (await invoke<ChecklistItemSummary>(DESKTOP_SET_CHECKLIST_ITEM_DONE_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/checklist-items/delete') {
      const body = jsonBody<{ workspaceId: string; itemId: string }>(init);
      return (await invoke<void>(DESKTOP_DELETE_CHECKLIST_ITEM_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/planner/pending-count') {
      const body = jsonBody<{ workspaceId: string; boardId: string }>(init);
      return (await invoke<PendingChangeCount>(DESKTOP_PENDING_CHANGE_COUNT_COMMAND, body)) as T;
    }

    if (method === 'POST' && path === '/parity/labels/list') {
      const body = jsonBody<{ workspaceId: string; boardId: string }>(init);
      return (await invoke<LabelSummary[]>(DESKTOP_LIST_LABELS_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/labels') {
      const body = jsonBody<{ workspaceId: string; boardId: string; name: string; color: string | null }>(init);
      return (await invoke<LabelSummary>(DESKTOP_CREATE_LABEL_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/labels/delete') {
      const body = jsonBody<{ workspaceId: string; boardId: string; labelId: string }>(init);
      return (await invoke<void>(DESKTOP_DELETE_LABEL_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/card-labels/list') {
      const body = jsonBody<{ workspaceId: string; cardId: string }>(init);
      return (await invoke<string[]>(DESKTOP_LIST_CARD_LABEL_IDS_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/card-labels/set') {
      const body = jsonBody<{ workspaceId: string; cardId: string; labelId: string; assigned: boolean }>(init);
      return (await invoke<void>(DESKTOP_SET_CARD_LABEL_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/comments/list') {
      const body = jsonBody<{ workspaceId: string; cardId: string }>(init);
      return (await invoke<CommentSummary[]>(DESKTOP_LIST_COMMENTS_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/comments') {
      const body = jsonBody<{ workspaceId: string; cardId: string; body: string }>(init);
      return (await invoke<CommentSummary>(DESKTOP_CREATE_COMMENT_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/comments/delete') {
      const body = jsonBody<{ workspaceId: string; commentId: string }>(init);
      return (await invoke<void>(DESKTOP_DELETE_COMMENT_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/appearance/get') {
      const body = jsonBody<{ workspaceId: string; boardId: string }>(init);
      return (await invoke<AppearanceSummary>(DESKTOP_GET_APPEARANCE_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/appearance/set') {
      const body = jsonBody<{ workspaceId: string; boardId: string; settingsJson: string }>(init);
      return (await invoke<AppearanceSummary>(DESKTOP_SET_APPEARANCE_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/activity/list') {
      const body = jsonBody<{ workspaceId: string; boardId: string; limit: number }>(init);
      return (await invoke<ActivitySummary[]>(DESKTOP_LIST_ACTIVITY_COMMAND, body)) as T;
    }
    if (method === 'POST' && path === '/parity/unsynced-count') {
      const body = jsonBody<{ workspaceId: string; boardId: string }>(init);
      return (await invoke<ParityUnsyncedCount>(DESKTOP_UNSYNCED_PARITY_COUNT_COMMAND, body)) as T;
    }
    return unsupported(path, method);
  },
};
