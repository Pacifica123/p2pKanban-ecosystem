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

export function isPrivateNodeOrigin(origin: string | null) {
  if (!origin) return false;
  let hostname: string;
  try {
    hostname = new URL(origin).hostname.toLowerCase().replace(/^\[|\]$/g, '');
  } catch {
    return false;
  }
  if (hostname === 'localhost' || hostname.endsWith('.local')) return true;
  if (hostname === '::1' || hostname.startsWith('fc') || hostname.startsWith('fd')) return true;
  const octets = hostname.split('.').map(Number);
  if (octets.length !== 4 || octets.some((value) => !Number.isInteger(value))) return false;
  const [first = -1, second = -1] = octets;
  return first === 10
    || first === 127
    || (first === 172 && second >= 16 && second <= 31)
    || (first === 192 && second === 168)
    || (first === 169 && second === 254);
}

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
