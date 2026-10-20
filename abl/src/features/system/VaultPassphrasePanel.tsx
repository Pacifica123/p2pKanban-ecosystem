import { useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError } from '../../shared/api/errors';
import type { VaultStatus } from '../../shared/api/types';
import { setUpVaultPassphrase, unlockVaultPassphrase } from './api/vault';

const MIN_BYTES = 12;
const MAX_BYTES = 1024;

const REASONS: Record<string, string> = {
  VAULT_PASSPHRASE_LENGTH: `Пароль должен быть от ${MIN_BYTES} до ${MAX_BYTES} байт.`,
  VAULT_PASSPHRASE_REJECTED: 'Пароль не подошёл.',
  VAULT_PASSPHRASE_NOT_APPLICABLE: 'Состояние хранилища изменилось. Перезапустите abl.',
  VAULT_CORRUPT: 'Файл хранилища повреждён. Запустите abl doctor.',
  VAULT_STORAGE_FAILURE: 'Не удалось записать файл хранилища в профиль.',
};

function reason(error: unknown): string {
  const code = error instanceof ApiError && typeof error.details === 'string' ? error.details : '';
  return REASONS[code] ?? (error instanceof Error ? error.message : 'Операция с хранилищем не удалась.');
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

/**
 * Explicit passphrase vault (ADR-004) for hosts without a usable Secret Service. Shown only
 * while the core reports the fallback as applicable; the passphrase is never stored here.
 */
export function VaultPassphrasePanel({ vault, onVault }: { vault: VaultStatus | null; onVault: (value: VaultStatus) => void }) {
  const [passphrase, setPassphrase] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (vault?.passphraseFallbackAvailable !== 'true') return null;
  const unlocking = vault.state === 'passphrase-required';
  const length = byteLength(passphrase);
  const lengthOk = length >= MIN_BYTES && length <= MAX_BYTES;
  const ready = !busy && lengthOk && (unlocking || passphrase === confirmation);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setFailure(null);
    try {
      const next = unlocking ? await unlockVaultPassphrase(passphrase) : await setUpVaultPassphrase(passphrase);
      setPassphrase('');
      setConfirmation('');
      onVault(next);
    } catch (error) {
      setFailure(reason(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="vault-passphrase-strip" aria-label="Хранилище секретов">
      <div>
        <p className="kicker">Хранилище секретов</p>
        <strong>{unlocking ? 'Хранилище закрыто паролем' : 'Secret Service недоступен'}</strong>
        <span>
          {unlocking
            ? 'Введите пароль хранилища. До этого ключи досок и устройства живут только до закрытия окна, а привязка недоступна.'
            : 'Связка ключей сеанса (GNOME Keyring, KWallet) не найдена. Задайте пароль хранилища, чтобы ключи пережили перезапуск и abl можно было привязать.'}
        </span>
        {unlocking ? null : <small>Пароль не восстанавливается: без него секреты этого профиля придётся получить заново. Его будут спрашивать при каждом запуске.</small>}
      </div>
      <form className="vault-passphrase-form" onSubmit={(event) => void submit(event)}>
        <label>Пароль хранилища
          <input type="password" autoComplete={unlocking ? 'current-password' : 'new-password'} value={passphrase} disabled={busy} onChange={(event) => setPassphrase(event.target.value)} />
        </label>
        {unlocking ? null : (
          <label>Повтор
            <input type="password" autoComplete="new-password" value={confirmation} disabled={busy} onChange={(event) => setConfirmation(event.target.value)} />
          </label>
        )}
        <small>
          {passphrase && !lengthOk ? `Нужно от ${MIN_BYTES} до ${MAX_BYTES} байт, сейчас ${length}.` : ''}
          {!unlocking && lengthOk && confirmation && passphrase !== confirmation ? 'Пароли не совпадают.' : ''}
        </small>
        <button type="submit" disabled={!ready}>{busy ? 'Проверяю…' : unlocking ? 'Открыть хранилище' : 'Задать пароль'}</button>
        {failure ? <span role="alert">{failure}</span> : null}
      </form>
    </section>
  );
}
