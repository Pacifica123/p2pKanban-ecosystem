export const paths = {
  home: '/',
  userAppearance: '/settings/appearance',
  network: '/settings/network',
  workspaceBoards: (workspaceId: string) => `/workspaces/${workspaceId}/boards`,
  workspaceAccess: (workspaceId: string) => `/workspaces/${workspaceId}/access`,
  invitation: (token: string) => `/invite/${encodeURIComponent(token)}`,
  board: (workspaceId: string, boardId: string) => `/workspaces/${workspaceId}/boards/${boardId}`,
  boardAppearance: (workspaceId: string, boardId: string) => `/workspaces/${workspaceId}/boards/${boardId}/customize`,
};
