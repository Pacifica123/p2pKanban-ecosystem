// What the web «Проверка приёмки» button does (docs/ecosystem/self-acceptance.md,
// «Что делает кнопка в web»). Every step calls the same API functions as the
// screens do; test data lives only in the «Приёмка p2pKanban» workspace.
import { getBoardActivity } from '@/features/activity/api/activity';
import { getSession, refreshSession } from '@/features/auth/api/auth';
import { createBoard, deleteBoard, getBoard, getBoards } from '@/features/boards/api/boards';
import {
  archiveCard, createCard, deleteCard, getCard, getCards, moveCard, unarchiveCard, updateCard,
} from '@/features/cards/api/cards';
import {
  createChecklist, createChecklistItem, getCardChecklists, updateChecklistItem,
} from '@/features/checklists/api/checklists';
import { createColumn, getColumns } from '@/features/columns/api/columns';
import { createComment, getCardComments, updateComment } from '@/features/comments/api/comments';
import { createPortableExport } from '@/features/integrations/api/importExport';
import { parseBoardBundleText } from '@/features/integrations/lib/boardBundle';
import { importBoardCopy } from '@/features/integrations/lib/importBoardCopy';
import { createBoardLabel, replaceCardLabels } from '@/features/labels/api/labels';
import { getBackendVersion } from '@/features/system/api/version';
import { getUpdateControlState, isUpdateAvailable, revisionsMatch } from '@/features/system/api/updateControl';
import { createWorkspace, getWorkspaces } from '@/features/workspaces/api/workspaces';
import { apiRequest, setAccessToken } from '@/shared/api/client';
import { ApiError } from '@/shared/api/errors';
import { applyUiTheme, readStoredUiTheme, UI_THEMES } from '@/shared/appearance/uiThemes';
import { collectReport, webSoftware } from '@/shared/errorReport/collect';
import { peer } from '@/shared/errorReport/journal';
import { parseReportText, renderReport } from '@/shared/errorReport/report';
import type { BoardColumn, Card } from '@/shared/types/api';
import { expectThat, fail, info, pass, skip, warn, type StepDefinition } from './runner';
import type { AcceptanceReport } from './report';

export const TEST_WORKSPACE = 'Приёмка p2pKanban';
export const CROSS_BOARD = 'Встречная доска';
export const CROSS_ITEM_FOR_ANDROID = 'Отметит Android';
export const CROSS_ITEM_FOR_WEB = 'Отметит web';
const CROSS_KEEP = 5;
export const POLL_BURST = 60;

export interface WebAcceptanceContext {
  runId: string;
  stamp: string;
  node: AcceptanceReport['node'];
  workspaceId?: string;
  boardId?: string;
  columns?: BoardColumn[];
  cardId?: string;
  importedBoardId?: string;
  ring?: { enabled: boolean; ring: unknown };
}

export function newWebContext(now = new Date()): WebAcceptanceContext {
  const runId = Math.random().toString(36).slice(2, 10);
  return { runId, stamp: now.toISOString().slice(0, 16).replace('T', ' '), node: null };
}

/** The web test plan answers the D items it cannot do itself. */
export const WEB_REMAINING = [
  'Посмотреть на четыре темы глазами: тёмно-синей нет, текст читается.',
  'Создать кольцо устройств и перенести в него телефон (один раз, необратимо), затем повторить проверку: шаг кольца станет PASS.',
  'Если проверка показала доступное обновление узла — нажать «Обновить», дождаться перезапуска и повторить проверку.',
  'Матрица web → web через общий relay: нужен второй узел.',
  'Release-gates, release ZIP, backup/restore, stop/start/rollback — UTS на хосте.',
];

// A comment longer than 256 bytes in Cyrillic: the activity log once cut it
// inside a 2-byte character and the node answered 502 (patch 2026-10-06-web-utf8-safe-truncation).
export const LONG_COMMENT = 'Проверка приёмки: длинный русский комментарий. '.repeat(8).trim();

const byNewest = (left: Card, right: Card) => right.createdAt.localeCompare(left.createdAt);
function need<T>(value: T | undefined, what: string): T {
  if (value === undefined || value === null) throw new Error(`нет ${what} из прошлого шага`);
  return value;
}

/** A v4-shaped id without crypto.randomUUID: that needs a secure context, and a LAN node is plain http. */
export function randomId(): string {
  const hex = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16));
  hex[12] = '4';
  hex[16] = '89ab'[Math.floor(Math.random() * 4)]!;
  const text = hex.join('');
  return `${text.slice(0, 8)}-${text.slice(8, 12)}-${text.slice(12, 16)}-${text.slice(16, 20)}-${text.slice(20)}`;
}

async function ensureColumns(boardId: string, names: string[]) {
  const existing = (await getColumns(boardId)).items;
  const columns = [...existing];
  for (const name of names.slice(existing.length)) {
    columns.push(await createColumn(boardId, { name, position: (columns.length + 1) * 1000 }));
  }
  return columns.sort((left, right) => left.position - right.position);
}

async function checklistItem(cardId: string, title: string) {
  const lists = (await getCardChecklists(cardId)).items;
  return lists.flatMap((list) => list.items).find((item) => item.title === title) ?? null;
}

export function webSteps(): StepDefinition<WebAcceptanceContext>[] {
  return [
    {
      id: 'env.client', phase: 'Окружение', title: 'Версия web-клиента',
      run: async () => {
        const sw = webSoftware();
        return sw.commit ? info(`web ${sw.version} · сборка ${sw.build || '?'} · коммит ${sw.commit}`)
          : warn(`web ${sw.version}: коммит сборки неизвестен (страница собрана без VITE_SOURCE_REVISION)`);
      },
    },
    {
      id: 'env.node', phase: 'Окружение', title: 'Узел отвечает и называет свою сборку',
      run: async (ctx) => {
        const health = await getBackendVersion();
        const identity = peer();
        ctx.node = { origin: window.location.origin, version: identity?.version ?? health.version ?? null,
          build: identity?.build ?? null, commit: identity?.commit ?? null };
        if (!identity) return warn(`узел ${health.version} не прислал x-p2p-kanban-node: старая сборка узла`);
        const client = webSoftware().commit;
        if (client && identity.commit && !revisionsMatch(client, identity.commit)) {
          return warn(`страница собрана из ${client.slice(0, 12)}, узел — из ${identity.commit.slice(0, 12)}: обновите вкладку (Ctrl+F5)`);
        }
        return pass(`узел web ${identity.version ?? health.version} · сборка ${identity.build || '?'} · коммит ${identity.commit?.slice(0, 12) || '?'}`);
      },
    },
    {
      id: 'auth.session', phase: 'Сеанс', title: 'Сеанс подтверждён узлом', needs: ['env.node'],
      run: async () => {
        const session = await getSession();
        expectThat(session.authenticated, 'узел говорит, что сеанса нет');
        return pass(`режим ${session.mode}`);
      },
    },
    {
      id: 'auth.poll-limit', phase: 'Сеанс', title: `${POLL_BURST} опросов подключения устройства, затем обновление сеанса`,
      covers: ['auth-poll-limit'], needs: ['auth.session'],
      run: async () => {
        let limited = 0;
        for (let index = 0; index < POLL_BURST; index += 1) {
          try {
            await apiRequest('/auth/device-link/lan/inbox');
          } catch (error) {
            if (error instanceof ApiError && error.status === 429) limited += 1;
            else throw error;
          }
        }
        expectThat(limited === 0, `опрос получил 429 ${limited} раз из ${POLL_BURST}: опрос всё ещё тратит общий лимит`);
        const refreshed = await refreshSession();
        setAccessToken(refreshed.accessToken);
        return pass(`${POLL_BURST} опросов без 429; обновление сеанса прошло`);
      },
    },
    {
      id: 'data.workspace', phase: 'Тестовые данные', title: `Пространство «${TEST_WORKSPACE}»`, needs: ['auth.session'],
      run: async (ctx) => {
        const found = (await getWorkspaces()).items.find((item) => item.name === TEST_WORKSPACE && !item.isArchived);
        const workspace = found ?? await createWorkspace({ name: TEST_WORKSPACE, visibility: 'private',
          description: 'Создано кнопкой «Проверка приёмки». Здесь только тестовые доски.' });
        ctx.workspaceId = workspace.id;
        return pass(found ? 'найдено' : 'создано');
      },
    },
    {
      id: 'data.board', phase: 'Тестовые данные', title: 'Доска прогона с двумя колонками', needs: ['data.workspace'],
      run: async (ctx) => {
        const board = await createBoard(need(ctx.workspaceId, 'пространства'), {
          name: `Проверка web ${ctx.stamp} · ${ctx.runId}`, description: 'Удаляется в конце проверки.' });
        ctx.boardId = board.id;
        ctx.columns = await ensureColumns(board.id, ['Сделать', 'Готово']);
        expectThat(ctx.columns.length >= 2, 'колонки не создались');
        return pass(board.name);
      },
    },
    {
      id: 'crud.card', phase: 'Карточки', title: 'Карточка: создать, изменить, переместить, архивировать, вернуть',
      covers: ['crud-matrix'], needs: ['data.board'],
      run: async (ctx) => {
        const boardId = need(ctx.boardId, 'доски');
        const [first, second] = need(ctx.columns, 'колонок');
        const card = await createCard(boardId, { title: `Карточка ${ctx.runId}`, columnId: first!.id });
        ctx.cardId = card.id;
        await updateCard(card.id, { title: `Карточка ${ctx.runId} (изменена)`, description: 'Описание **Markdown**', priority: 'high' });
        const edited = await getCard(card.id);
        expectThat(edited.title.endsWith('(изменена)') && edited.priority === 'high', 'изменение не сохранилось на узле');
        await moveCard(card.id, { targetColumnId: second!.id });
        expectThat((await getCard(card.id)).columnId === second!.id, 'карточка не переместилась');
        await archiveCard(card.id);
        expectThat(!(await getCards(boardId)).items.some((item) => item.id === card.id), 'архивная карточка видна на доске');
        await unarchiveCard(card.id);
        expectThat((await getCards(boardId)).items.some((item) => item.id === card.id), 'карточка не вернулась из архива');
        return pass('создана, изменена, перемещена, архивирована и возвращена');
      },
    },
    {
      id: 'crud.checklist', phase: 'Карточки', title: 'Чек-лист: два пункта, один отмечен',
      covers: ['crud-matrix'], needs: ['crud.card'],
      run: async (ctx) => {
        const cardId = need(ctx.cardId, 'карточки');
        const list = await createChecklist(cardId, { title: 'Проверка' });
        const done = await createChecklistItem(list.id, { title: 'Первый пункт' });
        await createChecklistItem(list.id, { title: 'Второй пункт' });
        await updateChecklistItem(done.id, { isDone: true });
        const items = (await getCardChecklists(cardId)).items.find((item) => item.id === list.id)?.items ?? [];
        expectThat(items.length === 2, `на узле ${items.length} пунктов вместо 2`);
        expectThat(items.filter((item) => item.isDone).length === 1, 'отметка пункта не сохранилась');
        return pass('2 пункта, отмечен 1');
      },
    },
    {
      id: 'crud.comment', phase: 'Карточки', title: 'Комментарий длиннее 256 байт по-русски',
      covers: ['crud-matrix'], needs: ['crud.card'],
      run: async (ctx) => {
        const cardId = need(ctx.cardId, 'карточки');
        const comment = await createComment(cardId, { body: LONG_COMMENT });
        await updateComment(comment.id, { body: `${LONG_COMMENT} Изменено.` });
        const stored = (await getCardComments(cardId)).items.find((item) => item.id === comment.id);
        expectThat(stored?.body === `${LONG_COMMENT} Изменено.`, 'текст комментария на узле другой');
        return pass(`${new TextEncoder().encode(LONG_COMMENT).length} байт, создан и изменён`);
      },
    },
    {
      id: 'crud.label', phase: 'Карточки', title: 'Метка на карточке', covers: ['crud-matrix'], needs: ['crud.card'],
      run: async (ctx) => {
        const label = await createBoardLabel(need(ctx.boardId, 'доски'), { name: 'проверка', color: '#27ae60' });
        await replaceCardLabels(need(ctx.cardId, 'карточки'), [label.id]);
        expectThat((await getCard(ctx.cardId!)).labelIds?.includes(label.id), 'метка не видна у карточки');
        return pass();
      },
    },
    {
      id: 'crud.activity', phase: 'Карточки', title: 'Журнал активности доски', needs: ['crud.card'],
      run: async (ctx) => {
        const items = (await getBoardActivity(need(ctx.boardId, 'доски'))).items ?? [];
        return items.length ? pass(`записей: ${items.length}`) : warn('журнал активности пуст после правок');
      },
    },
    {
      id: 'crud.delete', phase: 'Карточки', title: 'Удалить карточку', covers: ['crud-matrix'], needs: ['data.board'],
      run: async (ctx) => {
        const boardId = need(ctx.boardId, 'доски');
        const card = await createCard(boardId, { title: `Удаляемая ${ctx.runId}`, columnId: need(ctx.columns, 'колонок')[0]!.id });
        await deleteCard(card.id);
        expectThat(!(await getCards(boardId, 'all')).items.some((item) => item.id === card.id), 'удалённая карточка осталась');
        return pass();
      },
    },
    {
      id: 'cross.client', phase: 'Встречная доска', title: 'Карточки web и Android на общей доске',
      covers: ['cross-client', 'crud-matrix'], needs: ['data.workspace'],
      run: async (ctx) => {
        const workspaceId = need(ctx.workspaceId, 'пространства');
        const board = (await getBoards(workspaceId)).items.find((item) => item.name === CROSS_BOARD && !item.isArchived)
          ?? await createBoard(workspaceId, { name: CROSS_BOARD, description: 'Каждая проверка web и Android оставляет здесь карточку и отмечает пункт на карточке другого клиента.' });
        const [column] = await ensureColumns(board.id, ['Карточки клиентов']);
        const cards = (await getCards(board.id)).items;
        const notes: string[] = [];
        let ok = true;
        const android = cards.filter((card) => card.title.startsWith('android ·')).sort(byNewest)[0];
        if (android) {
          const item = await checklistItem(android.id, CROSS_ITEM_FOR_WEB);
          if (item && !item.isDone) await updateChecklistItem(item.id, { isDone: true });
          notes.push(item ? `отмечен пункт на карточке «${android.title}»` : `у карточки «${android.title}» нет пункта «${CROSS_ITEM_FOR_WEB}»`);
          ok &&= Boolean(item);
        } else {
          notes.push('карточек Android ещё нет: запустите проверку на телефоне');
          ok = false;
        }
        const mine = cards.filter((card) => card.title.startsWith('web ·')).sort(byNewest);
        if (mine[0]) {
          const item = await checklistItem(mine[0].id, CROSS_ITEM_FOR_ANDROID);
          notes.push(item?.isDone ? `Android отметил пункт на «${mine[0].title}»` : `Android ещё не отметил «${mine[0].title}»`);
          ok &&= Boolean(item?.isDone);
        }
        const created = await createCard(board.id, { title: `web · ${ctx.stamp} · ${ctx.runId}`, columnId: column!.id });
        const list = await createChecklist(created.id, { title: 'Встречная проверка' });
        await createChecklistItem(list.id, { title: CROSS_ITEM_FOR_ANDROID });
        notes.push('оставлена новая карточка web');
        for (const old of mine.slice(CROSS_KEEP - 1)) await deleteCard(old.id);
        return ok ? pass(notes.join('; ')) : info(notes.join('; '));
      },
    },
    {
      id: 'io.export', phase: 'Экспорт и импорт', title: 'Переносимый экспорт доски читается импортёром',
      covers: ['import-copy'], needs: ['crud.checklist', 'crud.comment'],
      run: async (ctx) => {
        const response = await createPortableExport({ scopeKind: 'board', workspaceId: ctx.workspaceId, boardId: ctx.boardId,
          exportMode: 'portable_export', includeArchived: true });
        const preview = parseBoardBundleText(JSON.stringify(response.bundle), response.suggestedFileName);
        expectThat(preview.counts.cards >= 1 && preview.counts.checklists >= 1 && preview.counts.comments >= 1,
          `в экспорте не хватает данных: ${JSON.stringify(preview.counts)}`);
        const copy = await importBoardCopy({ workspaceId: ctx.workspaceId!, boardName: `${preview.board.name} · копия`, preview });
        ctx.importedBoardId = copy.boardId;
        expectThat(JSON.stringify(copy.counts) === JSON.stringify(preview.counts),
          `копия ${JSON.stringify(copy.counts)} ≠ экспорт ${JSON.stringify(preview.counts)}`);
        await deleteBoard(copy.boardId);
        ctx.importedBoardId = undefined;
        return pass(`экспорт → импорт копией: ${preview.counts.cards} карточек, ${preview.counts.checklistItems} пунктов, ${preview.counts.comments} комментариев; копия удалена`);
      },
    },
    {
      id: 'error.report', phase: 'Подробности ошибки', title: 'Ошибка 404 даёт полный отчёт error-report/1',
      covers: ['error-report'], needs: ['env.node'],
      run: async () => {
        let caught: unknown = null;
        try {
          await getBoard(randomId());
        } catch (error) {
          caught = error;
        }
        expectThat(caught instanceof ApiError && caught.status >= 400, 'узел не вернул ошибку на несуществующую доску');
        const report = parseReportText(renderReport(collectReport({ message: 'Проверка приёмки: доска не найдена',
          error: caught, screen: 'Проверка приёмки', operation: 'Ошибка 404' })));
        expectThat(report.http?.status === (caught as ApiError).status, 'в отчёте нет HTTP-статуса');
        const gaps = [!report.software.commit && 'коммит клиента', !report.peer && 'сборка узла'].filter(Boolean);
        return gaps.length ? warn(`отчёт собран, но без: ${gaps.join(', ')}`)
          : pass(`HTTP ${report.http?.status}, узел ${report.peer?.version} · ${report.peer?.build}, клиент ${report.software.commit?.slice(0, 7)}`);
      },
    },
    {
      id: 'ring.view', phase: 'Кольцо и обновление', title: 'Экран кольца устройств загружается', covers: ['ring-r2'],
      needs: ['auth.session'],
      run: async (ctx) => {
        const view = await apiRequest<{ enabled: boolean; ring: null | { members: unknown[] }; legacy: unknown[] }>('/ring');
        ctx.ring = view;
        if (!view.enabled) return info('кольцу нужен включённый Nostr-роуминг узла');
        if (!view.ring) return info(`кольцо не создано; доверены по-старому: ${view.legacy.length}. Создать — решение человека (D)`);
        return pass(`устройств в кольце: ${view.ring.members.length}; вне кольца: ${view.legacy.length}`);
      },
    },
    {
      id: 'ring.sync', phase: 'Кольцо и обновление', title: '«Синхронизировать сейчас» собирает кворум relay', covers: ['ring-r2'],
      needs: ['ring.view'],
      run: async (ctx) => {
        if (!ctx.ring?.ring) return skip('кольца нет');
        const view = await apiRequest<{ lastSync: null | { quorum: boolean; errors: string[]; fetched: number } }>('/ring/sync', { method: 'POST' });
        const sync = view.lastSync;
        expectThat(sync, 'узел не записал итог синхронизации');
        if (!sync.quorum) return fail(`кворум не собран; ошибки: ${sync.errors.join('; ') || 'нет'}`);
        return sync.errors.length ? warn(`кворум есть, ошибки: ${sync.errors.join('; ')}`) : pass(`кворум есть, получено записей: ${sync.fetched}`);
      },
    },
    {
      id: 'update.channel', phase: 'Кольцо и обновление', title: 'Канал обновления узла', covers: ['web-update-channel'],
      run: async () => {
        let state: Awaited<ReturnType<typeof getUpdateControlState>>;
        try {
          state = await getUpdateControlState();
        } catch (error) {
          return info(`состояние обновления не получено: ${error instanceof Error ? error.message : String(error)}`);
        }
        const installed = state.installedRevision?.slice(0, 12) || 'неизвестна';
        if (!state.latest) return info(`сборка узла ${installed}; последний коммит web/ в ${state.repository || 'GitHub'} не получен`);
        const latest = `${state.latest.shortSha} «${state.latest.message.split('\n')[0]}»`;
        return isUpdateAvailable(state)
          ? info(`доступно обновление: узел ${installed}, последний коммит web/ — ${latest}. Нажать «Обновить» — D`)
          : pass(`узел собран из последнего коммита web/ (${latest})`);
      },
    },
    {
      id: 'ui.themes', phase: 'Темы', title: 'Четыре темы приложения применяются', covers: ['ui-themes'],
      run: async () => {
        const root = document.documentElement;
        const wrong: string[] = [];
        try {
          for (const theme of UI_THEMES) {
            applyUiTheme(theme.id, root);
            const value = getComputedStyle(root).getPropertyValue('--ui-background').trim().toLowerCase();
            if (value !== theme.swatches.background.toLowerCase()) wrong.push(`${theme.label}: фон ${value || 'не задан'} вместо ${theme.swatches.background}`);
          }
        } finally {
          applyUiTheme(readStoredUiTheme(), root);
        }
        expectThat(!wrong.length, wrong.join('; '));
        return pass(UI_THEMES.map((theme) => theme.label).join(', '));
      },
    },
    {
      id: 'cleanup', phase: 'Уборка', title: 'Удалить доску прогона', needs: ['data.board'],
      run: async (ctx) => {
        if (ctx.importedBoardId) await deleteBoard(ctx.importedBoardId).catch(() => undefined);
        await deleteBoard(need(ctx.boardId, 'доски'));
        return pass(`пространство «${TEST_WORKSPACE}» и «${CROSS_BOARD}» оставлены для следующих прогонов`);
      },
    },
  ];
}
