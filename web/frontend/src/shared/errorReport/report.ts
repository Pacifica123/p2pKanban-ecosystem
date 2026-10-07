// p2p-kanban-error-report/1 (contracts/error-report/1/SPEC.md).
// Port of redact / truncate / build_report / render_report / parse_node_header
// from tools/ecosystem/contract_ref.py; the vectors in contracts/ are the
// source of truth (src/test/unit/shared/errorReport.test.ts).

export const ERROR_REPORT = 'p2p-kanban-error-report/1';
export const NODE_HEADER = 'x-p2p-kanban-node';
export const ERROR_ID_HEADER = 'x-p2p-error-id';
export const HIDDEN = '[скрыто]';
export const MAX_LOG_LINES = 50;
export const REPORT_LIMITS: Record<string, number> = {
  message: 1000, screen: 200, operation: 200, stage: 200, platform: 200,
  'error.name': 200, 'error.detail': 2000, 'http.path': 500, 'http.body': 4000, log: 500,
};
const REDACTED_FIELDS = new Set(['message', 'stage', 'error.detail', 'http.path', 'http.body']);

export type ErrorKind = 'http' | 'network' | 'timeout' | 'native' | 'storage' | 'validation' | 'internal' | 'unknown';
export type Software = { direction: 'web' | 'mobile' | 'abl'; version: string; build: string | null; commit: string | null };
export type NodeIdentity = { version: string | null; build: string | null; commit: string | null };
export type ErrorReport = {
  protocol: string;
  reportId: string;
  at: string;
  software: Software;
  platform?: string | null;
  screen?: string | null;
  operation?: string | null;
  stage?: string | null;
  message: string;
  error: { kind: ErrorKind; name?: string | null; detail?: string | null };
  http: null | { method: string; path: string; status: number; requestId: string | null; errorId: string | null; body: string | null };
  peer: null | ({ direction: 'web' } & NodeIdentity);
  logs: string[];
  redacted: number;
};

const BEARER = /bearer\s+[A-Za-z0-9._~+/=-]+/gi;
const JWT = /eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*/g;
const NSEC = /nsec1[02-9ac-hj-np-z]{20,}/g;
const URL_CREDENTIALS = /:\/\/[^/\s:@]+:[^/\s@]+@/g;
const KEY_VALUE = new RegExp(
  '(^|[^A-Za-z0-9])'
  + '([A-Za-z0-9_-]*(?:password|passwd|secret|token|apikey|api_key|api-key|privatekey|private_key|'
  + 'passphrase|mnemonic|boardkey|board_key|masterkey|master_key|cookie)[A-Za-z0-9_-]*)'
  + '(\\\\?"?[ \\t]*[:=][ \\t]*)'
  + '(\\\\"(?:[^\\\\]|\\\\[^"])*?\\\\"|"(?:[^"\\\\]|\\\\[\\s\\S])*"|[^\\s,;&}"\\\\]+)',
  'gi',
);

/** Cut secrets out of one string; returns the text and how many values were hidden. */
export function redact(input: string): [string, number] {
  let count = 0;
  const plain = (replacement: string) => () => { count += 1; return replacement; };
  let text = input
    .replace(BEARER, plain(`Bearer ${HIDDEN}`))
    .replace(JWT, plain('[скрыто:jwt]'))
    .replace(NSEC, plain('[скрыто:nsec]'))
    .replace(URL_CREDENTIALS, plain(`://${HIDDEN}@`));
  text = text.replace(KEY_VALUE, (whole: string, lead: string, key: string, sep: string, value: string) => {
    const hidden = value.startsWith('\\"') ? `\\"${HIDDEN}\\"` : value.startsWith('"') ? `"${HIDDEN}"` : HIDDEN;
    if (value === hidden || value.startsWith('Bearer') || value.startsWith('[скрыто')) return whole;
    count += 1;
    return lead + key + sep + hidden;
  });
  return [text, count];
}

/** Truncate by Unicode code points (not UTF-8 bytes, not UTF-16 units). */
export function truncate(text: string, limit: number): string {
  const points = Array.from(text);
  return points.length <= limit ? text : `${points.slice(0, limit - 1).join('')}…`;
}

const newlines = (text: string) => text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

/** Normalize a raw report: newlines, redaction, limits. Idempotent. */
export function buildReport(raw: Omit<ErrorReport, 'protocol' | 'redacted' | 'logs'> & { logs?: string[]; redacted?: number }): ErrorReport {
  const report = JSON.parse(JSON.stringify(raw)) as Record<string, unknown>;
  report.protocol = ERROR_REPORT;
  let count = Number.isInteger(report.redacted) ? (report.redacted as number) : 0;
  for (const path of ['message', 'screen', 'operation', 'stage', 'platform', 'error.name', 'error.detail', 'http.path', 'http.body']) {
    const parts = path.split('.');
    let node: Record<string, unknown> | null = report;
    for (const part of parts.slice(0, -1)) {
      const next: unknown = node?.[part];
      node = next && typeof next === 'object' && !Array.isArray(next) ? (next as Record<string, unknown>) : null;
    }
    const key = parts[parts.length - 1] ?? '';
    if (!node || typeof node[key] !== 'string') continue;
    let value = newlines(node[key] as string);
    if (REDACTED_FIELDS.has(path)) {
      const [text, n] = redact(value);
      value = text;
      count += n;
    }
    node[key] = truncate(value, REPORT_LIMITS[path] ?? value.length);
  }
  const logs = Array.isArray(report.logs) ? (report.logs as string[]) : [];
  report.logs = logs.slice(-MAX_LOG_LINES).map((line) => {
    const [text, n] = redact(newlines(line).replace(/\n/g, ' '));
    count += n;
    return truncate(text, REPORT_LIMITS.log ?? 500);
  });
  report.redacted = count;
  return report as unknown as ErrorReport;
}

/** Canonical JSON: sorted keys, no spaces, non-ASCII as is. */
export function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    const entries = Object.keys(value as object).sort()
      .map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value);
}

const continued = (text: string) => text.replace(/\n/g, '\n  ');

/** Text behind «Скопировать подробности»: for a person first, the JSON for a machine last. */
export function renderReport(report: ErrorReport): string {
  const sw = report.software;
  const lines = [
    'p2pKanban: подробности ошибки',
    `Отчёт: ${report.reportId} · ${report.at}`,
    `Программа: ${sw.direction} ${sw.version} · сборка ${sw.build || 'неизвестна'} · коммит ${sw.commit || 'неизвестен'}`,
  ];
  if (report.platform) lines.push(`Платформа: ${report.platform}`);
  const where = [report.screen, report.operation, report.stage].filter(Boolean);
  if (where.length) lines.push(`Где: ${where.join(' → ')}`);
  lines.push(`Сообщение: ${continued(report.message)}`);
  const error = report.error;
  lines.push(`Ошибка: ${[error.kind, error.name, error.detail].filter(Boolean).map((x) => continued(x as string)).join(' · ')}`);
  const http = report.http;
  if (http) {
    let line = `HTTP: ${http.method} ${http.path} → ${http.status ? String(http.status) : 'нет ответа'}`;
    if (http.requestId) line += ` · запрос ${http.requestId}`;
    if (http.errorId) line += ` · ошибка узла ${http.errorId}`;
    lines.push(line);
  }
  const peer = report.peer;
  if (peer) {
    lines.push(`Узел: ${peer.direction} ${peer.version || '?'} · сборка ${peer.build || 'неизвестна'} · коммит ${peer.commit || 'неизвестен'}`);
  }
  if (http?.body) {
    lines.push('Ответ узла:');
    lines.push(...http.body.split('\n').map((row) => `  ${row}`));
  }
  if (report.redacted) lines.push(`Скрыто значений: ${report.redacted}`);
  if (report.logs.length) {
    lines.push(`Журнал (${report.logs.length} последних строк):`);
    lines.push(...report.logs.map((row) => `  ${row}`));
  }
  lines.push(`--- ${ERROR_REPORT} ---`);
  lines.push(canonical(report));
  return `${lines.join('\n')}\n`;
}

/** Read a copied report back: the JSON after the marker is the source of truth. */
export function parseReportText(text: string): ErrorReport {
  const marker = `--- ${ERROR_REPORT} ---\n`;
  const at = text.indexOf(marker);
  if (at < 0) throw new Error(`в тексте нет отчёта ${ERROR_REPORT}`);
  return JSON.parse(text.slice(at + marker.length)) as ErrorReport;
}

/** `2.1.0; build=8087da08253b; commit=<40 hex>` → identity; `unknown` → null. */
export function parseNodeHeader(value: string): NodeIdentity {
  const parts = value.split(';').map((part) => part.trim());
  const out: NodeIdentity = { version: parts[0] || null, build: null, commit: null };
  for (const part of parts.slice(1)) {
    const at = part.indexOf('=');
    const key = at < 0 ? part : part.slice(0, at);
    const val = at < 0 ? '' : part.slice(at + 1);
    if (key === 'build' || key === 'commit') out[key] = val === '' || val === 'unknown' ? null : val;
  }
  return out;
}

export function newReportId(): string {
  const bytes = new Uint8Array(8);
  globalThis.crypto.getRandomValues(bytes);
  return `er-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
}
