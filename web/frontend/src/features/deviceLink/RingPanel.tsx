import { ErrorDetails } from '@/shared/ui/ErrorDetails';
import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiRequest } from '@/shared/api/client';
import { Panel } from '@/shared/ui/Panel';
import { Button } from '@/shared/ui/Button';
import { TextField } from '@/shared/ui/Field';
import { Badge } from '@/shared/ui/Badge';

// R2 of the device ring: contracts/account-ring/1 and contracts/keyring/1.
type DeviceKind = 'web' | 'android' | 'arch';
type Member = { publicKey: string; name: string; kind: DeviceKind; role: string; addedBy: string | null };
type Presence = { publicKey: string; seenAt: number; software?: { direction: string; version: string } };
type Skew = { publicKey: string; missingProtocols: string[]; staleRing: boolean };
type KeyringItem = { kind: string; id: string; name?: string; rev: number; deleted: boolean; onThisNode: boolean };
type Published = { recordType: string; accepted: string[]; failed: string[] };
export type RingView = {
  enabled: boolean;
  nodePublicKey?: string;
  ring: null | {
    accountId: string;
    members: Member[];
    removed: { publicKey: string }[];
    relays: { urls: string[]; minAcks: number };
    rejected: { id: string; reason: string }[];
    pending: { id: string }[];
    readerOutdated: string[];
  };
  legacy: { publicKey: string; approvedAt: string }[];
  keyring: null | { summary: { boards: number; items: number }; copies: number; items: KeyringItem[] };
  presences: Presence[];
  skew: Skew[];
  lastSync: null | { at: number; quorum: boolean; fetched: number; newEntries: number; keyringCopies: number;
    presences: number; published: Published[]; errors: string[] };
  relays?: { urls: string[]; minAcks: number } | null;
};

export const KIND_LABELS: Record<DeviceKind, string> = { web: 'web-узел', android: 'Android', arch: 'Linux (abl)' };
const short = (key: string) => `${key.slice(0, 8)}…${key.slice(-4)}`;
const when = (seconds?: number) => (seconds ? new Date(seconds * 1000).toLocaleString('ru-RU') : 'не виделось');

/** Plain-language reason a device lags behind, from presence_skew. */
export function skewText(skew: Skew): string {
  const parts: string[] = [];
  if (skew.missingProtocols.length) parts.push(`не знает ${skew.missingProtocols.join(', ')} — нужна новая версия`);
  if (skew.staleRing) parts.push('видит старый журнал кольца');
  return parts.join('; ');
}

export function RingPanel() {
  const cache = useQueryClient();
  const query = useQuery({ queryKey: ['device-ring'], queryFn: () => apiRequest<RingView>('/ring') });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [nodeName, setNodeName] = useState('Домашний узел');
  const [drafts, setDrafts] = useState<Record<string, { name: string; kind: DeviceKind }>>({});
  async function run(path: string, body?: unknown) {
    setBusy(true); setError('');
    try {
      const view = await apiRequest<RingView>(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) });
      cache.setQueryData(['device-ring'], view);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  const view = query.data;
  const title = 'Кольцо устройств';
  if (query.isLoading) return <Panel title={title}><p className="muted">Загружаем кольцо…</p></Panel>;
  if (query.error || !view) return <Panel title={title}><p role="alert">{String(query.error ?? 'Нет ответа узла')}</p>
    <ErrorDetails message={String(query.error ?? 'Нет ответа узла')} error={query.error ?? undefined} operation="Кольцо устройств" /></Panel>;
  if (!view.enabled) return <Panel title={title}><p>Кольцу нужен включённый Nostr-роуминг этого узла (TRANSPORTS__NOSTR__ENABLED).</p></Panel>;
  const draft = (key: string) => drafts[key] ?? { name: '', kind: 'android' as DeviceKind };
  const setDraft = (key: string, next: Partial<{ name: string; kind: DeviceKind }>) =>
    setDrafts((all) => ({ ...all, [key]: { ...draft(key), ...next } }));
  const legacy = <>
    {view.legacy.length > 0 && <h4>Доверены по-старому, вне кольца</h4>}
    {view.legacy.map((device) => <div key={device.publicKey} className="panel" data-testid="ring-legacy">
      <p style={{ overflowWrap: 'anywhere' }}>Ключ {short(device.publicKey)} · доверие с {new Date(device.approvedAt).toLocaleDateString('ru-RU')}.
        Старая привязка истекает через 90 дней; в кольце членство бессрочное.</p>
      {view.ring && <div className="toolbar">
        <TextField label="Имя устройства" value={draft(device.publicKey).name} placeholder="Телефон"
          onChange={(e) => setDraft(device.publicKey, { name: e.target.value })} />
        <label>Вид <select value={draft(device.publicKey).kind}
          onChange={(e) => setDraft(device.publicKey, { kind: e.target.value as DeviceKind })}>
          {Object.entries(KIND_LABELS).map(([kind, label]) => <option key={kind} value={kind}>{label}</option>)}
        </select></label>
        <Button disabled={busy || !draft(device.publicKey).name.trim()} onClick={() => void run('/ring/migrate',
          { publicKey: device.publicKey, ...draft(device.publicKey) })}>Перенести в кольцо</Button>
      </div>}
    </div>)}
  </>;
  if (!view.ring) {
    return <Panel title={title} description="Одно кольцо на аккаунт: устройства в нём доверяют друг другу в любой сети, без срока.">
      {view.relays
        ? <p>Relay кольца: {view.relays.urls.join(', ')} (подтверждений: {view.relays.minAcks}).</p>
        : <p role="alert">Для кольца нужен хотя бы один relay wss:// в настройках узла.</p>}
      <TextField label="Имя этого узла в кольце" value={nodeName} onChange={(e) => setNodeName(e.target.value)} />
      <Button disabled={busy || !view.relays || !nodeName.trim()} onClick={() => void run('/ring/genesis', { name: nodeName })}>
        Создать кольцо</Button>
      {legacy}
      {error && <><p role="alert">{error}</p><ErrorDetails message={error} operation="Кольцо устройств" /></>}
    </Panel>;
  }
  const ring = view.ring;
  const presence = new Map(view.presences.map((p) => [p.publicKey, p]));
  const skew = new Map(view.skew.map((s) => [s.publicKey, s]));
  const elsewhere = (view.keyring?.items ?? []).filter((item) => !item.onThisNode && !item.deleted);
  const sync = view.lastSync;
  return <Panel title={title} description={`Аккаунт ${short(ring.accountId)} · устройств: ${ring.members.length}`}
    actions={<Button disabled={busy} onClick={() => void run('/ring/sync')}>Синхронизировать сейчас</Button>}>
    {ring.readerOutdated.length > 0 && <p role="alert">В журнале есть записи от более новой версии ({ring.readerOutdated.join(', ')}): обновите этот узел.</p>}
    <ul className="ring-members">
      {ring.members.map((member) => {
        const seen = presence.get(member.publicKey);
        const lag = skew.get(member.publicKey);
        const self = member.publicKey === view.nodePublicKey;
        return <li key={member.publicKey} data-testid="ring-member">
          <strong>{member.name}</strong> · {KIND_LABELS[member.kind] ?? member.kind} {self && <Badge tone="owner">этот узел</Badge>}
          <span className="muted" style={{ overflowWrap: 'anywhere' }}> · {short(member.publicKey)}</span>
          {!self && <span className="muted"> · {seen ? `${seen.software?.direction ?? ''} ${seen.software?.version ?? ''}, виделся ${when(seen.seenAt)}` : 'ещё не отмечался'}</span>}
          {lag && <div><Badge tone="warning">отстаёт</Badge> {skewText(lag)}</div>}
          <div className="toolbar">
            <TextField label="Новое имя" value={draft(member.publicKey).name} onChange={(e) => setDraft(member.publicKey, { name: e.target.value })} />
            <Button disabled={busy || !draft(member.publicKey).name.trim()}
              onClick={() => void run('/ring/rename', { publicKey: member.publicKey, name: draft(member.publicKey).name })}>Переименовать</Button>
          </div>
        </li>;
      })}
    </ul>
    {legacy}
    <h4>Связка ключей</h4>
    <p>Досок с ключами: {view.keyring?.summary.boards ?? 0} · элементов: {view.keyring?.summary.items ?? 0} · копий от других устройств: {view.keyring?.copies ?? 0}.</p>
    {elsewhere.length > 0 && <>
      <p>Созданы на других устройствах, на этот узел ещё не перенесены (это следующий этап):</p>
      <ul>{elsewhere.map((item) => <li key={`${item.kind}:${item.id}`}>{item.kind === 'space' ? 'Пространство' : item.kind === 'board' ? 'Доска' : item.kind} «{item.name ?? item.id}»</li>)}</ul>
    </>}
    <h4>Relay кольца</h4>
    <p>{ring.relays.urls.join(', ')} · нужно подтверждений: {ring.relays.minAcks}</p>
    {sync
      ? <div data-testid="ring-last-sync">
        <p>Последний обмен: {when(sync.at)} · {sync.quorum ? 'кворум relay собран' : 'кворум relay не собран'} · получено записей: {sync.fetched},
          новых записей журнала: {sync.newEntries}, связок: {sync.keyringCopies}, отметок: {sync.presences}.</p>
        {sync.published.map((p) => <p key={p.recordType} className="muted">{p.recordType}: приняли {p.accepted.length ? p.accepted.join(', ') : 'никто'}{p.failed.length ? `; отказ: ${p.failed.join(', ')}` : ''}</p>)}
        {sync.errors.length > 0 && <><p role="alert">Ошибки обмена: {sync.errors.join('; ')}</p>
          <ErrorDetails message={`Ошибки обмена с relay: ${sync.errors.join('; ')}`} operation="Кольцо устройств" stage="обмен с relay" /></>}
      </div>
      : <p className="muted">Обмена с relay ещё не было.</p>}
    {(ring.rejected.length > 0 || ring.pending.length > 0) && <p className="muted">Отклонено записей журнала: {ring.rejected.length}; ждут предков: {ring.pending.length}.</p>}
    {error && <><p role="alert">{error}</p><ErrorDetails message={error} operation="Кольцо устройств" /></>}
  </Panel>;
}
