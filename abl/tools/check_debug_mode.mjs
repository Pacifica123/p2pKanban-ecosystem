// abl debug mode (docs/DEBUG_MODE.md): the journal grows only in the mode, detailed
// lines cost nothing outside it, and the Markdown export hides secrets the way
// contracts/error-report/1 does. Runs the TypeScript sources directly
// (Node >= 22.18 strips types), no npm packages needed.
import { registerHooks } from 'node:module';
import { strictEqual, ok } from 'node:assert/strict';

// The sources import siblings without the .ts extension, as Vite allows.
registerHooks({
  resolve(specifier, context, next) {
    try { return next(specifier, context); } catch (error) {
      if (specifier.startsWith('.') && !specifier.endsWith('.ts')) return next(`${specifier}.ts`, context);
      throw error;
    }
  },
});

let journal;
let exporter;
try {
  journal = await import(new URL('../src/shared/errorReport/journal.ts', import.meta.url));
  exporter = await import(new URL('../src/shared/debug/export.ts', import.meta.url));
} catch (error) {
  console.error(`FAIL: Node ${process.versions.node} не исполняет TypeScript напрямую (нужен Node >= 22.18): ${error.message}`);
  process.exit(1);
}
const { DEBUG_CAPACITY, NORMAL_CAPACITY, journalEntries, journalLines, logLine, resetJournalForTests, setJournalDebugMode, trace } = journal;

resetJournalForTests();
let built = 0;
trace('nav', () => { built += 1; return 'не должно попасть'; });
strictEqual(built, 0, 'trace без режима не собирает строку');
strictEqual(journalLines().length, 0);

setJournalDebugMode(true);
trace('nav', () => 'доска 01a10d38 открыта');
ok(/ debug nav: доска 01a10d38 открыта$/.test(journalLines()[0]), 'trace в режиме пишет строку контракта');
for (let index = 0; index < DEBUG_CAPACITY + 5; index += 1) logLine('debug', 'desktop', `GET /x ${index}`);
strictEqual(journalEntries().length, DEBUG_CAPACITY);
setJournalDebugMode(false);
strictEqual(journalEntries().length, NORMAL_CAPACITY);

const { text, hidden } = exporter.renderDebugJournal({
  software: { direction: 'abl', version: '0.1.0', build: '0.1.0-1', commit: 'c3bc6f61a3a0' },
  platform: 'KDE · wayland',
  exportedAt: '2026-10-17T03:20:00.000Z',
  lines: ['2026-10-17T03:19:59.000Z error desktop: POST /vault secret=abc123 → NATIVE_ERROR'],
  debugMode: false,
});
strictEqual(hidden, 1);
ok(!text.includes('abc123'), 'секрет вырезан');
ok(text.startsWith('# p2pKanban: журнал отладки\n\n- Программа: abl 0.1.0 · сборка 0.1.0-1 · коммит c3bc6f6\n'));

console.log('OK: abl режим отладки — ёмкость, ленивые строки, Markdown без секретов');
