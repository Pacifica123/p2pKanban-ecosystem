import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const read = path => readFileSync(new URL('../' + path, import.meta.url), 'utf8');
const relay = read('src/features/roaming/nostrRelay.ts');
assert(relay.includes('!relays.length') && relay.includes('new Set(relays)'));
assert(!relay.includes('Math.min(minimumAcks, relays.length)'));
assert(relay.includes("filter['#d']") && relay.includes("filter['#p']"));
for (const screen of ['boards/BoardsScreen.tsx', 'workspaces/WorkspacesScreen.tsx']) {
  const text = read('src/features/' + screen);
  assert(text.includes('30_000') && text.includes('clearInterval(timer)'));
  assert(!text.includes('query.isSuccess))return') && !text.includes('query.isSuccess && networkType'));
}
const storage = read('src/features/roaming/storage.ts');
assert(storage.includes('capability.capabilityEpoch < previous.capabilityEpoch'));
assert(storage.includes('capability.boardKey !== previous.boardKey'));
const local = read('src/features/localFirst/useLocalBoard.ts');
const start = local.indexOf('const installed = roamingCapabilityRef.current');
const end = local.indexOf('const relay = await pullRoamingBoard(installed', start);
assert(start >= 0 && end > start && !local.slice(start, end).includes('fetchBoardSnapshot'));
assert(read('src/features/roaming/catalog.ts').includes('trustedPublisher'));
console.log('network recovery offline source contract: PASS (runtime/Jest is a separate gate)');
