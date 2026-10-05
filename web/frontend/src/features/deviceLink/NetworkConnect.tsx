import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import { apiRequest } from '@/shared/api/client';
import { Panel } from '@/shared/ui/Panel';
import { Button } from '@/shared/ui/Button';
import { TextField } from '@/shared/ui/Field';

type Signed = { id: string; pubkey: string; content: string };
export function NetworkConnect({ first = false }: { first?: boolean }) {
  const auth = useAuthSession();
  const cache = useQueryClient();
  const [address, setAddress] = useState('');
  const [request, setRequest] = useState<Signed | null>(null);
  const [response, setResponse] = useState<Signed | null>(null);
  const [password, setPassword] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [incoming, setIncoming] = useState<Signed[]>([]);
  useEffect(() => {
    if (first) return;
    let active = true;
    const load = () => void apiRequest<Signed[]>('/auth/device-link/lan/inbox')
      .then((items) => { if (active) setIncoming(items); }).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 4000);
    return () => { active = false; window.clearInterval(timer); };
  }, [first]);
  useEffect(() => {
    if (!request || response) return;
    let active = true;
    const load = () => void Promise.all([
      apiRequest<{ response: Signed | null }>(`/auth/device-link/lan/mobile-poll/${request.id}`, {}, { skipAuthRefresh: first }).catch(() => null),
      ...(address ? [apiRequest<{ response: Signed | null }>(`/auth/device-link/lan/poll/${request.id}`, {}, { skipAuthRefresh: first }).catch(() => null)] : []),
    ]).then((results) => {
      const found = results.find((result) => result?.response)?.response;
      if (active && found) { setResponse(found); setNotice('Зашифрованное разрешение получено.'); }
    });
    load();
    const timer = window.setInterval(load, 3500);
    return () => { active = false; window.clearInterval(timer); };
  }, [request, response, address, first]);
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return <Panel title={first ? 'Подключить пустой узел' : 'Сеть и доверенные устройства'}>
    {!first && incoming.map((item) => <div key={item.id} className="panel" style={{ overflowWrap: 'anywhere' }}>
      <p>Запрос нового устройства: {item.id}</p><p>Публичный ключ: {item.pubkey}</p>
      <Button disabled={busy} onClick={() => void run(async () => {
        await apiRequest('/auth/device-link/lan/approve', { method: 'POST',
          body: JSON.stringify({ requestId: item.id, confirmedRequestId: item.id }) });
        setIncoming((items) => items.filter((next) => next.id !== item.id));
        setNotice('Запрос подтверждён; зашифрованный ответ доступен новому узлу.');
      })}>Сверил отпечаток · разрешить</Button>
    </div>)}
    <p>Введите IP:порт доверенного web-узла в одной сети. Если отвечает Android, нажмите
      «Ожидать ответ Android», а на телефоне укажите IP:порт этого нового web-узла.</p>
    <TextField label="IP:порт другого web-узла" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="192.168.1.42:8080" />
    <div className="toolbar">
      <Button disabled={busy || !address} onClick={() => void run(async () => {
        const data = await apiRequest<{ request: Signed }>('/auth/device-link/lan/connect',
          { method: 'POST', body: JSON.stringify({ address, supplement: !first }) }, { skipAuthRefresh: first });
        setRequest(data.request); setResponse(null); setConfirmed(false); setNotice('Запрос доставлен; ожидаем подтверждения.');
      })}>Отправить запрос через LAN</Button>
      <Button disabled={busy} onClick={() => void run(async () => {
        const data = await apiRequest<Signed>(first ? '/auth/device-link/request' : '/auth/device-link/supplement-request',
          { method: 'POST' }, { skipAuthRefresh: first });
        setRequest(data); setResponse(null); setConfirmed(false);
        setNotice('Ожидаем Android. На телефоне укажите IP:порт этого web-узла.');
      })}>Ожидать ответ Android</Button>
    </div>
    {request && <p style={{ overflowWrap: 'anywhere' }}>Отпечаток запроса на новом узле: {request.id}</p>}
    {response && <>
      <p style={{ overflowWrap: 'anywhere' }}>Ключ доверенного устройства: <strong>{response.pubkey}</strong></p>
      <label><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /> Сверил ключ отправителя</label>
      {first && <TextField label="Пароль нового узла (не передаётся другим устройствам)" type="password" value={password}
        onChange={(e) => setPassword(e.target.value)} />}
      <Button disabled={busy || !confirmed || (first && password.length < 8)} onClick={() => void run(async () => {
        const result = await apiRequest<{ addedBoards?: number }>('/auth/device-link/accept', {
          method: 'POST', body: JSON.stringify({ response, supplement: !first, password, confirmedSender: response.pubkey }),
        }, { skipAuthRefresh: first });
        setResponse(null); setPassword('');
        if (first) await auth.refreshCurrentSession();
        else { await cache.invalidateQueries(); setNotice(`Добавлено досок: ${result.addedBoards ?? 0}`); }
      })}>{first ? 'Подключить и сохранить реплику' : 'Получить новые доски'}</Button>
    </>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </Panel>;
}
