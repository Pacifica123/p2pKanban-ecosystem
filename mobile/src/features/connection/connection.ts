export function normalizeNodeOrigin(input: string) {
  let candidate = input.trim();
  if (!candidate) throw new Error('Введите адрес узла.');
  if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(candidate)) {
    candidate = `http://${candidate}`;
  }

  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error('Адрес узла имеет неверный формат.');
  }

  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Поддерживаются только адреса http:// и https://.');
  }
  if (parsed.username || parsed.password) {
    throw new Error('Логин и пароль не должны находиться в адресе узла.');
  }

  const normalizedPath = parsed.pathname.replace(/\/+$/, '');
  const allowedPaths = ['', '/api', '/api/v1', '/health', '/healthz'];
  if (!allowedPaths.includes(normalizedPath)) {
    throw new Error('Укажите корневой адрес узла без дополнительного пути.');
  }

  return parsed.origin;
}

export { isPrivateNodeOrigin } from '../../shared/api/nodeReach';

interface ProbeResponse {
  ok: boolean;
  status: number;
  json?: () => Promise<unknown>;
}

type ProbeFetch = (url: string, init?: RequestInit) => Promise<ProbeResponse>;

export async function probeNode(origin: string, fetcher: ProbeFetch = fetch) {
  const candidates = ['/healthz', '/health', '/api/v1/health'];
  let lastStatus: number | null = null;

  for (const path of candidates) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5_000);
    try {
      const response = await fetcher(`${origin}${path}`, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      lastStatus = response.status;
      if (response.ok) {
        if (!response.json) return null;
        try {
          const body = await response.json() as {
            version?: unknown;
            data?: { version?: unknown };
          };
          const version = body.data?.version ?? body.version;
          return typeof version === 'string' ? version : null;
        } catch {
          return null;
        }
      }
    } catch {
      // The next known health endpoint may still be valid.
    } finally {
      clearTimeout(timeout);
    }
  }

  if (lastStatus !== null) {
    throw new Error(`Узел найден, но health-check вернул HTTP ${lastStatus}.`);
  }
  throw new Error('Узел не отвечает. Проверьте адрес, порт и доступ из локальной сети.');
}
