#!/usr/bin/env node
// «Проверка приёмки» на месте: экран, маршрут, пункт в настройках, шаги и их тест.
// docs/architecture/acceptance-check-20261017.md
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(join(root, path), 'utf8');
const errors = [];
const need = (path, texts) => {
  const text = read(path);
  for (const value of texts) if (!text.includes(value)) errors.push(`${path}: нет «${value}»`);
};

need('src/app/navigation/types.ts', ['Acceptance: undefined;']);
need('src/app/navigation/RootNavigator.tsx', ['<Stack.Screen name="Acceptance" component={AcceptanceScreen} />']);
need('src/features/settings/SettingsScreen.tsx', ["navigation.navigate('Acceptance')"]);
need('src/features/acceptance/report.ts', ['p2p-kanban-acceptance-report/1']);
need('src/features/acceptance/AcceptanceScreen.tsx', ['useLocalBoard(']);
const steps = read('src/features/acceptance/mobileSteps.ts');
const ids = [...steps.matchAll(/\bid: '([a-z.-]+)'/g)].map((match) => match[1]);
if (new Set(ids).size !== ids.length) errors.push('mobileSteps.ts: повторяются id шагов');
for (const id of ['auth.other-node', 'crud.local', 'net.catalog-new-board', 'offline.card', 'back.node', 'cleanup']) {
  if (!ids.includes(id)) errors.push(`mobileSteps.ts: нет шага ${id}`);
}
if (ids.at(-1) !== 'cleanup') errors.push('mobileSteps.ts: уборка должна идти последней');
for (const forbidden of ['signOutAll', 'nativeRefresh', 'disconnect(']) {
  if (steps.includes(forbidden)) errors.push(`mobileSteps.ts: кнопке запрещено ${forbidden}`);
}
if (!existsSync(join(root, 'src/features/acceptance/acceptance.test.ts'))) errors.push('нет src/features/acceptance/acceptance.test.ts');

if (errors.length) {
  for (const error of errors) console.error(`FAIL: ${error}`);
  process.exit(1);
}
console.log(`OK: «Проверка приёмки»: шагов ${ids.length} (с просьбами о сети), экран и маршрут на месте`);
