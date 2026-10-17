import { apiRequest } from '../../shared/api/client';
import type { ProjectBoardPayload } from '../../shared/api/types';

interface BundleOrigin { boardRevision?: unknown; lastPatchId?: unknown; generatedAt?: unknown }

/**
 * Desktop: the copy compiled into abl (`desktop_api_project_board`).
 * Web transport: the node's `GET /project-board` answers with the board file itself.
 */
export async function getProjectBoard(): Promise<ProjectBoardPayload> {
  const value = await apiRequest<Record<string, unknown>>('/project-board');
  if (typeof value.raw === 'string') return value as unknown as ProjectBoardPayload;
  const origin = (value.origin ?? {}) as BundleOrigin;
  const raw = JSON.stringify(value);
  return {
    source: 'node',
    revision: String(origin.boardRevision ?? ''),
    lastPatchId: String(origin.lastPatchId ?? ''),
    generatedAt: String(origin.generatedAt ?? ''),
    sha256: '',
    bytes: String(raw.length),
    raw,
  };
}
