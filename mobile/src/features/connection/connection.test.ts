import { isPrivateNodeOrigin, normalizeNodeOrigin, probeNode } from './connection';

describe('normalizeNodeOrigin', () => {
  it('adds http and removes API paths', () => {
    expect(normalizeNodeOrigin('192.168.1.20:49152')).toBe('http://192.168.1.20:49152');
    expect(normalizeNodeOrigin('https://board.example/api/v1/')).toBe('https://board.example');
  });

  it('rejects credentials and unrelated paths', () => {
    expect(() => normalizeNodeOrigin('http://user:pass@host:8080')).toThrow('Логин и пароль');
    expect(() => normalizeNodeOrigin('http://host:8080/manager')).toThrow('корневой адрес');
  });
});

describe('isPrivateNodeOrigin', () => {
  it('distinguishes LAN-only and public endpoints', () => {
    expect(isPrivateNodeOrigin('http://192.168.1.42:18080')).toBe(true);
    expect(isPrivateNodeOrigin('http://10.0.2.2:18080')).toBe(true);
    expect(isPrivateNodeOrigin('https://node.example')).toBe(false);
  });
});

describe('probeNode', () => {
  it('falls back across known health endpoints', async () => {
    const calls: string[] = [];
    await probeNode('http://node:8080', async (url) => {
      calls.push(url);
      return { ok: url.endsWith('/api/v1/health'), status: url.endsWith('/api/v1/health') ? 200 : 404 };
    });
    expect(calls).toEqual([
      'http://node:8080/healthz',
      'http://node:8080/health',
      'http://node:8080/api/v1/health',
    ]);
  });

  it('reads the backend version from the health envelope', async () => {
    const version = await probeNode('http://node:8080', async () => ({
      ok: true,
      status: 200,
      json: async () => ({ data: { version: '1.0.0-beta.9' } }),
    }));

    expect(version).toBe('1.0.0-beta.9');
  });
});
