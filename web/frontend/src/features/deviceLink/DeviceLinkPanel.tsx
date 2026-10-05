import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { apiRequest } from '@/shared/api/client';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import { Button } from '@/shared/ui/Button';
import { TextAreaField, TextField } from '@/shared/ui/Field';
import { Panel } from '@/shared/ui/Panel';
type SignedEvent = { id: string; pubkey: string; content: string };
function download(value: unknown, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }),
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function DeviceLinkPanel({
  destination = false,
  supplement = false,
}: {
  destination?: boolean;
  supplement?: boolean;
}) {
  const auth = useAuthSession();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false),
    [request, setRequest] = useState<SignedEvent | null>(null),
    [raw, setRaw] = useState(''),
    [password, setPassword] = useState(''),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState('');
  let parsed: SignedEvent | null = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    /*draft*/
  }
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setMessage('');
    try {
      await action();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel
      title={
        destination
          ? (supplement ? 'Получить новые доски от доверенного устройства' : 'Подключить через доверенное устройство')
          : 'Разрешить новое устройство'
      }
    >
      <Button onClick={() => setExpanded(!expanded)}>
        {expanded ? 'Свернуть' : 'Открыть подключение v2'}
      </Button>
      {expanded && (
        <div className="stack">
          <p>
            {destination
              ? supplement ? 'Добавляет отсутствующие доски в уже доверенные пространства. Существующие доски не перезаписываются. Получите свежий зашифрованный ответ на запрос ниже.' : 'Нужен пустой узел. Подготовленный Android или другой узел владельца может разрешить подключение без доступного PC-node.'
              : 'Вы передаёте свои пространства владельца и право дальнейшего подключения от вашего имени. Новый узел работает самостоятельно через relay.'}
          </p>
          {destination && (
            <>
              <Button
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    setRequest(
                      await apiRequest<SignedEvent>(
                        supplement ? '/auth/device-link/supplement-request' : '/auth/device-link/request',
                        { method: 'POST' },
                        { skipAuthRefresh: !supplement },
                      ),
                    );
                    setConfirmed(false);
                  })
                }
              >
                Создать запрос · 10 минут
              </Button>
              {request && (
                <>
                  <TextAreaField
                    label="Запрос — скопируйте на доверенное устройство"
                    readOnly
                    value={JSON.stringify(request)}
                  />
                  <p style={{ overflowWrap: 'anywhere' }}>
                    Отпечаток запроса: <strong>{request.id}</strong>
                  </p>
                  <Button
                    onClick={() =>
                      download(request, 'p2pkanban-pairing-request.json')
                    }
                  >
                    Скачать запрос
                  </Button>
                </>
              )}
            </>
          )}
          <TextAreaField
            label={
              destination
                ? 'Зашифрованное разрешение (JSON)'
                : 'Запрос нового устройства (JSON)'
            }
            rows={4}
            value={raw}
            onChange={(e) => {
              setRaw(e.target.value);
              setConfirmed(false);
            }}
          />
          <label className="field">
            Открыть JSON-файл
            <input
              type="file"
              accept=".json,application/json"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f)
                  void run(async () => {
                    if (f.size > 16 * 1024 * 1024)
                      throw new Error('Файл превышает 16 MiB.');
                    setRaw(await f.text());
                    setConfirmed(false);
                  });
              }}
            />
          </label>
          {parsed && (
            <p style={{ overflowWrap: 'anywhere' }}>
              {destination
                ? 'Ключ отправителя — сверьте на доверенном устройстве:'
                : 'Отпечаток запроса — сверьте на новом устройстве:'}
              <br />
              <strong>{destination ? parsed.pubkey : parsed.id}</strong>
            </p>
          )}
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />{' '}
            Отпечаток совпадает; разрешаю подключение
          </label>
          {destination && !supplement && (
            <TextField
              label="Новый пароль только для этого узла"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
          <Button
            disabled={
              busy ||
              !confirmed ||
              !parsed ||
              (destination && !supplement && password.length < 8)
            }
            onClick={() =>
              void run(async () => {
                if (!parsed) return;
                if (destination) {
                  const result = await apiRequest<{ addedBoards?: number }>(
                    '/auth/device-link/accept',
                    {
                      method: 'POST',
                      body: JSON.stringify({
                        response: parsed,
                        password,
                        supplement,
                        confirmedSender: parsed.pubkey,
                      }),
                    },
                    { skipAuthRefresh: !supplement },
                  );
                  setPassword('');
                  if (supplement) {
                    await queryClient.invalidateQueries();
                    setMessage(`Добавлено досок: ${result.addedBoards ?? 0}.`);
                  } else await auth.refreshCurrentSession();
                } else {
                  const response = await apiRequest<SignedEvent>(
                    '/auth/device-link/approve',
                    {
                      method: 'POST',
                      body: JSON.stringify({
                        request: parsed,
                        confirmedRequestId: parsed.id,
                      }),
                    },
                  );
                  download(response, 'p2pkanban-pairing-approval.json');
                  setMessage(
                    `Передайте файл новому узлу. Ключ отправителя для проверки: ${response.pubkey}`,
                  );
                }
              })
            }
          >
            {destination
              ? (supplement ? 'Принять новые доски' : 'Принять и подключиться')
              : 'Разрешить и скачать зашифрованный ответ'}
          </Button>
          {message && (
            <p role="status" style={{ overflowWrap: 'anywhere' }}>
              {message}
            </p>
          )}
          <p className="muted">
            Пароль исходного аккаунта не передаётся. Relay переносит карточки,
            чек-листы и оформление. Структура пространств, комментарии и
            управление доступом пока не имеют полной автономной синхронизации.
          </p>
        </div>
      )}
    </Panel>
  );
}
