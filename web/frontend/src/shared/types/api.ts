export interface PageInfo {
  nextCursor?: string | null;
  prevCursor?: string | null;
  hasNextPage?: boolean;
  hasPrevPage?: boolean;
}

export interface Workspace {
  id: string;
  name: string;
  slug?: string | null;
  description?: string | null;
  visibility: 'private' | 'shared';
  ownerUserId: string;
  memberCount?: number;
  currentUserRole?: WorkspaceRole | null;
  accessEpoch?: number;
  isArchived: boolean;
  createdAt: string;
  updatedAt: string;
  archivedAt?: string | null;
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
  role: Exclude<WorkspaceRole, 'owner'>;
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

export interface WorkspaceInvitationPreview {
  workspaceId: string;
  workspaceName: string;
  role: Exclude<WorkspaceRole, 'owner'>;
  status: WorkspaceInvitation['status'];
  expiresAt: string;
}

export interface WorkspaceListResponse {
  items: Workspace[];
  pageInfo: PageInfo;
}

export interface Board {
  id: string;
  workspaceId: string;
  name: string;
  description?: string | null;
  boardType: 'kanban';
  isArchived: boolean;
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


export interface BoardLabel {
  id: string;
  boardId: string;
  name: string;
  color: string;
  description?: string | null;
  createdAt?: string;
  updatedAt?: string;
}

export interface BoardLabelListResponse {
  items: BoardLabel[];
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
  workspaceId: string;
  boardId: string;
  cardId: string | null;
  entityType: string;
  entityId: string;
  actor: ActivityActor;
  fieldMask: string[];
  payload: Record<string, unknown>;
  requestId: string | null;
}

export interface ActivityListResponse {
  items: ActivityEntry[];
  nextCursor: string | null;
}

export interface ProductivityDay {
  date: string;
  actionCount: number;
}

export interface BoardProductivityResponse {
  days: ProductivityDay[];
  totalActions: number;
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

export interface UpdateUserAppearancePreferencesRequest {
  appTheme?: AppTheme;
  density?: Density;
  reduceMotion?: boolean;
  checklistItemSubmitMode?: ChecklistItemSubmitMode;
  cardDetailsMode?: CardDetailsMode;
}

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

export interface UpdateBoardAppearanceRequest {
  themePreset?: string;
  wallpaper?: WallpaperConfig;
  columnDensity?: Density;
  cardPreviewMode?: CardPreviewMode;
  showCardDescription?: boolean;
  showCardDates?: boolean;
  showChecklistProgress?: boolean;
  customProperties?: Record<string, unknown>;
}


export interface IntegrationProviderSummary {
  key: string;
  displayName: string;
  providerType: 'third_party' | 'system';
  status: 'stub' | 'planned' | 'active';
  authMode: string;
  supportsImport: boolean;
  supportsExport: boolean;
  supportsInboundWebhooks: boolean;
  supportsOutboundWebhooks: boolean;
}

export interface IntegrationTouchpoint {
  key: string;
  direction: 'import' | 'export' | 'bidirectional';
  payloadFormat: string;
  description: string;
  status: 'stub' | 'planned' | 'active';
}

export interface DomainEventSubscription {
  eventType: string;
  deliveryMode: 'pull' | 'batch' | 'outbox' | 'push';
  purpose: string;
}

export interface WebhookContract {
  mode: 'inbound' | 'outbound';
  signatureScheme: string;
  eventTypes: string[];
  description: string;
}

export interface IntegrationProviderCatalogResponse {
  items: IntegrationProviderSummary[];
}

export interface IntegrationProviderDetailResponse {
  provider: IntegrationProviderSummary;
  importTouchpoints: IntegrationTouchpoint[];
  exportTouchpoints: IntegrationTouchpoint[];
  domainEventSubscriptions: DomainEventSubscription[];
  inboundWebhook?: WebhookContract | null;
  outboundWebhook?: WebhookContract | null;
  boundaryRules: string[];
  notes: string[];
}

export interface CreateImportJobRequest {
  providerKey: string;
  workspaceId?: string | null;
  sourceRef?: string | null;
  options?: Record<string, unknown>;
}

export interface CreateExportJobRequest {
  providerKey: string;
  workspaceId?: string | null;
  targetRef?: string | null;
  options?: Record<string, unknown>;
}

export interface IntegrationOperationStubResponse {
  operation: string;
  providerKey: string;
  status: 'stub_only';
  message: string;
}

export interface WebhookReceiptResponse {
  providerKey: string;
  status: 'stub_only';
  message: string;
  acceptedEventTypes: string[];
}


export interface PortableEntityCounts {
  workspaces: number;
  boards: number;
  columns: number;
  cards: number;
  comments: number;
  checklists: number;
  attachments: number;
}

export interface PortableBundleSummary {
  scopeKind: 'workspace' | 'board';
  entityCounts: PortableEntityCounts;
  includesActivityHistory: boolean;
  includesAppearance: boolean;
  includesArchived: boolean;
  includesAttachments: boolean;
}

export interface PortableBundleManifest {
  format: 'p2p_planner_bundle';
  formatVersion: 1;
  bundleKind: 'portable_export' | 'backup_snapshot';
  scopeKind: 'workspace' | 'board';
  workspaceId?: string | null;
  boardId?: string | null;
  includesLocalMetadata: boolean;
  summary: PortableBundleSummary;
}

export interface PortableBundlePayload {
  workspaces: Record<string, unknown>[];
  boards: Record<string, unknown>[];
  columns: Record<string, unknown>[];
  cards: Record<string, unknown>[];
  labels: Record<string, unknown>[];
  cardLabels: Record<string, unknown>[];
  checklists: Record<string, unknown>[];
  checklistItems: Record<string, unknown>[];
  comments: Record<string, unknown>[];
  boardAppearanceSettings: Record<string, unknown>[];
  activityEntries: Record<string, unknown>[];
}

export interface PortableBundle {
  'manifest.json': PortableBundleManifest;
  scope: {
    scopeKind: 'workspace' | 'board';
    workspaceId?: string | null;
    boardId?: string | null;
  };
  origin: {
    exportedByUserId: string;
    generatedAt: string;
    backendVisibleState: boolean;
  };
  includes: {
    appearance: boolean;
    activityHistory: boolean;
    archived: boolean;
    attachments: boolean;
    localMetadata: boolean;
  };
  payload: PortableBundlePayload;
  restoreHints: {
    recommendedStrategy: 'create_copy';
    requiresManualReview: boolean;
    destructiveRestoreAllowed: boolean;
    notes: string[];
  };
}

export interface ImportExportCapabilitiesResponse {
  providerKey: 'import_export';
  format: 'p2p_planner_bundle';
  formatVersion: 1;
  supportedExportModes: Array<'portable_export' | 'backup_snapshot'>;
  clientOnlyBackupModes: Array<'local_backup_snapshot'>;
  supportedImportModes: Array<'portable_import' | 'restore_backup'>;
  supportedScopeKinds: Array<'workspace' | 'board'>;
  supportedRestoreStrategies: Array<'create_copy' | 'merge_review'>;
  maxBundleSizeBytes?: number | null;
  notes: string[];
}

export interface CreatePortableExportRequest {
  scopeKind: 'workspace' | 'board';
  workspaceId?: string | null;
  boardId?: string | null;
  exportMode: 'portable_export' | 'backup_snapshot';
  includeArchived?: boolean;
  includeActivityHistory?: boolean;
  includeAppearance?: boolean;
  includeAttachments?: boolean;
  targetRef?: string | null;
}

export interface PortableExportResponse {
  jobId: string;
  providerKey: 'import_export';
  status: 'ready';
  exportMode: 'portable_export' | 'backup_snapshot';
  suggestedFileName: string;
  targetRef?: string | null;
  bundleManifest: PortableBundleManifest;
  bundle: PortableBundle;
  message: string;
  warnings: string[];
}

export interface CreateImportPreviewRequest {
  sourceRef?: string | null;
  importMode: 'portable_import' | 'restore_backup';
  targetWorkspaceId?: string | null;
  restoreStrategy: 'create_copy' | 'merge_review';
  bundleManifest?: Record<string, unknown>;
  bundle?: Record<string, unknown>;
  options?: Record<string, unknown>;
}

export interface ImportPreviewResponse {
  previewId: string;
  providerKey: 'import_export';
  status: 'preview_ready' | 'preview_needs_bundle';
  detectedFormat: 'p2p_planner_bundle';
  detectedFormatVersion: 1;
  importMode: 'portable_import' | 'restore_backup';
  restoreStrategy: 'create_copy' | 'merge_review';
  requiresManualReview: boolean;
  warnings: string[];
  steps: string[];
  summary: PortableBundleSummary;
}

export interface CreateImportExecutionRequest {
  sourceRef?: string | null;
  importMode: 'portable_import' | 'restore_backup';
  targetWorkspaceId?: string | null;
  restoreStrategy: 'create_copy' | 'merge_review';
  previewId?: string | null;
  bundleManifest?: Record<string, unknown>;
  options?: Record<string, unknown>;
}

export interface ImportExecutionResponse {
  jobId: string;
  providerKey: 'import_export';
  status: 'preview_required';
  importMode: 'portable_import' | 'restore_backup';
  restoreStrategy: 'create_copy' | 'merge_review';
  previewId?: string | null;
  targetWorkspaceId?: string | null;
  message: string;
  warnings: string[];
}


export interface AuthUser {
  id: string;
  email: string;
  displayName: string;
}

export interface SignInRequest {
  email: string;
  password: string;
}

export interface SignUpRequest {
  email: string;
  password: string;
  displayName: string;
}

export interface NodeLinkImportRequest {
  sourceUrl: string;
  email: string;
  password: string;
}

export interface AuthSuccessResponse {
  authenticated: boolean;
  mode: string;
  accessToken: string;
  accessTokenExpiresAt: string;
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

export interface SignOutResponse {
  signedOut: boolean;
  mode: string;
}
