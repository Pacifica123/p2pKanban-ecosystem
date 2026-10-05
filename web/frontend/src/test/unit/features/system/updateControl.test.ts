import {
  getUpdateControlState,
  revisionsMatch,
} from '@/features/system/api/updateControl';

describe('source update revision identity', () => {
  it('matches a full GitHub SHA with the short running image revision', () => {
    const full = '0123456789abcdef0123456789abcdef01234567';
    expect(revisionsMatch(full, full.slice(0, 12))).toBe(true);
    expect(revisionsMatch(full, 'fedcba987654')).toBe(false);
  });

  it('does not treat an unknown running revision as the latest commit', () => {
    expect(revisionsMatch('0123456789abcdef0123456789abcdef01234567', null)).toBe(false);
    expect(revisionsMatch('not-a-sha', 'not-a-sha')).toBe(false);
  });

  it('falls back to the public GitHub commit when the host installer is down', async () => {
    const sha = 'fedcba9876543210fedcba9876543210fedcba98';
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockRejectedValueOnce(new TypeError('control plane is down'))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        sha,
        html_url: `https://github.com/Pacifica123/p2p_planner/commit/${sha}`,
        commit: {
          message: 'fix: compile production images',
          committer: { date: '2026-08-21T10:00:00Z' },
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }));

    const state = await getUpdateControlState();

    expect(state.available).toBe(false);
    expect(state.sessionToken).toBeNull();
    expect(state.latest?.sha).toBe(sha);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      'https://api.github.com/repos/Pacifica123/p2p_planner/commits/main',
      expect.objectContaining({ cache: 'no-store' }),
    );
    fetchMock.mockRestore();
  });
});
