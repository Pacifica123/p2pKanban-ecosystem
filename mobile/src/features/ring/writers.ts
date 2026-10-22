/**
 * Ring members are writers of every board of the account (keyring/1). The
 * roaming pull asks here, so it does not depend on the ring code.
 */
import { readSessionJson, writeSessionJson } from '../../shared/storage/storage';

const KEY = 'ring/writers';
let memo: Set<string> | null = null;

export async function ringWriters(): Promise<ReadonlySet<string>> {
  memo ??= new Set((await readSessionJson<string[]>(KEY, [])).map(key => key.toLowerCase()));
  return memo;
}

export async function saveRingWriters(keys: string[]) {
  memo = new Set(keys.map(key => key.toLowerCase()));
  await writeSessionJson(KEY, [...memo]);
}

export function resetRingWritersForTests() { memo = null; }
