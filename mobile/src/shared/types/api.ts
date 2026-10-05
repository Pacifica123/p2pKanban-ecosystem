export interface PageInfo {
  nextCursor?: string | null;
  hasNextPage?: boolean;
}

export interface AuthUser {
  id: string;
  email: string;
  displayName: string;
}

export interface NativeAuthSuccessResponse {
  authenticated: true;
  mode: 'native_refresh_token_plus_bearer' | string;
  accessToken: string;
  accessTokenExpiresAt: string;
  refreshToken: string;
  sessionId: string;
  deviceId: string;
  user: AuthUser;
}

export interface SessionResponse {
  authenticated: boolean;
  mode: string;
  sessionId: string | null;
  deviceId: string | null;
  user: AuthUser | null;
}

export interface Workspace {
  id: string;
  name: string;
  slug?: string | null;
  description?: string | null;
  visibility: 'private' | 'shared';
  ownerUserId: string;
  memberCount?: number;
  currentUserRole?: 'owner' | 'member' | 'guest' | null;
  accessEpoch?: number;
  isArchived: boolean;
  createdAt: string;
  updatedAt: string;
  archivedAt?: string | null;
}

export interface WorkspaceListResponse {
  items: Workspace[];
  pageInfo: PageInfo;
}

export type WorkspaceRole = 'owner' | 'member' | 'guest';

export interface WorkspaceMember {
  id: string;
  workspaceId: string;
  userId: string;
  displayName: string;
  email: string;
  role: WorkspaceRole;
  status: 'active' | 'removed';
  invitedByUserId?: string | null;
  createdAt: string;
  updatedAt: string;
  removedAt?: string | null;
}

export interface WorkspaceMembersListResponse {
  items: WorkspaceMember[];
  pageInfo: PageInfo;
}

export interface WorkspaceInvitation {
  id: string;
  workspaceId: string;
  role: 'member' | 'guest';
  status: 'active' | 'accepted' | 'revoked' | 'expired';
  createdByUserId: string;
  expiresAt: string;
  createdAt: string;
  revokedAt?: string | null;
  acceptedAt?: string | null;
  acceptedByUserId?: string | null;
}

export interface WorkspaceInvitationsListResponse {
  items: WorkspaceInvitation[];
  pageInfo: PageInfo;
}

export interface CreatedWorkspaceInvitationResponse {
  invitation: WorkspaceInvitation;
  token: string;
}

export interface Board {
  id: string;
  workspaceId: string;
  name: string;
  description?: string | null;
  boardType: 'kanban';
  isArchived: boolean;
  labelIds?: string[];
  checklistCount?: number;
  checklistCompletedItemCount?: number;
  commentCount?: number;
  createdByUserId?: string | null;
  createdAt: string;
  updatedAt: string;
  archivedAt?: string | null;
}

export interface BoardListResponse {
  items: Board[];
  pageInfo: PageInfo;
}

export interface BoardColumn {
  id: string;
  boardId: string;
  name: string;
  description?: string | null;
  position: number;
  colorToken?: string | null;
  wipLimit?: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface ColumnListResponse {
  items: BoardColumn[];
}

export type CardPriority = 'low' | 'medium' | 'high' | 'urgent' | null;

export interface Card {
  id: string;
  boardId: string;
  columnId: string;
  parentCardId?: string | null;
  title: string;
  description?: string | null;
  priority: CardPriority;
  position: number;
  startAt?: string | null;
  dueAt?: string | null;
  isArchived: boolean;
  labelIds?: string[];
  checklistCount?: number;
  checklistItemCount?: number;
  checklistCompletedItemCount?: number;
  commentCount?: number;
  createdByUserId?: string | null;
  createdAt: string;
  updatedAt: string;
  archivedAt?: string | null;
}

export interface CardListResponse {
  items: Card[];
  pageInfo: PageInfo;
}

export interface ChecklistItem {
  id: string;
  checklistId: string;
  title: string;
  isDone: boolean;
  position: number;
  completedAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface Checklist {
  id: string;
  cardId: string;
  title: string;
  position: number;
  items: ChecklistItem[];
  createdAt: string;
  updatedAt: string;
}

export interface ChecklistListResponse {
  items: Checklist[];
}

export interface BoardLabel {
  id: string;
  boardId: string;
  name: string;
  color: string;
  description?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface BoardLabelListResponse {
  items: BoardLabel[];
}

export interface Comment {
  id: string;
  cardId: string;
  authorUserId?: string | null;
  body: string;
  createdAt: string;
  updatedAt: string;
  editedAt?: string | null;
}

export interface CommentListResponse {
  items: Comment[];
  pageInfo: PageInfo;
}

export interface ActivityActor {
  userId: string | null;
  displayName: string | null;
}

export interface ActivityEntry {
  id: string;
  createdAt: string;
  kind: string;
  boardId: string;
  cardId: string | null;
  entityType: string;
  entityId: string;
  actor: ActivityActor;
  fieldMask: string[];
}

export interface ActivityListResponse {
  items: ActivityEntry[];
  nextCursor: string | null;
}

export interface Replica {
  id: string;
  replicaKey?: string | null;
  kind: string;
  status: 'active' | 'disabled';
  displayName?: string | null;
  platform?: string | null;
  lastSeenAt?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface SyncStatusResponse {
  healthy: boolean;
  mode: string;
  serverTime: string;
  maxServerOrder?: number | null;
  replica?: Replica | null;
}

export interface RoamingCapabilityResponse {
  formatVersion: 1;
  protocolVersion: 'p2p-kanban-roaming/1';
  workspaceId: string;
  boardId: string;
  boardTag: string;
  boardKey: string;
  capabilityEpoch: number;
  canWrite: boolean;
  writerPublicKeys: string[];
  relays: string[];
  eventKind: number;
  minimumRelayAcks: number;
  provisionedAt: string;
}

export interface BackendVersionResponse {
  status: string;
  service: string;
  version: string;
  env: string;
}

export type AppTheme = 'system' | 'light' | 'dark';
export type Density = 'comfortable' | 'compact';
export type ChecklistItemSubmitMode = 'ctrl_enter' | 'enter' | 'button';
export type CardDetailsMode = 'drawer' | 'modal';
export type WallpaperKind = 'none' | 'accent' | 'solid' | 'gradient' | 'preset' | 'image';
export type CardPreviewMode = 'compact' | 'expanded';

export interface WallpaperConfig {
  kind: WallpaperKind;
  value?: string | null;
}

export interface UserAppearancePreferences {
  userId: string;
  isCustomized: boolean;
  appTheme: AppTheme;
  density: Density;
  reduceMotion: boolean;
  checklistItemSubmitMode: ChecklistItemSubmitMode;
  cardDetailsMode: CardDetailsMode;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export type UpdateUserAppearancePreferencesRequest = Partial<Pick<
  UserAppearancePreferences,
  'appTheme' | 'density' | 'reduceMotion' | 'checklistItemSubmitMode' | 'cardDetailsMode'
>>;

export interface BoardAppearanceSettings {
  boardId: string;
  isCustomized: boolean;
  themePreset: string;
  wallpaper: WallpaperConfig;
  columnDensity: Density;
  cardPreviewMode: CardPreviewMode;
  showCardDescription: boolean;
  showCardDates: boolean;
  showChecklistProgress: boolean;
  customProperties: Record<string, unknown>;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export type UpdateBoardAppearanceRequest = Partial<Pick<
  BoardAppearanceSettings,
  | 'themePreset'
  | 'wallpaper'
  | 'columnDensity'
  | 'cardPreviewMode'
  | 'showCardDescription'
  | 'showCardDates'
  | 'showChecklistProgress'
  | 'customProperties'
>>;
