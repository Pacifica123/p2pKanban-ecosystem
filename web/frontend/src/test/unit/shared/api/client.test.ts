import {
  apiRequest,
  clearAccessToken,
  setAccessToken,
  setAuthLifecycleHandlers,
} from '@/shared/api/client';

describe('apiRequest', () => {
  beforeEach(() => {
    setAccessToken('test-reset');
    clearAccessToken();
    setAuthLifecycleHandlers({ refresh: null, expired: null });
  });

  it('unwraps the data envelope and sends authorization header', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const headers = new Headers(init?.headers);

      expect(headers.get('Authorization')).toBe('Bearer access-token');
      expect(headers.get('Content-Type')).toBe('application/json');

      return new Response(JSON.stringify({ data: { ok: true } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });

    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('access-token');

    await expect(
      apiRequest<{ ok: boolean }>('/test', {
        method: 'POST',
        body: JSON.stringify({ hello: 'world' }),
      }),
    ).resolves.toEqual({ ok: true });

  });

  it('coalesces parallel 401 responses into one refresh and retries both requests', async () => {
    const refresh = vi.fn(async () => 'fresh-token');
    setAuthLifecycleHandlers({ refresh, expired: vi.fn() });
    setAccessToken('expired-token');
    vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const token = new Headers(init?.headers).get('Authorization');
      return token === 'Bearer fresh-token'
        ? new Response(JSON.stringify({ data: { ok: true } }), { status: 200 })
        : new Response(JSON.stringify({ error: { code: 'UNAUTHORIZED' } }), { status: 401 });
    }));

    await expect(Promise.all([
      apiRequest<{ ok: boolean }>('/first'),
      apiRequest<{ ok: boolean }>('/second'),
    ])).resolves.toEqual([{ ok: true }, { ok: true }]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it('expires once and blocks further protected requests after refresh fails', async () => {
    const expired = vi.fn();
    setAuthLifecycleHandlers({ refresh: async () => null, expired });
    setAccessToken('expired-token');
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'UNAUTHORIZED' } }),
      { status: 401 },
    ));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiRequest('/first')).rejects.toMatchObject({ status: 401 });
    await expect(apiRequest('/second')).rejects.toMatchObject({
      status: 401,
      code: 'SESSION_EXPIRED',
    });
    expect(expired).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('expires when the one permitted retry still returns 401', async () => {
    const expired = vi.fn();
    setAuthLifecycleHandlers({ refresh: async () => 'rejected-token', expired });
    setAccessToken('expired-token');
    const fetchMock = vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'UNAUTHORIZED' } }),
      { status: 401 },
    ));
    vi.stubGlobal('fetch', fetchMock);

    await expect(apiRequest('/first')).rejects.toMatchObject({ status: 401 });
    await expect(apiRequest('/second')).rejects.toMatchObject({ code: 'SESSION_EXPIRED' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(expired).toHaveBeenCalledTimes(1);
  });

  it('throws a network ApiError when fetch fails before a response exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('socket hang up');
      }),
    );

    await expect(apiRequest('/test')).rejects.toMatchObject({
      name: 'ApiError',
      status: 0,
      code: 'NETWORK_ERROR',
    });

    await expect(apiRequest('/test')).rejects.toThrow('Не удалось связаться с backend');
  });
});
