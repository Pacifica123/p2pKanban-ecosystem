import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  buildReport, parseNodeHeader, parseReportText, redact, renderReport, truncate, type ErrorReport,
} from '@/shared/errorReport/report';

// The shared vectors of contracts/error-report/1 are the source of truth.
function contractsDir(): string {
  let dir = resolve(__dirname);
  while (!existsSync(join(dir, 'contracts', 'compatibility.json'))) {
    const parent = dirname(dir);
    if (parent === dir) throw new Error('contracts/compatibility.json not found above the frontend');
    dir = parent;
  }
  return join(dir, 'contracts', 'error-report', '1', 'vectors');
}
const vector = (name: string) => JSON.parse(readFileSync(join(contractsDir(), name), 'utf8'));

describe('contracts/error-report/1 vectors', () => {
  const redactions = vector('redact.json');
  it.each(redactions.cases.map((c: { name: string }) => [c.name, c]))('redact: %s', (_name, c) => {
    const { input, expected, redactions: count } = c as { input: string; expected: string; redactions: number };
    expect(redact(input)).toEqual([expected, count]);
    expect(redact(expected)[0]).toBe(expected);
  });

  it('truncates by code points', () => {
    for (const c of redactions.truncate) expect(truncate(c.input, c.limit)).toBe(c.expected);
  });

  const reports = vector('reports.json');
  it.each(reports.cases.map((c: { name: string }) => [c.name, c]))('report: %s', (_name, c) => {
    const { input, expectedReport, expectedText } = c as { input: ErrorReport; expectedReport: ErrorReport; expectedText: string };
    const report = buildReport(input);
    expect(report).toEqual(expectedReport);
    expect(buildReport(report)).toEqual(report);
    expect(renderReport(expectedReport)).toBe(expectedText);
    expect(parseReportText(expectedText)).toEqual(expectedReport);
  });

  it('reads the node header like the reference', () => {
    for (const c of vector('http-error.json').cases) {
      const header = c.headers['x-p2p-kanban-node'];
      expect(header ? parseNodeHeader(header) : null).toEqual(c.expectedNode);
    }
  });
});
