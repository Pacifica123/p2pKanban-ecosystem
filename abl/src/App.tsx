import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import {
  createBoard,
  createWorkspace,
  getVaultStatus,
  listBoards,
  listWorkspaces,
  openBoard,
} from './features/planner/api/workspace';
import {
  createCard,
  createChecklist,
  createChecklistItem,
  createColumn,
  deleteCard,
  deleteChecklist,
  deleteChecklistItem,
  getPendingChangeCount,
  listCards,
  listChecklistItems,
  listChecklists,
  listColumns,
  moveCard,
  setCardArchived,
  setChecklistItemDone,
  swapCardOrder,
} from './features/planner/api/planner';
import {
  createComment,
  createLabel,
  deleteComment,
  deleteLabel,
  getAppearance,
  getUnsyncedParityCount,
  listActivity,
  listCardLabelIds,
  listComments,
  listLabels,
  setAppearance,
  setCardLabel,
} from './features/parity/api/parity';
import { getBackendVersion } from './features/system/api/version';
import { getIntegrationCapabilities, takeDeepLinkIntents } from './features/system/api/integration';
import { getLanBridgeStatus, listLanBridgeAddresses, startLanBridge, stopLanBridge } from './features/system/api/lanBridge';
import { getApiTransportKind } from './shared/api/client';
import type {
  ActivitySummary,
  AppearanceSummary,
  BackendVersion,
  BoardSummary,
  CardSummary,
  ChecklistItemSummary,
  ChecklistSummary,
  ColumnSummary,
  CommentSummary,
  DeepLinkIntentSummary,
  IntegrationCapabilities,
  LabelSummary,
  LanBridgeStatus,
  VaultStatus,
  WorkspaceSummary,
} from './shared/api/types';

function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Native operation failed';
}

function prettyJson(value: string): string {
  try {
    return JSON.stringify(JSON.parse(value) as unknown, null, 2);
  } catch {
    return value;
  }
}

export default function App() {
  const [health, setHealth] = useState<BackendVersion | null>(null);
  const [vault, setVault] = useState<VaultStatus | null>(null);
  const [integration, setIntegration] = useState<IntegrationCapabilities | null>(null);
  const [deepLinkIntents, setDeepLinkIntents] = useState<DeepLinkIntentSummary[]>([]);
  const [lanBridgeAddresses, setLanBridgeAddresses] = useState<string[]>([]);
  const [lanBridgeAddress, setLanBridgeAddress] = useState('');
  const [lanBridgeTtl, setLanBridgeTtl] = useState('300');
  const [lanBridgeStatus, setLanBridgeStatus] = useState<LanBridgeStatus | null>(null);
  const [lanBridgeCapability, setLanBridgeCapability] = useState('');
  const [lanBridgeDevicePublicKey, setLanBridgeDevicePublicKey] = useState('');
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState<WorkspaceSummary | null>(null);
  const [boards, setBoards] = useState<BoardSummary[]>([]);
  const [openedBoard, setOpenedBoard] = useState<BoardSummary | null>(null);
  const [columns, setColumns] = useState<ColumnSummary[]>([]);
  const [cards, setCards] = useState<CardSummary[]>([]);
  const [selectedCard, setSelectedCard] = useState<CardSummary | null>(null);
  const [checklists, setChecklists] = useState<ChecklistSummary[]>([]);
  const [checklistItems, setChecklistItems] = useState<Record<string, ChecklistItemSummary[]>>({});
  const [labels, setLabels] = useState<LabelSummary[]>([]);
  const [cardLabelIds, setCardLabelIds] = useState<string[]>([]);
  const [comments, setComments] = useState<CommentSummary[]>([]);
  const [appearance, setAppearanceValue] = useState<AppearanceSummary | null>(null);
  const [activity, setActivity] = useState<ActivitySummary[]>([]);
  const [pendingCount, setPendingCount] = useState('0');
  const [unsyncedParityCount, setUnsyncedParityCount] = useState('0');
  const [showArchived, setShowArchived] = useState(false);
  const [workspaceTitle, setWorkspaceTitle] = useState('');
  const [boardTitle, setBoardTitle] = useState('');
  const [columnTitle, setColumnTitle] = useState('');
  const [cardTitle, setCardTitle] = useState('');
  const [cardColumnId, setCardColumnId] = useState('');
  const [checklistTitle, setChecklistTitle] = useState('');
  const [itemDrafts, setItemDrafts] = useState<Record<string, string>>({});
  const [labelName, setLabelName] = useState('');
  const [labelColor, setLabelColor] = useState('');
  const [commentDraft, setCommentDraft] = useState('');
  const [appearanceDraft, setAppearanceDraft] = useState('{}');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([
      getBackendVersion(),
      getVaultStatus(),
      listWorkspaces(),
      getIntegrationCapabilities(),
      takeDeepLinkIntents(),
      listLanBridgeAddresses(),
      getLanBridgeStatus(),
    ])
      .then(([healthValue, vaultValue, workspaceValues, integrationValue, intents, bridgeAddresses, bridgeStatus]) => {
        setHealth(healthValue);
        setVault(vaultValue);
        setWorkspaces(workspaceValues);
        setIntegration(integrationValue);
        setDeepLinkIntents(intents.slice(-5));
        setLanBridgeAddresses(bridgeAddresses);
        setLanBridgeAddress((current) => current || bridgeAddresses[0] || '');
        setLanBridgeStatus(bridgeStatus);
      })
      .catch((reason: unknown) => setError(message(reason)));

    const onFocus = () => { void refreshIntegration(); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, []);

  async function refreshIntegration(): Promise<void> {
    try {
      const [capabilities, intents] = await Promise.all([
        getIntegrationCapabilities(),
        takeDeepLinkIntents(),
      ]);
      setIntegration(capabilities);
      if (intents.length > 0) {
        setDeepLinkIntents((current) => [...current, ...intents].slice(-5));
      }
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function refreshLanBridge(): Promise<void> {
    try {
      const [addresses, status] = await Promise.all([listLanBridgeAddresses(), getLanBridgeStatus()]);
      setLanBridgeAddresses(addresses);
      setLanBridgeAddress((current) => addresses.includes(current) ? current : (addresses[0] || ''));
      setLanBridgeStatus(status);
      if (status.lifecycle !== 'listening') {
        setLanBridgeCapability('');
        setLanBridgeDevicePublicKey('');
      }
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function startLanBridgeSession(): Promise<void> {
    setError(null);
    if (!lanBridgeAddress) {
      setError('No private/link-local IPv4 address is available for the bounded LAN bridge.');
      return;
    }
    try {
      const ttl = Number(lanBridgeTtl);
      const started = await startLanBridge(lanBridgeAddress, ttl);
      setLanBridgeStatus(started);
      setLanBridgeCapability(started.capability);
      setLanBridgeDevicePublicKey(started.devicePublicKey);
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function stopLanBridgeSession(): Promise<void> {
    setError(null);
    try {
      const stopped = await stopLanBridge();
      setLanBridgeStatus(stopped);
      setLanBridgeCapability('');
      setLanBridgeDevicePublicKey('');
    } catch (reason) {
      setError(message(reason));
    }
  }

  function clearBoardState(): void {
    setOpenedBoard(null);
    setColumns([]);
    setCards([]);
    setSelectedCard(null);
    setChecklists([]);
    setChecklistItems({});
    setLabels([]);
    setCardLabelIds([]);
    setComments([]);
    setAppearanceValue(null);
    setAppearanceDraft('{}');
    setActivity([]);
    setPendingCount('0');
    setUnsyncedParityCount('0');
  }

  async function chooseWorkspace(workspace: WorkspaceSummary): Promise<void> {
    setError(null);
    clearBoardState();
    setSelectedWorkspace(workspace);
    try {
      setBoards(await listBoards(workspace.id));
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function loadCardDetails(workspaceId: string, card: CardSummary): Promise<void> {
    const [lists, labelIds, commentValues] = await Promise.all([
      listChecklists(workspaceId, card.id),
      listCardLabelIds(workspaceId, card.id),
      listComments(workspaceId, card.id),
    ]);
    const itemPairs = await Promise.all(
      lists.map(async (checklist) => [checklist.id, await listChecklistItems(workspaceId, checklist.id)] as const),
    );
    setSelectedCard(card);
    setChecklists(lists);
    setChecklistItems(Object.fromEntries(itemPairs));
    setCardLabelIds(labelIds);
    setComments(commentValues);
  }

  async function loadBoard(
    workspace: WorkspaceSummary,
    board: BoardSummary,
    includeArchived = showArchived,
  ): Promise<void> {
    const [columnValues, cardValues, pending, labelValues, appearanceValue, activityValues, unsynced] = await Promise.all([
      listColumns(workspace.id, board.id),
      listCards(workspace.id, board.id, includeArchived),
      getPendingChangeCount(workspace.id, board.id),
      listLabels(workspace.id, board.id),
      getAppearance(workspace.id, board.id),
      listActivity(workspace.id, board.id, 50),
      getUnsyncedParityCount(workspace.id, board.id),
    ]);
    setColumns(columnValues);
    setCards(cardValues);
    setPendingCount(pending.count);
    setLabels(labelValues);
    setAppearanceValue(appearanceValue);
    setAppearanceDraft(prettyJson(appearanceValue.settingsJson));
    setActivity(activityValues);
    setUnsyncedParityCount(unsynced.count);
    setCardColumnId((current) => current || columnValues[0]?.id || '');
    if (selectedCard) {
      const fresh = cardValues.find((card) => card.id === selectedCard.id);
      if (fresh) await loadCardDetails(workspace.id, fresh);
      else {
        setSelectedCard(null);
        setChecklists([]);
        setChecklistItems({});
        setCardLabelIds([]);
        setComments([]);
      }
    }
  }

  async function chooseBoard(board: BoardSummary): Promise<void> {
    if (!selectedWorkspace) return;
    setError(null);
    try {
      const opened = await openBoard(selectedWorkspace.id, board.id);
      setOpenedBoard(opened);
      setSelectedCard(null);
      setChecklists([]);
      setChecklistItems({});
      setCardLabelIds([]);
      setComments([]);
      await loadBoard(selectedWorkspace, opened);
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function refreshBoard(includeArchived = showArchived): Promise<void> {
    if (!selectedWorkspace || !openedBoard) return;
    await loadBoard(selectedWorkspace, openedBoard, includeArchived);
  }

  async function submitWorkspace(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    try {
      const workspace = await createWorkspace(workspaceTitle);
      setWorkspaceTitle('');
      setWorkspaces((current) => [...current, workspace].sort((a, b) => a.title.localeCompare(b.title)));
      await chooseWorkspace(workspace);
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitBoard(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace) return;
    setError(null);
    try {
      const board = await createBoard(selectedWorkspace.id, boardTitle);
      setBoardTitle('');
      setBoards((current) => [...current, board].sort((a, b) => a.title.localeCompare(b.title)));
      await chooseBoard(board);
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitColumn(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace || !openedBoard) return;
    setError(null);
    try {
      const column = await createColumn(selectedWorkspace.id, openedBoard.id, columnTitle);
      setColumnTitle('');
      if (!cardColumnId) setCardColumnId(column.id);
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitCard(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace || !openedBoard || !cardColumnId) return;
    setError(null);
    try {
      await createCard(selectedWorkspace.id, openedBoard.id, cardColumnId, cardTitle);
      setCardTitle('');
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function mutateCard(operation: () => Promise<unknown>): Promise<void> {
    setError(null);
    try {
      await operation();
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitChecklist(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace || !selectedCard) return;
    setError(null);
    try {
      await createChecklist(selectedWorkspace.id, selectedCard.id, checklistTitle);
      setChecklistTitle('');
      await loadCardDetails(selectedWorkspace.id, selectedCard);
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitChecklistItem(event: FormEvent, checklist: ChecklistSummary): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace || !selectedCard) return;
    const title = itemDrafts[checklist.id] ?? '';
    setError(null);
    try {
      await createChecklistItem(selectedWorkspace.id, checklist.id, title);
      setItemDrafts((current) => ({ ...current, [checklist.id]: '' }));
      await loadCardDetails(selectedWorkspace.id, selectedCard);
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function mutateChecklist(operation: () => Promise<unknown>): Promise<void> {
    if (!selectedWorkspace || !selectedCard) return;
    setError(null);
    try {
      await operation();
      await loadCardDetails(selectedWorkspace.id, selectedCard);
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitLabel(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace || !openedBoard) return;
    setError(null);
    try {
      await createLabel(selectedWorkspace.id, openedBoard.id, labelName, labelColor);
      setLabelName('');
      setLabelColor('');
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function removeLabel(labelId: string): Promise<void> {
    if (!selectedWorkspace || !openedBoard) return;
    setError(null);
    try {
      await deleteLabel(selectedWorkspace.id, openedBoard.id, labelId);
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function toggleCardLabel(labelId: string, assigned: boolean): Promise<void> {
    if (!selectedWorkspace || !selectedCard) return;
    setError(null);
    try {
      await setCardLabel(selectedWorkspace.id, selectedCard.id, labelId, assigned);
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitComment(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace || !selectedCard) return;
    setError(null);
    try {
      await createComment(selectedWorkspace.id, selectedCard.id, commentDraft);
      setCommentDraft('');
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function removeComment(commentId: string): Promise<void> {
    if (!selectedWorkspace) return;
    setError(null);
    try {
      await deleteComment(selectedWorkspace.id, commentId);
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  async function submitAppearance(event: FormEvent): Promise<void> {
    event.preventDefault();
    if (!selectedWorkspace || !openedBoard) return;
    setError(null);
    try {
      const value = await setAppearance(selectedWorkspace.id, openedBoard.id, appearanceDraft);
      setAppearanceValue(value);
      setAppearanceDraft(prettyJson(value.settingsJson));
      await refreshBoard();
    } catch (reason) {
      setError(message(reason));
    }
  }

  return (
    <main className="app-shell" aria-labelledby="app-title">
      <header className="topbar">
        <div>
          <p className="eyebrow">ARCH NATIVE · A14 BOUNDED LAN COMPATIBILITY</p>
          <h1 id="app-title">p2pKanban</h1>
        </div>
        <div className="status-stack" aria-live="polite">
          <span>mode: <strong>{getApiTransportKind()}</strong></span>
          <span>{health ? `${health.service} ${health.version} · ${health.status}` : 'native IPC…'}</span>
          <span>vault: <strong>{vault?.mode ?? 'checking'}</strong>{vault ? ` · ${vault.state} · durable secrets ${vault.durable === 'true' ? 'enabled' : 'disabled'}` : ''}</span>
          <span>roaming-capable pending: <strong>{pendingCount}</strong></span>
          <span>roaming/1 unsupported parity changes: <strong>{unsyncedParityCount}</strong></span>
          <span>session: <strong>{integration?.sessionType ?? 'detecting'}</strong>{integration ? ` · ${integration.desktop}` : ''}</span>
          <span>notifications/tray: <strong>{integration ? `${integration.notifications}/${integration.statusNotifier}` : 'detecting'}</strong></span>
          <span>LAN bridge: <strong>{lanBridgeStatus?.lifecycle ?? 'stopped'}</strong></span>
        </div>
      </header>

      {error ? <div className="error-banner" role="alert">{error}</div> : null}

      <section className="integration-strip" aria-label="Desktop integration capabilities">
        <div>
          <p className="kicker">A13 lifecycle/integration</p>
          <strong>{integration?.sessionType ?? 'unknown'} · {integration?.desktop ?? 'desktop unknown'}</strong>
          <span>D-Bus {integration?.sessionBus ?? 'detecting'} · notifications {integration?.notifications ?? 'detecting'} · StatusNotifier {integration?.statusNotifier ?? 'detecting'} · portal {integration?.portal ?? 'detecting'}</span>
        </div>
        <div className="integration-actions">
          <span>tray lifecycle: <strong>{integration?.trayLifecycle ?? 'disabled'}</strong> · systemd user service: <strong>{integration?.systemdUserService ?? 'disabled'}</strong></span>
          <button type="button" onClick={() => void refreshIntegration()}>Refresh integration</button>
        </div>
        <div className="deep-link-history">
          <span>Validated deep-link intents: <strong>{deepLinkIntents.length}</strong></span>
          {deepLinkIntents.length === 0 ? <small>None received in this session.</small> : deepLinkIntents.map((intent, index) => (
            <small key={`${intent.canonical}-${index}`}>{intent.kind}{intent.entityId ? ` · ${intent.entityId}` : ''}</small>
          ))}
        </div>
      </section>

      <section className="lan-bridge-strip" aria-label="Bounded LAN compatibility bridge">
        <div className="lan-bridge-summary">
          <p className="kicker">A14 bounded LAN compatibility</p>
          <strong>{lanBridgeStatus?.lifecycle ?? 'stopped'} · off by default</strong>
          <span>Short-lived pairing/migration bridge only. Normal planner operation does not listen on TCP.</span>
          <small>Requires durable SecretVault; one authenticated request consumes the capability and closes the listener.</small>
        </div>
        <div className="lan-bridge-controls">
          <label>LAN address
            <select value={lanBridgeAddress} disabled={lanBridgeStatus?.lifecycle === 'listening'} onChange={(event) => setLanBridgeAddress(event.target.value)}>
              {lanBridgeAddresses.length === 0 ? <option value="">No private IPv4 detected</option> : lanBridgeAddresses.map((address) => <option key={address} value={address}>{address}</option>)}
            </select>
          </label>
          <label>TTL
            <select value={lanBridgeTtl} disabled={lanBridgeStatus?.lifecycle === 'listening'} onChange={(event) => setLanBridgeTtl(event.target.value)}>
              <option value="120">2 minutes</option>
              <option value="300">5 minutes</option>
              <option value="600">10 minutes</option>
            </select>
          </label>
          <div className="lan-bridge-buttons">
            <button type="button" disabled={vault?.durable !== 'true' || !lanBridgeAddress || lanBridgeStatus?.lifecycle === 'listening'} onClick={() => void startLanBridgeSession()}>Start compatibility bridge</button>
            <button type="button" disabled={lanBridgeStatus?.lifecycle !== 'listening'} onClick={() => void stopLanBridgeSession()}>Stop</button>
            <button type="button" onClick={() => void refreshLanBridge()}>Refresh</button>
          </div>
        </div>
        <div className="lan-bridge-session">
          <span>endpoint: <strong>{lanBridgeStatus?.endpoint || 'not listening'}</strong></span>
          <span>attempts: <strong>{lanBridgeStatus?.attempts ?? '0'}</strong>{lanBridgeStatus?.lastResult ? ` · ${lanBridgeStatus.lastResult}` : ''}</span>
          {lanBridgeCapability ? (
            <>
              <small>Pairing descriptor — the private device key never leaves this native process:</small>
              <code>device public key: {lanBridgeDevicePublicKey}</code>
              <code>one-time capability: {lanBridgeCapability}</code>
            </>
          ) : lanBridgeStatus?.lifecycle === 'listening' ? (
            <small>Capability is not recoverable after a WebView reload. Stop and start a new bridge if it was lost.</small>
          ) : (
            <small>No capability is active.</small>
          )}
        </div>
      </section>

      <section className="planner-grid" aria-label="Local durable planner">
        <aside className="panel">
          <div className="panel-heading"><div><p className="kicker">Local profile</p><h2>Workspaces</h2></div><span className="count">{workspaces.length}</span></div>
          <form className="create-row" onSubmit={(event) => void submitWorkspace(event)}>
            <input aria-label="Workspace title" maxLength={120} placeholder="New workspace" value={workspaceTitle} onChange={(event) => setWorkspaceTitle(event.target.value)} />
            <button type="submit">Create</button>
          </form>
          <div className="item-list">
            {workspaces.length === 0 ? <p className="empty">No workspaces yet.</p> : null}
            {workspaces.map((workspace) => (
              <button className={selectedWorkspace?.id === workspace.id ? 'item active' : 'item'} key={workspace.id} type="button" onClick={() => void chooseWorkspace(workspace)}>
                <span>{workspace.title || 'Untitled migrated workspace'}</span><small>epoch {workspace.accessEpoch}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="panel">
          <div className="panel-heading"><div><p className="kicker">{selectedWorkspace ? selectedWorkspace.title : 'Select a workspace'}</p><h2>Boards</h2></div><span className="count">{boards.length}</span></div>
          <form className="create-row" onSubmit={(event) => void submitBoard(event)}>
            <input aria-label="Board title" disabled={!selectedWorkspace} maxLength={120} placeholder={selectedWorkspace ? 'New board' : 'Choose workspace first'} value={boardTitle} onChange={(event) => setBoardTitle(event.target.value)} />
            <button disabled={!selectedWorkspace} type="submit">Create</button>
          </form>
          <div className="item-list">
            {!selectedWorkspace ? <p className="empty">Choose a workspace to load durable boards.</p> : null}
            {selectedWorkspace && boards.length === 0 ? <p className="empty">No boards yet.</p> : null}
            {boards.map((board) => (
              <button className={openedBoard?.id === board.id ? 'item active' : 'item'} key={board.id} type="button" onClick={() => void chooseBoard(board)}>
                <span>{board.title || 'Untitled migrated board'}</span><small>open</small>
              </button>
            ))}
          </div>
        </section>

        <section className="panel board-stage">
          <p className="kicker">Opened board</p>
          {!openedBoard || !selectedWorkspace ? (
            <><h2>Nothing open</h2><p className="empty">Create or choose a board. No localhost backend is involved.</p></>
          ) : (
            <>
              <div className="board-heading">
                <div>
                  <h2>{openedBoard.title}</h2>
                  <p className="lede">Planner data and A12 parity data are durable in SQLite. Appearance uses the existing roaming/1 appearance operation; label/comment mutations remain explicit local-only parity changes until a compatible wire operation exists.</p>
                </div>
                <label className="toggle"><input type="checkbox" checked={showArchived} onChange={(event) => { const includeArchived = event.target.checked; setShowArchived(includeArchived); void refreshBoard(includeArchived); }} /> show archived</label>
              </div>

              <div className="planner-actions">
                <form className="create-row" onSubmit={(event) => void submitColumn(event)}>
                  <input aria-label="Column title" maxLength={120} placeholder="New column" value={columnTitle} onChange={(event) => setColumnTitle(event.target.value)} />
                  <button type="submit">Add column</button>
                </form>
                <form className="create-row card-create" onSubmit={(event) => void submitCard(event)}>
                  <input aria-label="Card title" disabled={columns.length === 0} maxLength={120} placeholder={columns.length ? 'New card' : 'Create a column first'} value={cardTitle} onChange={(event) => setCardTitle(event.target.value)} />
                  <select aria-label="Card column" disabled={columns.length === 0} value={cardColumnId} onChange={(event) => setCardColumnId(event.target.value)}>
                    {columns.map((column) => <option key={column.id} value={column.id}>{column.title || 'Untitled column'}</option>)}
                  </select>
                  <button disabled={!cardColumnId} type="submit">Add card</button>
                </form>
              </div>

              <section className="parity-grid" aria-label="Board parity controls">
                <section className="parity-card">
                  <div className="section-heading"><div><p className="kicker">Labels</p><h3>Board labels</h3></div><span className="count">{labels.length}</span></div>
                  <form className="create-row label-create" onSubmit={(event) => void submitLabel(event)}>
                    <input aria-label="Label name" maxLength={120} placeholder="Label name" value={labelName} onChange={(event) => setLabelName(event.target.value)} />
                    <input aria-label="Label color token" maxLength={128} placeholder="Color/token" value={labelColor} onChange={(event) => setLabelColor(event.target.value)} />
                    <button type="submit">Add</button>
                  </form>
                  <div className="label-list">
                    {labels.length === 0 ? <p className="empty">No labels.</p> : null}
                    {labels.map((label) => (
                      <span className="label-chip" key={label.id} title={label.color || 'no color token'}>
                        <span>{label.name}</span>
                        <button className="link danger" type="button" onClick={() => void removeLabel(label.id)} aria-label={`Delete label ${label.name}`}>×</button>
                      </span>
                    ))}
                  </div>
                  <p className="constraint-note">Label CRUD is durable and audited locally; roaming/1 has no label mutation operation, so changes are counted in the unsupported parity ledger instead of being silently dropped.</p>
                </section>

                <section className="parity-card">
                  <div className="section-heading"><div><p className="kicker">Appearance</p><h3>Board appearance JSON</h3></div><span className="count">roaming/1</span></div>
                  <form className="appearance-form" onSubmit={(event) => void submitAppearance(event)}>
                    <textarea aria-label="Board appearance JSON" rows={7} value={appearanceDraft} onChange={(event) => setAppearanceDraft(event.target.value)} />
                    <div className="appearance-meta"><small>{appearance?.updatedAt ? `updated ${appearance.updatedAt}` : 'default appearance'}</small><button type="submit">Save appearance</button></div>
                  </form>
                  <p className="constraint-note">The native service normalizes <code>boardId</code>; appearance uses the already proven <code>board.appearance.put</code> path.</p>
                </section>

                <section className="parity-card activity-card">
                  <div className="section-heading"><div><p className="kicker">Activity</p><h3>Local provenance</h3></div><span className="count">{activity.length}</span></div>
                  <div className="activity-list">
                    {activity.length === 0 ? <p className="empty">No activity yet. A12 does not fabricate historical entries.</p> : null}
                    {activity.map((entry) => (
                      <article className="activity-entry" key={entry.id}>
                        <strong>{entry.kind}</strong>
                        <span>{entry.entityType}{entry.entityId ? ` · ${entry.entityId}` : ''}</span>
                        <time>{entry.occurredAt}</time>
                      </article>
                    ))}
                  </div>
                </section>
              </section>

              {columns.length === 0 ? <p className="empty">Create the first column to start the offline planner.</p> : null}
              <div className="kanban-columns">
                {columns.map((column) => (
                  <section className="kanban-column" key={column.id}>
                    <div className="column-heading"><h3>{column.title || 'Untitled column'}</h3><span className="count">{cards.filter((card) => card.columnId === column.id).length}</span></div>
                    <div className="card-stack">
                      {cards.filter((card) => card.columnId === column.id).map((card, cardIndex, columnCards) => (
                        <article className={selectedCard?.id === card.id ? 'kanban-card selected' : 'kanban-card'} key={card.id}>
                          <button className="card-title" type="button" onClick={() => selectedWorkspace && void loadCardDetails(selectedWorkspace.id, card)}>{card.title}</button>
                          {card.archived === 'true' ? <span className="archived-badge">archived</span> : null}
                          <select aria-label={`Move ${card.title}`} value={card.columnId} onChange={(event) => selectedWorkspace && void mutateCard(() => moveCard(selectedWorkspace.id, card.id, event.target.value))}>
                            {columns.map((target) => <option key={target.id} value={target.id}>{target.title || 'Untitled column'}</option>)}
                          </select>
                          <div className="card-actions">
                            <button disabled={cardIndex === 0} type="button" onClick={() => selectedWorkspace && cardIndex > 0 && void mutateCard(() => swapCardOrder(selectedWorkspace.id, card.id, columnCards[cardIndex - 1].id))}>↑</button>
                            <button disabled={cardIndex >= columnCards.length - 1} type="button" onClick={() => selectedWorkspace && cardIndex < columnCards.length - 1 && void mutateCard(() => swapCardOrder(selectedWorkspace.id, card.id, columnCards[cardIndex + 1].id))}>↓</button>
                            <button type="button" onClick={() => selectedWorkspace && void mutateCard(() => setCardArchived(selectedWorkspace.id, card.id, card.archived !== 'true'))}>{card.archived === 'true' ? 'Restore' : 'Archive'}</button>
                            <button className="danger" type="button" onClick={() => selectedWorkspace && void mutateCard(() => deleteCard(selectedWorkspace.id, card.id))}>Delete</button>
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>
                ))}
              </div>

              <section className="card-details">
                {selectedCard ? (
                  <>
                    <div className="panel-heading"><div><p className="kicker">Card details</p><h3>{selectedCard.title}</h3></div><span className="count">{checklists.length} lists</span></div>

                    <section className="card-parity-grid">
                      <section className="parity-card compact-card">
                        <div className="section-heading"><strong>Labels</strong><span className="count">{cardLabelIds.length}</span></div>
                        <div className="label-assignment-list">
                          {labels.length === 0 ? <p className="empty">Create board labels above first.</p> : null}
                          {labels.map((label) => (
                            <label className="label-assignment" key={label.id}>
                              <input type="checkbox" checked={cardLabelIds.includes(label.id)} onChange={(event) => void toggleCardLabel(label.id, event.target.checked)} />
                              <span>{label.name}</span><small>{label.color || 'no color'}</small>
                            </label>
                          ))}
                        </div>
                      </section>

                      <section className="parity-card compact-card">
                        <div className="section-heading"><strong>Comments</strong><span className="count">{comments.length}</span></div>
                        <form className="comment-form" onSubmit={(event) => void submitComment(event)}>
                          <textarea aria-label="New comment" maxLength={65536} rows={3} placeholder="Write a local durable comment" value={commentDraft} onChange={(event) => setCommentDraft(event.target.value)} />
                          <button type="submit">Add comment</button>
                        </form>
                        <div className="comment-list">
                          {comments.map((comment) => (
                            <article className="comment-entry" key={comment.id}>
                              <div><strong>{comment.authorUserId || 'local/imported actor'}</strong><time>{comment.createdAt}</time></div>
                              <p>{comment.body}</p>
                              <button className="link danger" type="button" onClick={() => void removeComment(comment.id)}>Delete</button>
                            </article>
                          ))}
                        </div>
                      </section>
                    </section>

                    <form className="create-row" onSubmit={(event) => void submitChecklist(event)}>
                      <input aria-label="Checklist title" maxLength={120} placeholder="New checklist" value={checklistTitle} onChange={(event) => setChecklistTitle(event.target.value)} />
                      <button type="submit">Add checklist</button>
                    </form>
                    <div className="checklist-grid">
                      {checklists.map((checklist) => (
                        <section className="checklist" key={checklist.id}>
                          <div className="checklist-heading"><strong>{checklist.title}</strong><button className="link danger" type="button" onClick={() => selectedWorkspace && void mutateChecklist(() => deleteChecklist(selectedWorkspace.id, checklist.id))}>Delete</button></div>
                          <div className="checklist-items">
                            {(checklistItems[checklist.id] ?? []).map((item) => (
                              <label className="checklist-item" key={item.id}>
                                <input type="checkbox" checked={item.isDone === 'true'} onChange={(event) => selectedWorkspace && void mutateChecklist(() => setChecklistItemDone(selectedWorkspace.id, item.id, event.target.checked))} />
                                <span>{item.title}</span>
                                <button className="link danger" type="button" onClick={() => selectedWorkspace && void mutateChecklist(() => deleteChecklistItem(selectedWorkspace.id, item.id))}>×</button>
                              </label>
                            ))}
                          </div>
                          <form className="create-row compact" onSubmit={(event) => void submitChecklistItem(event, checklist)}>
                            <input aria-label={`New item for ${checklist.title}`} maxLength={120} placeholder="Checklist item" value={itemDrafts[checklist.id] ?? ''} onChange={(event) => setItemDrafts((current) => ({ ...current, [checklist.id]: event.target.value }))} />
                            <button type="submit">Add</button>
                          </form>
                        </section>
                      ))}
                    </div>
                  </>
                ) : <p className="empty">Select a card to manage labels, comments, and durable checklists.</p>}
              </section>
            </>
          )}
        </section>
      </section>

      <footer><span>A14 bounded LAN compatibility · explicit TTL + one-time encrypted capability + single allowlisted endpoint</span><span>No firewall mutation, mDNS, daemon, or default listener; A13 desktop integration remains foreground-only</span></footer>
    </main>
  );
}
