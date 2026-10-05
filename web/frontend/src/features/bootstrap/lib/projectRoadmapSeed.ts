import { createBoard, getBoards } from '@/features/boards/api/boards';
import { createCard, getCards, updateCard } from '@/features/cards/api/cards';
import { createColumn, getColumns } from '@/features/columns/api/columns';
import { createWorkspace, getWorkspaces } from '@/features/workspaces/api/workspaces';
import type { BoardColumn, Card } from '@/shared/types/api';

const ROADMAP_WORKSPACE_NAME = 'P2P Planner roadmap';
const ROADMAP_BOARD_NAME = 'План работ по проекту';

const ROADMAP_COLUMNS = [
  {
    name: 'Готово',
    description: 'То, что уже реализовано и проверено в текущем проекте.',
  },
  {
    name: 'Сейчас',
    description: 'Ближайшие правки и активные задачи.',
  },
  {
    name: 'Далее',
    description: 'Следующие инженерные этапы после текущего полиша.',
  },
  {
    name: 'Потом',
    description: 'То, что важно, но идет после core sync и стабилизации.',
  },
] as const;

type RoadmapCardSeed = {
  title: string;
  priority: Card['priority'];
  description: string;
};

const V1_COMPLETED_TITLES = [
  'MVP scope v1',
  'Docs v2 и ADR',
  'Data model и БД',
  'Backend module map',
  'OpenAPI / HTTP API v1',
  'Auth и identity модель',
  'Migrations и backend skeleton',
  'Core backend CRUD',
  'Appearance / customization backend',
  'Activity / history / audit',
  'Web frontend architecture',
  'Web frontend core UI',
  'Web customization UI',
  'UI cleanup и рефакторинг beta-базы',
  'Косметический polish кнопок и micro-UX',
  'Автогенерация dev-roadmap board',
  'Local-first слой',
  'Sync model implementation plan',
  'Conflict resolution',
  'P2P / relay / bootstrap abstraction',
  'Integrations architecture',
  'Import / export / backup',
  'Security / privacy / threat model',
  'Testing strategy',
  'Deployment / packaging',
  'Beta scope',
  'Mobile architecture',
] as const;

export const ROADMAP_CARDS: Record<string, readonly RoadmapCardSeed[]> = {
  'Готово': [
    ...V1_COMPLETED_TITLES.map((title) => ({
      title,
      priority: null,
      description: `Этап «${title}» завершён в v1 и служит опорой для следующей продуктовой сессии.`,
    })),
    {
      title: 'v2: Пригласительные ссылки и права доступа',
      priority: null,
      description: 'Готово: owner/member/guest, одноразовые ссылки со сроком жизни, отзыв приглашений и участников, серверная проверка роли и ротация access epoch/capability после каждого изменения состава пространства.',
    },
  ],
  'Сейчас': [
    {
      title: 'v2: Rich text в карточках',
      priority: 'high',
      description: 'Добавить переносимый безопасный формат rich text для описаний и комментариев с одинаковым отображением в web и Android.',
    },
  ],
  'Далее': [
    {
      title: 'v2: Интеграция с GitHub',
      priority: 'high',
      description: 'Связать карточки с issues/PR/commit, сохранив local-first очередь, явное владение полями и проверяемые webhook-события.',
    },
    {
      title: 'v2: Интеграция с devctl',
      priority: 'medium',
      description: 'Показывать планы, применение патчей и receipts как связанные с карточками действия без переноса transport-терминов в обычный UX.',
    },
  ],
  'Потом': [
    {
      title: 'v2: Интеграция с Obsidian',
      priority: 'medium',
      description: 'Исследовать двусторонние ссылки на Markdown-заметки и предсказуемый export/import без скрытого destructive merge.',
    },
  ],
};

async function ensureRoadmapWorkspace() {
  const workspaces = await getWorkspaces();
  const existing = workspaces.items.find((item) => !item.isArchived && item.name === ROADMAP_WORKSPACE_NAME);

  if (existing) return existing;

  return createWorkspace({
    name: ROADMAP_WORKSPACE_NAME,
    visibility: 'private',
    description: 'Автогенерируемый dev-workspace с примерной доской по текущему проекту.',
  });
}

async function ensureRoadmapBoard(workspaceId: string) {
  const boards = await getBoards(workspaceId);
  const existing = boards.items.find((item) => !item.isArchived && item.name === ROADMAP_BOARD_NAME);

  if (existing) return existing;

  return createBoard(workspaceId, {
    name: ROADMAP_BOARD_NAME,
    description: 'Наглядная дорожная карта разработки прямо внутри самого planner-проекта.',
  });
}

async function ensureColumns(boardId: string) {
  let columns = await getColumns(boardId);

  for (const columnSeed of ROADMAP_COLUMNS) {
    const exists = columns.items.some((item) => item.name === columnSeed.name);
    if (!exists) {
      await createColumn(boardId, {
        name: columnSeed.name,
        description: columnSeed.description,
      });
      columns = await getColumns(boardId);
    }
  }

  return columns.items;
}

async function ensureCards(boardId: string, columns: BoardColumn[]) {
  const cards = await getCards(boardId);
  const existingByTitle = new Map(cards.items.map((card) => [card.title, card]));
  const columnByName = new Map(columns.map((column) => [column.name, column]));

  for (const [columnName, seeds] of Object.entries(ROADMAP_CARDS)) {
    const column = columnByName.get(columnName);
    if (!column) continue;

    for (const seed of seeds) {
      const existing = existingByTitle.get(seed.title);
      if (!existing) {
        const created = await createCard(boardId, {
          title: seed.title,
          description: seed.description,
          columnId: column.id,
          priority: seed.priority,
        });
        existingByTitle.set(seed.title, created);
        continue;
      }

      if (
        existing.columnId !== column.id
        || existing.priority !== seed.priority
        || existing.description !== seed.description
      ) {
        const updated = await updateCard(existing.id, {
          columnId: column.id,
          priority: seed.priority,
          description: seed.description,
        });
        existingByTitle.set(seed.title, updated);
      }
    }
  }
}

export async function ensureProjectRoadmapSeed() {
  const workspace = await ensureRoadmapWorkspace();
  const board = await ensureRoadmapBoard(workspace.id);
  const columns = await ensureColumns(board.id);
  await ensureCards(board.id, columns);

  return {
    workspaceId: workspace.id,
    boardId: board.id,
  };
}
