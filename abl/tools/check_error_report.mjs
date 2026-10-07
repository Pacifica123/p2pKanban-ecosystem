// abl side of contracts/error-report/1: the report module the WebView uses must
// reproduce the shared vectors byte for byte. Runs src/shared/errorReport/report.ts
// directly (Node >= 22.18 strips TypeScript types), no npm packages needed.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { deepStrictEqual, strictEqual } from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
let root = resolve(here);
while (!existsSync(join(root, 'contracts', 'compatibility.json'))) {
  const parent = dirname(root);
  if (parent === root) throw new Error('contracts/compatibility.json not found above abl/');
  root = parent;
}
const vectors = join(root, 'contracts', 'error-report', '1', 'vectors');
const read = (name) => JSON.parse(readFileSync(join(vectors, name), 'utf8'));

let report;
try {
  report = await import(new URL('../src/shared/errorReport/report.ts', import.meta.url));
} catch (error) {
  console.error(`FAIL: Node ${process.versions.node} не исполняет TypeScript напрямую (нужен Node >= 22.18): ${error.message}`);
  process.exit(1);
}
const { buildReport, parseNodeHeader, parseReportText, redact, renderReport, truncate } = report;

let checked = 0;
const redactions = read('redact.json');
for (const c of redactions.cases) {
  deepStrictEqual(redact(c.input), [c.expected, c.redactions], `redact ${c.name}`);
  strictEqual(redact(c.expected)[0], c.expected, `redact ${c.name} is idempotent`);
  checked += 1;
}
for (const c of redactions.truncate) {
  strictEqual(truncate(c.input, c.limit), c.expected, `truncate ${c.input}`);
  checked += 1;
}
for (const c of read('reports.json').cases) {
  const built = buildReport(c.input);
  deepStrictEqual(built, c.expectedReport, `report ${c.name}`);
  deepStrictEqual(buildReport(built), built, `report ${c.name} is idempotent`);
  strictEqual(renderReport(c.expectedReport), c.expectedText, `text ${c.name}`);
  deepStrictEqual(parseReportText(c.expectedText), c.expectedReport, `parse ${c.name}`);
  checked += 1;
}
for (const c of read('http-error.json').cases) {
  const header = c.headers['x-p2p-kanban-node'];
  deepStrictEqual(header ? parseNodeHeader(header) : null, c.expectedNode, `node header ${c.name}`);
  checked += 1;
}
console.log(`OK: abl error-report/1 совпадает с векторами (${checked} проверок)`);
