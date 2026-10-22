// What the Android «Проверка приёмки» button does (docs/ecosystem/self-acceptance.md,
// «Что делает кнопка в Android»). Board work goes through the same local-first
// runtime the board screen uses (useLocalBoard), mounted by AcceptanceScreen;
// the test data lives only in the «Приёмка p2pKanban» workspace.
import { UI_THEMES, type UiThemeId } from '../../app/uiThemes';
import { ApiError, apiRequest } from '../../shared/api/client';
import { resetNodeReach } from '../../shared/api/nodeReach';
import {
  createBoard, createCard, createChecklist, createChecklistItem, createColumn, createWorkspace, deleteBoard,
  deleteCard, getBackendVersion, getBoard, getBoards, getCards, getChecklists, getColumns, getSession,
  getWorkspaces, nativeSignIn, updateChecklistItem,
} from '../../shared/api/endpoints';
import { collectReport, mobileSoftware } from '../../shared/errorReport/collect';
import { peer } from '../../shared/errorReport/journal';
import { parseReportText, renderReport } from '../../shared/errorReport/report';
import type { Board, BoardColumn, Card } from '../../shared/types/api';
import { readableError } from '../auth/signInError';
import { deviceFingerprint } from '../deviceLink/service';
import type { LocalBoardRuntime } from '../localFirst/useLocalBoard';
import { refreshDeviceCatalog, refreshWorkspaceCatalog } from '../roaming/catalog';
import { fetchFromRelays } from '../roaming/nostrRelay';
import { loadRoamingCapability } from '../roaming/service';
import type { AcceptanceReport } from './report';
import { expectThat, fail, info, pass, skip, warn, type StepDefinition } from './runner';

export const TEST_WORKSPACE = 'Приёмка p2pKanban';
export const CROSS_BOARD = 'Встречная доска';
export const CROSS_ITEM_FOR_ANDROID = 'Отметит Android';
export const CROSS_ITEM_FOR_WEB = 'Отметит web';
const CROSS_KEEP = 5;
export const POLL_BURST = 30;

export interface NetworkState { isOnline: boolean; type: string }

/** A request to the person: one physical action the app cannot do itself. */
export interface Prompt {
  id: string;
  title: string;
  text: string;
  /** The app sees by itself that the action is done. */
  ready: (network: NetworkState) => boolean;
}

export interface BoardDriver {
  /** Mount the board runtime (as the board screen does) and wait until its copy is loaded. */
  open: (boardId: string, workspaceId: string) => Promise<LocalBoardRuntime>;
  /** The runtime as of the last render. */
  current: () => LocalBoardRuntime | null;
  close: () => void;
}

export interface MobileAcceptanceContext {
  runId: string;
  stamp: string;
  node: AcceptanceReport['node'];
  nodeOrigin: string | null;
  user: { id: string; email: string } | null;
  network: () => NetworkState;
  /** Resolves true when `ready` held long enough, false when the person skipped the phase. */
  ask: (prompt: Prompt) => Promise<boolean>;
  board: BoardDriver;
  ui: { theme: () => UiThemeId; setTheme: (id: UiThemeId) => void; background: () => string };
  sleep?: (ms: number) => Promise<void>;
  workspaceId?: string;
  boardA?: Board;
  boardB?: Board;
  columns?: BoardColumn[];
  mainCardTitle?: string;
  phaseCards: string[];
}

export const PROMPTS = {
  cellular: {
    id: 'phase.cellular', title: 'Мобильная сеть',
    text: 'Выключите Wi-Fi, чтобы телефон перешёл в мобильную сеть. Узел в домашней сети станет недоступен — так и задумано. Проверка продолжится сама.',
    ready: (net: NetworkState) => net.isOnline && net.type === 'cellular',
  },
  offline: {
    id: 'phase.offline', title: 'Без сети',
    text: 'Включите режим полёта (или выключите и Wi-Fi, и мобильные данные). Проверка продолжится сама.',
    ready: (net: NetworkState) => !net.isOnline,
  },
  wifi: {
    id: 'phase.wifi', title: 'Снова Wi-Fi',
    text: 'Выключите режим полёта и подключитесь к Wi-Fi той же сети, что узел. Проверка продолжится сама.',
    ready: (net: NetworkState) => net.isOnline && net.type === 'wifi',
  },
} satisfies Record<string, Prompt>;

export const MOBILE_REMAINING = [
  'Посмотреть на четыре темы глазами: тёмно-синей нет, текст читается.',
  'Перезапустить приложение посреди работы и оставить телефон на ночь в фоне (Doze): карточки не теряются.',
  'Несколько устройств одновременно на одной доске через relay.',
  'Кольцо устройств на телефоне появится с этапом R3.',
];

export function newMobileContext(input: Omit<MobileAcceptanceContext, 'runId' | 'stamp' | 'node' | 'phaseCards'>, now = new Date()): MobileAcceptanceContext {
  return { ...input, runId: Math.random().toString(36).slice(2, 10), stamp: now.toISOString().slice(0, 16).replace('T', ' '),
    node: null, phaseCards: [] };
}

function need<T>(value: T | undefined | null, what: string): T {
  if (value === undefined || value === null) throw new Error(`нет ${what} из прошлого шага`);
  return value;
}

const wait = (ctx: MobileAcceptanceContext, ms: number) => (ctx.sleep ?? ((t) => new Promise<void>((done) => setTimeout(done, t))))(ms);

/** Poll until `probe` returns a value; `null` once `timeoutMs` of pauses have passed. */
export async function until<T>(ctx: MobileAcceptanceContext, probe: () => Promise<T | null | undefined | false> | T | null | undefined | false,
  timeoutMs: number, everyMs = 2000): Promise<T | null> {
  for (let waited = 0; ; waited += everyMs) {
    try {
      const value = await probe();
      if (value) return value;
    } catch { /* not yet: the network may still be settling */ }
    if (waited >= timeoutMs) return null;
    await wait(ctx, everyMs);
  }
}

const queued = (runtime: LocalBoardRuntime) => runtime.pendingCount + runtime.relayPendingCount;
const byNewest = (left: Card, right: Card) => right.createdAt.localeCompare(left.createdAt);

/** v4-shaped id for a board that does not exist; expo-crypto is not needed for that. */
function randomId(): string {
  const hex = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16));
  hex[12] = '4';
  hex[16] = '8';
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
  const lists = (await getChecklists(cardId)).items;
  return lists.flatMap((list) => list.items ?? []).find((item) => item.title === title) ?? null;
}

async function waitQueueEmpty(ctx: MobileAcceptanceContext, timeoutMs: number) {
  return until(ctx, async () => {
    const runtime = ctx.board.current();
    if (!runtime) return null;
    if (queued(runtime) === 0) return runtime;
    await runtime.refresh();
    return null;
  }, timeoutMs, 3000);
}

function promptStep(prompt: Prompt, needs: string[]): StepDefinition<MobileAcceptanceContext> {
  return {
    id: prompt.id, phase: prompt.title, title: `Просьба: ${prompt.title.toLowerCase()}`, needs,
    run: async (ctx) => {
      const done = await ctx.ask(prompt);
      const net = ctx.network();
      return done ? pass(`сеть: ${net.type}${net.isOnline ? '' : ', нет связи'}`) : skip('фаза пропущена человеком');
    },
  };
}

export function mobileSteps(): StepDefinition<MobileAcceptanceContext>[] {
  return [
    // ---- Wi-Fi / LAN -------------------------------------------------------
    {
      id: 'env.client', phase: 'Wi-Fi', title: 'Версия Android-клиента',
      run: async () => {
        const sw = mobileSoftware();
        return sw.commit ? info(`mobile ${sw.version} · versionCode ${sw.build} · коммит ${sw.commit}`)
          : warn(`mobile ${sw.version} · versionCode ${sw.build}: коммит сборки неизвестен`);
      },
    },
    {
      id: 'env.network', phase: 'Wi-Fi', title: 'Телефон в Wi-Fi',
      run: async (ctx) => {
        const net = ctx.network();
        return net.type === 'wifi' && net.isOnline ? pass('wifi')
          : warn(`сеть ${net.type}: начните проверку в Wi-Fi той же сети, что узел`);
      },
    },
    {
      id: 'env.node', phase: 'Wi-Fi', title: 'Узел отвечает и называет свою сборку',
      run: async (ctx) => {
        // The check is a fresh question to the node: a pause left by an earlier silence
        // (shared/api/nodeReach.ts) must not answer for it. Run jd21drv3 (2026-10-22)
        // reported «не ответил 503 с назад» in 0 ms without asking the node.
        resetNodeReach();
        const health = await getBackendVersion();
        const identity = peer();
        ctx.node = { origin: ctx.nodeOrigin, version: identity?.version ?? health.version ?? null,
          build: identity?.build ?? null, commit: identity?.commit ?? null };
        if (!identity) return warn(`узел ${health.version} не прислал x-p2p-kanban-node: старая сборка узла`);
        return pass(`${ctx.nodeOrigin} · web ${identity.version} · сборка ${identity.build || '?'} · коммит ${identity.commit?.slice(0, 12) || '?'}`);
      },
    },
    {
      id: 'auth.session', phase: 'Wi-Fi', title: 'Сеанс подтверждён узлом', needs: ['env.node'],
      run: async () => {
        const session = await getSession();
        expectThat(session.authenticated, 'узел говорит, что сеанса нет');
        return pass();
      },
    },
    {
      id: 'auth.other-node', phase: 'Wi-Fi', title: 'Вход с чужим паролем объясняет «аккаунт на другом узле»',
      covers: ['auth-other-node'], needs: ['auth.session'],
      run: async (ctx) => {
        const email = need(ctx.user?.email, 'почты аккаунта');
        let caught: unknown = null;
        try {
          await nativeSignIn({ email, password: `wrong-${randomId()}` });
        } catch (error) {
          caught = error;
        }
        expectThat(caught instanceof ApiError, 'узел принял неверный пароль');
        expectThat(caught.status === 401, `узел ответил ${caught.status} вместо 401`);
        const text = readableError(caught, 'sign-in', ctx.nodeOrigin);
        expectThat(text.includes('только на узле, где его создали'), `текст ошибки: ${text}`);
        const report = parseReportText(renderReport(collectReport({ message: text, error: caught, screen: 'Вход' })));
        expectThat(report.http?.status === 401 && report.http.path.endsWith('/auth/native/sign-in'),
          'в подробностях ошибки входа нет POST …/native/sign-in → 401');
        const key = await deviceFingerprint();
        expectThat(/^[0-9a-f]{64}$/.test(key), `ключ устройства в неожиданном виде: ${JSON.stringify(key.slice(0, 12))}…`);
        return pass('401 с объяснением, подробности несут HTTP 401, ключ устройства — 64 hex без «\\n»');
      },
    },
    {
      id: 'auth.poll-limit', phase: 'Wi-Fi', title: `${POLL_BURST} опросов подключения устройства без 429`,
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
        expectThat(limited === 0, `429 ${limited} раз из ${POLL_BURST}`);
        await getSession();
        return pass('опросы без 429, сеанс после них отвечает');
      },
    },
    {
      id: 'data.workspace', phase: 'Wi-Fi', title: `Пространство «${TEST_WORKSPACE}»`, needs: ['auth.session'],
      run: async (ctx) => {
        const found = (await getWorkspaces()).items.find((item) => item.name === TEST_WORKSPACE && !item.isArchived);
        const workspace = found ?? await createWorkspace({ name: TEST_WORKSPACE, visibility: 'private',
          description: 'Создано кнопкой «Проверка приёмки». Здесь только тестовые доски.' });
        ctx.workspaceId = workspace.id;
        return pass(found ? 'найдено' : 'создано');
      },
    },
    {
      id: 'data.boards', phase: 'Wi-Fi', title: 'Доска A (откроется) и доска B (не открывается)', needs: ['data.workspace'],
      run: async (ctx) => {
        const workspaceId = need(ctx.workspaceId, 'пространства');
        ctx.boardA = await createBoard(workspaceId, { name: `Проверка android ${ctx.stamp} · ${ctx.runId}`, description: 'Удаляется в конце проверки.' });
        ctx.columns = await ensureColumns(ctx.boardA.id, ['Сделать', 'Готово']);
        ctx.boardB = await createBoard(workspaceId, { name: `Проверка android ${ctx.stamp} · ${ctx.runId} · не открыта`,
          description: 'Создана на узле и не открывается в Wi-Fi: в мобильной сети она должна появиться сама.' });
        return pass(`${ctx.boardA.name}; ${ctx.boardB.name}`);
      },
    },
    {
      id: 'board.open', phase: 'Wi-Fi', title: 'Доска A открывается и готовит роуминг', covers: ['mobile-cross-network'],
      needs: ['data.boards'],
      run: async (ctx) => {
        const board = need(ctx.boardA, 'доски A');
        const runtime = await ctx.board.open(board.id, board.workspaceId);
        const ready = await until(ctx, () => {
          const current = ctx.board.current();
          return current?.snapshot && current.syncMode === 'roaming' ? current : null;
        }, 30_000, 1000);
        if (!ready) return warn(`доска открыта, но роуминг не подготовлен: ${runtime.lastError || 'узел не выдал ключ доски'}`);
        return pass(`роуминг готов, relay: ${ready.relayCount}`);
      },
    },
    {
      id: 'crud.local', phase: 'Wi-Fi', title: 'Карточка, чек-лист, перемещение и архив через очередь доски',
      covers: ['crud-matrix'], needs: ['board.open'],
      run: async (ctx) => {
        const runtime = need(ctx.board.current(), 'открытой доски');
        const [first, second] = need(ctx.columns, 'колонок');
        const title = `Карточка android ${ctx.runId}`;
        const card = await runtime.createCard({ title, columnId: first!.id });
        const current = () => need(ctx.board.current(), 'открытой доски');
        const live = (id: string) => current().snapshot?.cards.find((item) => item.id === id || item.title.startsWith(title));
        await current().updateCard(card.id, { title: `${title} (изменена)`, priority: 'high' });
        ctx.mainCardTitle = `${title} (изменена)`;
        const id = () => need(live(card.id), 'карточки в локальной копии').id;
        await current().createChecklist(id(), 'Проверка');
        const list = await until(ctx, () => current().getCardChecklists(id())[0], 10_000, 500);
        expectThat(list, 'чек-лист не появился в локальной копии');
        await current().createChecklistItem(id(), list.id, 'Первый пункт');
        const item = await until(ctx, () => current().getCardChecklists(id())[0]?.items?.[0], 10_000, 500);
        expectThat(item, 'пункт не появился в локальной копии');
        await current().toggleChecklistItem(id(), list.id, item.id, true);
        await current().moveCard(id(), second!.id);
        await current().archiveCard(id());
        await current().unarchiveCard(id());
        const doomed = await current().createCard({ title: `Удаляемая ${ctx.runId}`, columnId: first!.id });
        await current().deleteCard(doomed.id);
        const settled = await waitQueueEmpty(ctx, 60_000);
        expectThat(settled, `очередь не опустела за минуту: ${current().pendingCount} ждут, ${current().failedCount} с ошибкой, ${current().lastError || ''}`);
        return pass('изменения ушли из очереди');
      },
    },
    {
      id: 'crud.node', phase: 'Wi-Fi', title: 'Узел видит изменения Android', covers: ['crud-matrix'], needs: ['crud.local'],
      run: async (ctx) => {
        const board = need(ctx.boardA, 'доски A');
        const second = need(ctx.columns, 'колонок')[1]!;
        const found = await until(ctx, async () => {
          const cards = (await getCards(board.id)).items;
          const card = cards.find((item) => item.title === ctx.mainCardTitle);
          if (!card || card.columnId !== second.id || card.isArchived || card.priority !== 'high') return null;
          if (cards.some((item) => item.title.startsWith('Удаляемая'))) return null;
          const items = (await getChecklists(card.id)).items.flatMap((list) => list.items ?? []);
          return items.some((entry) => entry.title === 'Первый пункт' && entry.isDone) ? card : null;
        }, 90_000, 5000);
        expectThat(found, 'за 90 с узел не показал карточку в колонке «Готово» с отмеченным пунктом (или удалённая карточка осталась)');
        return pass('название, приоритет, колонка, архив, чек-лист и удаление совпадают');
      },
    },
    {
      id: 'cross.client', phase: 'Wi-Fi', title: 'Карточки Android и web на общей доске',
      covers: ['cross-client', 'crud-matrix'], needs: ['data.workspace'],
      run: async (ctx) => {
        const workspaceId = need(ctx.workspaceId, 'пространства');
        const board = (await getBoards(workspaceId)).items.find((item) => item.name === CROSS_BOARD && !item.isArchived)
          ?? await createBoard(workspaceId, { name: CROSS_BOARD, description: 'Каждая проверка web и Android оставляет здесь карточку и отмечает пункт на карточке другого клиента.' });
        const [column] = await ensureColumns(board.id, ['Карточки клиентов']);
        const cards = (await getCards(board.id)).items;
        const notes: string[] = [];
        let ok = true;
        const web = cards.filter((card) => card.title.startsWith('web ·')).sort(byNewest)[0];
        if (web) {
          const entry = await checklistItem(web.id, CROSS_ITEM_FOR_ANDROID);
          if (entry && !entry.isDone) await updateChecklistItem(entry.id, { isDone: true });
          notes.push(entry ? `отмечен пункт на карточке «${web.title}»` : `у карточки «${web.title}» нет пункта «${CROSS_ITEM_FOR_ANDROID}»`);
          ok &&= Boolean(entry);
        } else {
          notes.push('карточек web ещё нет: запустите проверку в web');
          ok = false;
        }
        const mine = cards.filter((card) => card.title.startsWith('android ·')).sort(byNewest);
        if (mine[0]) {
          const entry = await checklistItem(mine[0].id, CROSS_ITEM_FOR_WEB);
          notes.push(entry?.isDone ? `web отметил пункт на «${mine[0].title}»` : `web ещё не отметил «${mine[0].title}»`);
          ok &&= Boolean(entry?.isDone);
        }
        const created = await createCard(board.id, { title: `android · ${ctx.stamp} · ${ctx.runId}`, columnId: column!.id });
        const list = await createChecklist(created.id, { title: 'Встречная проверка' });
        await createChecklistItem(list.id, { title: CROSS_ITEM_FOR_WEB });
        notes.push('оставлена новая карточка Android');
        for (const old of mine.slice(CROSS_KEEP - 1)) await deleteCard(old.id);
        return ok ? pass(notes.join('; ')) : info(notes.join('; '));
      },
    },
    {
      id: 'error.report', phase: 'Wi-Fi', title: 'Ошибка 404 даёт полный отчёт error-report/1', covers: ['error-report'],
      needs: ['env.node'],
      run: async () => {
        let caught: unknown = null;
        try {
          await getBoard(randomId());
        } catch (error) {
          caught = error;
        }
        expectThat(caught instanceof ApiError && caught.status >= 400, 'узел не вернул ошибку на несуществующую доску');
        const report = parseReportText(renderReport(collectReport({ message: 'Проверка приёмки: доска не найдена', error: caught,
          screen: 'Проверка приёмки', operation: 'Ошибка 404' })));
        expectThat(report.http?.status === caught.status, 'в отчёте нет HTTP-статуса');
        const gaps = [!report.software.commit && 'коммит APK', !report.peer && 'сборка узла', !report.logs.length && 'журнал'].filter(Boolean);
        return gaps.length ? warn(`отчёт собран, но без: ${gaps.join(', ')}`)
          : pass(`HTTP ${report.http?.status}, узел ${report.peer?.version} · ${report.peer?.build}, APK ${report.software.commit?.slice(0, 7)}`);
      },
    },
    {
      id: 'ui.themes', phase: 'Wi-Fi', title: 'Четыре темы приложения применяются', covers: ['ui-themes'],
      run: async (ctx) => {
        const original = ctx.ui.theme();
        const wrong: string[] = [];
        try {
          for (const theme of UI_THEMES) {
            ctx.ui.setTheme(theme.id);
            const seen = await until(ctx, () => ctx.ui.background().toLowerCase() === theme.colors.background.toLowerCase(), 3000, 100);
            if (!seen) wrong.push(`${theme.label}: фон ${ctx.ui.background()} вместо ${theme.colors.background}`);
          }
        } finally {
          ctx.ui.setTheme(original);
        }
        expectThat(!wrong.length, wrong.join('; '));
        return pass(UI_THEMES.map((theme) => theme.label).join(', '));
      },
    },
    {
      id: 'relays.reach', phase: 'Wi-Fi', title: 'Relay доски отвечают', covers: ['mobile-relays'], needs: ['board.open'],
      run: async (ctx) => {
        const capability = await loadRoamingCapability(need(ctx.boardA, 'доски A').id);
        if (!capability) return skip('у доски нет relay-ключа');
        const result = await fetchFromRelays({ relays: capability.relays, kind: capability.eventKind, boardTag: capability.boardTag });
        const enough = result.relayCount >= capability.minimumRelayAcks;
        return (enough ? pass : warn)(`ответили ${result.relayCount}/${capability.relays.length} (нужно ${capability.minimumRelayAcks}); событий доски: ${result.events.length}`);
      },
    },
    // ---- Мобильная сеть ----------------------------------------------------
    promptStep(PROMPTS.cellular, ['board.open']),
    {
      id: 'net.cellular-open', phase: 'Мобильная сеть', title: 'Доска A открыта из локальной копии и получает изменения через relay',
      covers: ['mobile-cross-network'], needs: ['phase.cellular'],
      run: async (ctx) => {
        const runtime = need(ctx.board.current(), 'открытой доски');
        expectThat(runtime.snapshot?.cards.some((card) => card.title === ctx.mainCardTitle), 'карточки из Wi-Fi нет в локальной копии');
        await runtime.refresh();
        const after = need(ctx.board.current(), 'открытой доски');
        return after.syncMode === 'roaming' ? pass(`relay: ${after.relayCount}${after.lastError ? `; последняя ошибка: ${after.lastError}` : ''}`)
          : fail(`доска в режиме ${after.syncMode}: без узла она не синхронизируется`);
      },
    },
    {
      id: 'net.catalog-workspace', phase: 'Мобильная сеть', title: 'Каталог устройства знает тестовое пространство',
      covers: ['mobile-new-board-roaming'], needs: ['phase.cellular'],
      run: async (ctx) => {
        const user = need(ctx.user, 'аккаунта');
        const found = await until(ctx, async () => (await refreshWorkspaceCatalog(user.id)).find((item) => item.id === ctx.workspaceId), 30_000, 10_000);
        return found ? pass(found.name) : fail('пространство не найдено в каталоге relay');
      },
    },
    {
      id: 'net.catalog-new-board', phase: 'Мобильная сеть', title: 'Доска B, не открытая в Wi-Fi, появилась в мобильной сети',
      covers: ['mobile-new-board-roaming'], needs: ['phase.cellular'],
      run: async (ctx) => {
        const board = need(ctx.boardB, 'доски B');
        const found = await until(ctx, async () => (await refreshDeviceCatalog(board.workspaceId, ctx.user?.id)).find((item) => item.id === board.id), 30_000, 10_000);
        return found ? pass(found.name)
          : fail('за 30 с каталог relay не показал доску, созданную на узле: в мобильной сети видны только доски, открытые в Wi-Fi (замечание John 2026-10-17)');
      },
    },
    {
      id: 'net.cellular-card', phase: 'Мобильная сеть', title: 'Карточка из мобильной сети уходит в relay',
      covers: ['mobile-cross-network'], needs: ['net.cellular-open'],
      run: async (ctx) => {
        const runtime = need(ctx.board.current(), 'открытой доски');
        const title = `Из мобильной сети ${ctx.runId}`;
        await runtime.createCard({ title, columnId: need(ctx.columns, 'колонок')[0]!.id });
        ctx.phaseCards.push(title);
        const settled = await waitQueueEmpty(ctx, 60_000);
        const current = ctx.board.current();
        expectThat(settled, `карточка не ушла в relay за минуту: ${current?.lastError || 'нет ошибки'}`);
        return pass('опубликована в relay');
      },
    },
    {
      id: 'net.node-from-cellular', phase: 'Мобильная сеть', title: 'Узел из мобильной сети', needs: ['phase.cellular'],
      run: async () => {
        try {
          await getBackendVersion();
          return info('узел доступен и из мобильной сети (публичный адрес)');
        } catch {
          return info('узел недоступен из мобильной сети — ожидаемо для адреса в домашней сети');
        }
      },
    },
    // ---- Без сети ----------------------------------------------------------
    promptStep(PROMPTS.offline, ['board.open']),
    {
      id: 'offline.card', phase: 'Без сети', title: 'Карточка без сети создаётся и ждёт в очереди',
      covers: ['mobile-offline-card'], needs: ['phase.offline'],
      run: async (ctx) => {
        const runtime = need(ctx.board.current(), 'открытой доски');
        const title = `Без сети ${ctx.runId}`;
        await runtime.createCard({ title, columnId: need(ctx.columns, 'колонок')[0]!.id });
        ctx.phaseCards.push(title);
        await wait(ctx, 500);
        const current = need(ctx.board.current(), 'открытой доски');
        expectThat(current.snapshot?.cards.some((card) => card.title === title), 'карточка не появилась на доске');
        return queued(current) > 0 ? pass(`в очереди: ${queued(current)}`)
          : warn('карточка видна, но очередь пуста: телефон, похоже, не офлайн');
      },
    },
    // ---- Снова Wi-Fi -------------------------------------------------------
    promptStep(PROMPTS.wifi, ['board.open']),
    {
      id: 'back.queue', phase: 'Снова Wi-Fi', title: 'Очередь отправляется сама', covers: ['mobile-offline-card'],
      needs: ['phase.wifi'],
      run: async (ctx) => {
        const settled = await waitQueueEmpty(ctx, 90_000);
        const current = ctx.board.current();
        expectThat(settled, `за 90 с очередь не опустела: ждут ${current ? queued(current) : '?'}, ${current?.lastError || ''}`);
        return pass('очередь пуста');
      },
    },
    {
      id: 'back.node', phase: 'Снова Wi-Fi', title: 'Карточки из мобильной сети и без сети есть на узле',
      covers: ['mobile-offline-card', 'mobile-cross-network'], needs: ['phase.wifi'],
      run: async (ctx) => {
        if (!ctx.phaseCards.length) return skip('в прошлых фазах карточки не создавались');
        const board = need(ctx.boardA, 'доски A');
        let missing = ctx.phaseCards;
        await until(ctx, async () => {
          const titles = new Set((await getCards(board.id)).items.map((card) => card.title));
          missing = ctx.phaseCards.filter((title) => !titles.has(title));
          return missing.length === 0;
        }, 90_000, 5000);
        expectThat(!missing.length, `за 90 с узел не получил: ${missing.join(', ')}`);
        return pass(ctx.phaseCards.join(', '));
      },
    },
    {
      id: 'cleanup', phase: 'Уборка', title: 'Удалить доски прогона', needs: ['data.boards'],
      run: async (ctx) => {
        ctx.board.close();
        const removed: string[] = [];
        for (const board of [ctx.boardA, ctx.boardB]) {
          if (!board) continue;
          try {
            await deleteBoard(board.id);
            removed.push(board.name);
          } catch (error) {
            return warn(`не удалось удалить «${board.name}»: ${error instanceof Error ? error.message : String(error)}. Удалите её в web или запустите проверку снова в Wi-Fi.`);
          }
        }
        return pass(`удалены: ${removed.length}; «${TEST_WORKSPACE}» и «${CROSS_BOARD}» оставлены`);
      },
    },
  ];
}
