import { apiRequest } from '../../../shared/api/client';
import type { VaultStatus } from '../../../shared/api/types';

const jsonHeaders = { 'Content-Type': 'application/json' };

/** Write-only: the passphrase goes to the Rust core, only the vault status comes back. */
export function setUpVaultPassphrase(passphrase: string): Promise<VaultStatus> {
  return apiRequest<VaultStatus>('/system/vault/passphrase/set-up', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ passphrase }),
  });
}

export function unlockVaultPassphrase(passphrase: string): Promise<VaultStatus> {
  return apiRequest<VaultStatus>('/system/vault/passphrase/unlock', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ passphrase }),
  });
}
