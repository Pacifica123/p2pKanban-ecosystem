import { apiRequest } from '@/shared/api/client';
import { parseBoardBundleText, type BoardBundlePreview } from '@/features/integrations/lib/boardBundle';
import { PROJECT_BOARD_ID, type ProjectBoardNodeSummary } from '@/features/projectBoard/lib/projectBoard';

// contracts/project-board/1: the node chooses between its build copy and main on GitHub.
export function getProjectBoardSummary() {
  return apiRequest<ProjectBoardNodeSummary>('/project-board/summary');
}

export async function getProjectBoard(): Promise<BoardBundlePreview> {
  const bundle = await apiRequest<unknown>('/project-board');
  const preview = parseBoardBundleText(JSON.stringify(bundle), 'project-board.json');
  if (preview.board.id !== PROJECT_BOARD_ID) {
    throw new Error('Узел отдал не доску проекта.');
  }
  return preview;
}
