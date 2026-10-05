export interface BackendVersion {
  status: string;
  service: string;
  version: string;
  env: string;
}


export interface ProfileDiagnostics {
  dataRoot: string;
  configRoot: string;
  stateRoot: string;
  cacheRoot: string;
  profileDatabase: string;
  runtimeActivation: 'available' | 'unavailable';
}


export interface IntegrationCapabilities {
  sessionType: 'wayland' | 'x11' | 'unknown';
  desktop: string;
  sessionBus: 'available' | 'unavailable';
  notifications: 'available' | 'unavailable';
  statusNotifier: 'available' | 'unavailable';
  portal: 'available' | 'unavailable';
  runtimeActivation: 'available' | 'unavailable';
  trayLifecycle: 'disabled';
  systemdUserService: 'disabled';
}

export interface DeepLinkIntentSummary {
  kind: 'activate' | 'workspace' | 'board' | 'card';
  entityId: string;
  canonical: string;
}

export interface WorkspaceSummary {
  id: string;
  title: string;
  accessEpoch: string;
}

export interface BoardSummary {
  id: string;
  workspaceId: string;
  title: string;
}

export interface VaultStatus {
  mode: 'session-only' | 'secret-service' | 'passphrase';
  state: 'ready' | 'provider-unavailable' | 'provider-locked' | 'provider-corrupt' | 'passphrase-required';
  durable: 'true' | 'false';
  passphraseFallbackAvailable: 'true' | 'false';
}

export interface ColumnSummary {
  id: string;
  boardId: string;
  title: string;
  position: string;
}

export interface CardSummary {
  id: string;
  workspaceId: string;
  boardId: string;
  columnId: string;
  title: string;
  position: string;
  archived: 'true' | 'false';
}

export interface ChecklistSummary {
  id: string;
  cardId: string;
  title: string;
  position: string;
}

export interface ChecklistItemSummary {
  id: string;
  checklistId: string;
  title: string;
  position: string;
  isDone: 'true' | 'false';
}

export interface PendingChangeCount {
  count: string;
}

export interface LabelSummary {
  id: string;
  boardId: string;
  name: string;
  color: string;
  position: string;
}

export interface CommentSummary {
  id: string;
  cardId: string;
  authorUserId: string;
  body: string;
  createdAt: string;
  updatedAt: string;
}

export interface AppearanceSummary {
  boardId: string;
  settingsJson: string;
  updatedAt: string;
}

export interface ActivitySummary {
  id: string;
  boardId: string;
  cardId: string;
  actorUserId: string;
  kind: string;
  entityType: string;
  entityId: string;
  payloadJson: string;
  occurredAt: string;
}

export interface ParityUnsyncedCount {
  count: string;
}


export interface LanBridgeStatus {
  lifecycle: 'stopped' | 'listening' | 'completed' | 'expired' | 'failed';
  bindAddress: string;
  endpoint: string;
  expiresAtUnix: string;
  attempts: string;
  lastResult: string;
}

export interface LanBridgeStartResult extends LanBridgeStatus {
  capability: string;
  devicePublicKey: string;
}
