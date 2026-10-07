import httpErrors from '../../../../contracts/error-report/1/vectors/http-error.json';
import redactions from '../../../../contracts/error-report/1/vectors/redact.json';
import reports from '../../../../contracts/error-report/1/vectors/reports.json';
import {
  buildReport, parseNodeHeader, parseReportText, redact, renderReport, truncate, type ErrorReport,
} from './report';

// The shared vectors of contracts/error-report/1 are the source of truth.
describe('contracts/error-report/1 vectors', () => {
  for (const c of redactions.cases) {
    it(`redact: ${c.name}`, () => {
      expect(redact(c.input)).toEqual([c.expected, c.redactions]);
      expect(redact(c.expected)[0]).toBe(c.expected);
    });
  }

  it('truncates by code points', () => {
    for (const c of redactions.truncate) expect(truncate(c.input, c.limit)).toBe(c.expected);
  });

  for (const c of reports.cases) {
    it(`report: ${c.name}`, () => {
      const expected = c.expectedReport as unknown as ErrorReport;
      const report = buildReport(c.input as unknown as ErrorReport);
      expect(report).toEqual(expected);
      expect(buildReport(report)).toEqual(report);
      expect(renderReport(expected)).toBe(c.expectedText);
      expect(parseReportText(c.expectedText)).toEqual(expected);
    });
  }

  it('reads the node header like the reference', () => {
    for (const c of httpErrors.cases) {
      const header = (c.headers as Record<string, string>)['x-p2p-kanban-node'];
      expect(header ? parseNodeHeader(header) : null).toEqual(c.expectedNode);
    }
  });
});
