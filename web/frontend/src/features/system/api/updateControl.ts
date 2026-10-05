const CONTROL_ORIGIN = 'http://127.0.0.1:8765';
const SOURCE_REPOSITORY = 'https://github.com/Pacifica123/p2p_planner';
const SOURCE_BRANCH = 'main';
const GITHUB_LATEST_COMMIT = 'https://api.github.com/repos/Pacifica123/p2p_planner/commits/main';
const EMBEDDED_SOURCE_REVISION = normalizeRevision(import.meta.env.VITE_SOURCE_REVISION);

export interface GitHubCommitInfo {
  sha: string;
  shortSha: string;
  message: string;
  committedAt: string | null;
  url: string;
}

export interface UpdateJobState {
  id: string;
  status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed';
  phase: string;
  progress: number;
  message: string;
  targetSha: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  error: string | null;
  verified: boolean;
}

export interface UpdateControlState {
  available: boolean;
  sessionToken: string | null;
  repository: string;
  branch: string;
  installedRevision: string | null;
  latest: GitHubCommitInfo | null;
  job: UpdateJobState;
}

const IDLE_JOB: UpdateJobState = {
  id: 'none',
  status: 'idle',
  phase: 'ожидание',
  progress: 0,
  message: 'Обновление не запущено.',
  targetSha: null,
  startedAt: null,
  finishedAt: null,
  error: null,
  verified: false,
};

function normalizeRevision(value: unknown) {
  const revision = typeof value === 'string' ? value.trim().toLowerCase() : '';
  return /^[0-9a-f]{7,40}$/.test(revision) ? revision : null;
}

export function revisionsMatch(left: string | null, right: string | null) {
  const normalizedLeft = normalizeRevision(left);
  const normalizedRight = normalizeRevision(right);
  if (!normalizedLeft || !normalizedRight) return false;
  return normalizedLeft === normalizedRight
    || normalizedLeft.startsWith(normalizedRight)
    || normalizedRight.startsWith(normalizedLeft);
}

export function isLocalUpdateSurface() {
  return ['127.0.0.1', 'localhost', '::1'].includes(window.location.hostname);
}

async function controlRequest<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
) {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (token) headers.set('X-P2PKanban-Control', token);
  const response = await fetch(`${CONTROL_ORIGIN}${path}`, { ...init, headers });
  const payload = await response.json().catch(() => null) as { error?: string } | null;
  if (!response.ok) throw new Error(payload?.error || `Control plane: HTTP ${response.status}`);
  return payload as T;
}

export function getUpdateControlState() {
  return controlRequest<UpdateControlState>('/v1/status')
    .catch(() => getReadOnlySourceUpdateState());
}

export function checkForSourceUpdate(token: string) {
  return controlRequest<UpdateControlState>('/v1/check', { method: 'POST' }, token);
}

export function startSourceUpdate(token: string, targetSha: string) {
  return controlRequest<UpdateControlState>(
    '/v1/update',
    {
      method: 'POST',
      body: JSON.stringify({ targetSha }),
      headers: { 'Content-Type': 'application/json' },
    },
    token,
  );
}

interface GitHubCommitPayload {
  sha?: unknown;
  html_url?: unknown;
  commit?: {
    message?: unknown;
    committer?: { date?: unknown } | null;
  } | null;
}

async function getReadOnlySourceUpdateState(): Promise<UpdateControlState> {
  const response = await fetch(GITHUB_LATEST_COMMIT, {
    cache: 'no-store',
    headers: { Accept: 'application/vnd.github+json' },
  });
  if (!response.ok) throw new Error(`GitHub: HTTP ${response.status}`);
  const payload = await response.json() as GitHubCommitPayload;
  const sha = normalizeRevision(payload.sha);
  if (!sha || sha.length !== 40) throw new Error('GitHub вернул некорректный commit SHA.');
  const message = typeof payload.commit?.message === 'string'
    ? payload.commit.message
    : 'Новый commit в main';
  const committedAt = typeof payload.commit?.committer?.date === 'string'
    ? payload.commit.committer.date
    : null;
  const url = typeof payload.html_url === 'string'
    ? payload.html_url
    : `${SOURCE_REPOSITORY}/commit/${sha}`;
  return {
    available: false,
    sessionToken: null,
    repository: SOURCE_REPOSITORY,
    branch: SOURCE_BRANCH,
    installedRevision: EMBEDDED_SOURCE_REVISION,
    latest: {
      sha,
      shortSha: sha.slice(0, 12),
      message,
      committedAt,
      url,
    },
    job: IDLE_JOB,
  };
}
