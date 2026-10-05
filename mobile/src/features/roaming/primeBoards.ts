import type { Board } from '../../shared/types/api';
import { getApiNodeOrigin } from '../../shared/api/client';
import { isPrivateNodeOrigin } from '../connection/connection';
import {
  loadBoardSnapshot,
  loadOperationQueue,
  persistServerSnapshot,
  serializeLocalState,
} from '../localFirst/repository';
import { fetchBoardSnapshot } from '../localFirst/snapshot';
import {
  installRoamingCapability,
  getRoamingAuthorPublicKey,
  loadRoamingCapability,
  publishBoardSnapshot,
  pullRoamingBoard,
} from './service';
import { provisionRoamingBoard } from '../../shared/api/endpoints';

export interface PrimeBoardsResult {
  ready: number;
  prepared: number;
  failed: number;
}

export async function primeBoard(workspaceId: string, board: Board, preferLan = false) {
  const [local, storedCapability] = await Promise.all([
    loadBoardSnapshot(board.id),
    loadRoamingCapability(board.id),
  ]);
  // Enrollment is not a recurring liveness check of another peer.
  if (storedCapability) {
    if (local?.checklistsHydratedAt) return 'ready' as const;
    if (preferLan && isPrivateNodeOrigin(getApiNodeOrigin())) {
      try {
        const snapshot = await fetchBoardSnapshot(board.id, workspaceId);
        await serializeLocalState(async () => persistServerSnapshot(snapshot, await loadOperationQueue()));
        return 'prepared' as const;
      } catch { /* LAN node unavailable: use autonomous relay replica */ }
    }
    const recovered = await pullRoamingBoard(storedCapability, local);
    if (!recovered.snapshot) throw new Error('Relay ещё не содержит базового снимка доски.');
    await serializeLocalState(async () => persistServerSnapshot(recovered.snapshot!, await loadOperationQueue()));
    return 'prepared' as const;
  }
  const authorPublicKey = await getRoamingAuthorPublicKey();
  const provisioned = await provisionRoamingBoard(board.id, authorPublicKey);
  const capability = provisioned;
  await installRoamingCapability(capability);
  if (local?.checklistsHydratedAt) return 'ready' as const;

  const snapshot = await fetchBoardSnapshot(board.id, workspaceId);
  const merged = await serializeLocalState(async () => persistServerSnapshot(snapshot, await loadOperationQueue()));
  if (capability.canWrite) await publishBoardSnapshot(capability, merged).catch(() => undefined);
  return 'prepared' as const;
}

export async function primeWorkspaceBoards(
  workspaceId: string,
  boards: Board[],
  preferLan = false,
): Promise<PrimeBoardsResult> {
  const result: PrimeBoardsResult = { ready: 0, prepared: 0, failed: 0 };
  for (let index = 0; index < boards.length; index += 2) {
    const batch = boards.slice(index, index + 2);
    const settled = await Promise.allSettled(
      batch.map((board) => primeBoard(workspaceId, board, preferLan)),
    );
    for (const item of settled) {
      if (item.status === 'rejected') result.failed += 1;
      else result[item.value] += 1;
    }
  }
  return result;
}
