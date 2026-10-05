export type RootStackParamList = {
  Connection: undefined;
  Auth: undefined;
  Workspaces: undefined;
  Boards: {
    workspaceId: string;
    workspaceName: string;
    workspaceRole?: 'owner' | 'member' | 'guest';
    accessEpoch?: number;
  };
  Board: {
    workspaceId: string;
    boardId: string;
    boardName: string;
    workspaceRole?: 'owner' | 'member' | 'guest';
    accessEpoch?: number;
    focusCardId?: string;
  };
  WorkspaceAccess: {
    workspaceId: string;
    workspaceName: string;
  };
  Activity: {
    boardId: string;
    boardName: string;
  };
  Settings: undefined;
};
