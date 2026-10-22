import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import qrcode from 'qrcode-generator';
import { apiRequest } from '@/shared/api/client';
import { Button } from '@/shared/ui/Button';
import { ErrorDetails } from '@/shared/ui/ErrorDetails';

// R4 of the device ring: contracts/rendezvous/1. The node only shows codes;
// the phone scans. The backend reads the relay mailbox on every poll.
export type MeetingMode = 'invite' | 'join';
export type Meeting = {
  sessionId: string;
  mode: MeetingMode;
  status: 'waiting' | 'confirm' | 'welcomed' | 'done' | 'refused' | 'expired' | 'canceled';
  qrText: string | null;
  expiresAt: number;
  relays: string[];
  code: string | null;
  peer: null | { publicKey: string; name: string; kind: string; alreadyMember?: boolean;
    software?: { direction: string; version: string } };
  outcome: null | { by?: string; reason?: string; detail?: string; members?: number };
};

export const POLL_MS = 2500;
const KINDS: Record<string, string> = { web: 'web-узел', android: 'Android', arch: 'Linux (abl)' };

/** Why a meeting stopped, in words, from the refusal codes of rendezvous/1. */
export const REFUSAL_TEXT: Record<string, string> = {
  declined: 'добавление отклонили',
  expired: 'срок QR истёк — покажите новый код',
  contested: 'в почтовый ящик пришли два разных устройства — покажите новый код',
  'session-used': 'этот QR уже использован',
  'ring-merge-unsupported': 'устройство уже в другом кольце с другими участниками; слияние колец пока не поддерживается',
  'key-removed': 'ключ этого устройства удалён из кольца; удалённое устройство возвращается с новым ключом',
  'sponsor-not-admin': 'добавлять устройства может только admin кольца',
  'sponsor-stale': 'журнал или связка поручителя отстают — синхронизируйте кольцо и повторите',
  'joiner-outdated': 'входящему устройству нужна новая версия приложения',
  'welcome-invalid': 'ответ поручителя не прошёл проверку',
};

/** QR as an SVG of dark modules; scales with the box, crisp on any screen. */
export function QrImage({ text, size = 264 }: { text: string; size?: number }) {
  const path = useMemo(() => {
    const qr = qrcode(0, 'M');
    qr.addData(text, 'Byte');
    qr.make();
    const count = qr.getModuleCount();
    let d = '';
    for (let row = 0; row < count; row++) {
      for (let col = 0; col < count; col++) if (qr.isDark(row, col)) d += `M${col + 4} ${row + 4}h1v1h-1z`;
    }
    return { d, box: count + 8 };
  }, [text]);
  return <svg role="img" aria-label="QR-код встречи" data-testid="ring-qr" width={size} height={size}
    viewBox={`0 0 ${path.box} ${path.box}`} shapeRendering="crispEdges" style={{ background: '#fff', borderRadius: 8 }}>
    <path d={path.d} fill="#000" />
  </svg>;
}

function left(expiresAt: number, now: number) {
  const seconds = Math.max(0, expiresAt - Math.floor(now / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

export function RingQrMeeting({ hasRing, members }: { hasRing: boolean; members: number }) {
  const cache = useQueryClient();
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [memberOnly, setMemberOnly] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const open = meeting && ['waiting', 'confirm', 'welcomed'].includes(meeting.status);

  useEffect(() => {
    if (!open) return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    const poll = setInterval(() => {
      apiRequest<Meeting>(`/ring/rendezvous/${meeting.sessionId}`)
        .then((next) => { setMeeting(next); setError(''); })
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }, POLL_MS);
    return () => { clearInterval(tick); clearInterval(poll); };
  }, [open, meeting?.sessionId]);

  useEffect(() => {
    if (meeting?.status === 'done') void cache.invalidateQueries({ queryKey: ['device-ring'] });
  }, [meeting?.status, cache]);

  async function act(path: string, body?: unknown) {
    setBusy(true); setError('');
    try {
      setMeeting(await apiRequest<Meeting>(path, { method: 'POST', ...(body ? { body: JSON.stringify(body) } : {}) }));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }

  const start = (mode: MeetingMode) => act('/ring/rendezvous', { mode });
  const peer = meeting?.peer;
  const peerLine = peer && `«${peer.name}» (${KINDS[peer.kind] ?? peer.kind}${peer.software ? `, ${peer.software.direction} ${peer.software.version}` : ''})`;

  return <section className="ring-meeting" data-testid="ring-meeting">
    <h4>Добавить устройство по QR</h4>
    <p className="muted">Сканирует телефон, этому узлу камера не нужна. Работает из любой сети через relay; новое устройство получает всё кольцо и все доски.</p>
    {!open && <div className="toolbar">
      {hasRing && <Button disabled={busy} onClick={() => void start('invite')}>Показать QR: телефон входит в кольцо узла</Button>}
      <Button disabled={busy} onClick={() => void start('join')}>Показать QR: добавить узел в кольцо телефона</Button>
    </div>}
    {!open && members > 1 && <p className="muted">Этот узел уже в кольце из {members} устройств: второй режим годится только для переподключения к тому же кольцу.</p>}
    {meeting && open && <div className="panel">
      {meeting.qrText && <QrImage text={meeting.qrText} />}
      {meeting.qrText && <Button disabled={busy} onClick={() => void navigator.clipboard?.writeText(meeting.qrText ?? '').catch(() => undefined)}>
        Скопировать текст QR</Button>}
      <p className="muted">Действует ещё {left(meeting.expiresAt, now)} · relay встречи: {meeting.relays.join(', ')}</p>
      {meeting.mode === 'invite' && meeting.status === 'waiting' &&
        <p>На телефоне: «Кольцо устройств» → «Сканировать QR». Ждём телефон…</p>}
      {meeting.mode === 'join' && meeting.status === 'waiting' && <>
        <p>Отсканируйте код телефоном, который уже в кольце. Сверьте код на двух экранах и подтвердите на телефоне.</p>
        <p data-testid="ring-code" style={{ fontSize: '2rem', letterSpacing: '0.1em' }}>{meeting.code}</p>
      </>}
      {meeting.status === 'confirm' && peer && <>
        <p>{peer.alreadyMember ? 'Переподключение участника кольца' : 'Просит войти в кольцо'}: {peerLine}.</p>
        <p>Код на телефоне должен быть:</p>
        <p data-testid="ring-code" style={{ fontSize: '2rem', letterSpacing: '0.1em' }}>{meeting.code}</p>
        {!peer.alreadyMember && <label><input type="checkbox" checked={memberOnly} onChange={(e) => setMemberOnly(e.target.checked)} />
          {' '}Только участник (чужое или временное устройство: не сможет добавлять другие)</label>}
        <div className="toolbar">
          <Button disabled={busy} onClick={() => void act(`/ring/rendezvous/${meeting.sessionId}/confirm`, { role: memberOnly ? 'member' : 'admin' })}>
            {peer.alreadyMember ? 'Код совпадает — переподключить' : 'Код совпадает — принять в кольцо'}</Button>
        </div>
      </>}
      {meeting.status === 'welcomed' && <p>Журнал кольца и связка ключей отправлены {peerLine}. Ждём подтверждения телефона…</p>}
      <Button disabled={busy} onClick={() => void act(`/ring/rendezvous/${meeting.sessionId}/cancel`)}>
        {meeting.status === 'confirm' ? 'Отклонить' : 'Отменить'}</Button>
    </div>}
    {meeting?.status === 'done' && <p role="status" data-testid="ring-meeting-done">
      {meeting.mode === 'invite'
        ? `Готово: ${peerLine} в кольце.`
        : `Готово: узел вошёл в кольцо${peer ? ` устройства «${peer.name}»` : ''} из ${meeting.outcome?.members ?? '?'} устройств. Доски других устройств появятся после обмена с relay.`}
    </p>}
    {meeting && ['refused', 'expired', 'canceled'].includes(meeting.status) && <p role="alert" data-testid="ring-meeting-stopped">
      Встреча остановлена: {REFUSAL_TEXT[meeting.outcome?.reason ?? ''] ?? meeting.outcome?.reason ?? meeting.status}
      {meeting.outcome?.detail ? `. ${meeting.outcome.detail}` : ''}
    </p>}
    {error && <><p role="alert">{error}</p><ErrorDetails message={error} operation="Встреча по QR" /></>}
  </section>;
}
