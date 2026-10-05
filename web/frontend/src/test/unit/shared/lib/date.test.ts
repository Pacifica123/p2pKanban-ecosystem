import { formatDateTime } from '@/shared/lib/date';

describe('formatDateTime', () => {
  it('returns an em dash for empty values', () => {
    expect(formatDateTime()).toBe('—');
    expect(formatDateTime(null)).toBe('—');
  });

  it('returns original string for invalid date values', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date');
  });

  it('formats valid ISO timestamps', () => {
    const formatted = formatDateTime('2026-04-14T10:15:00Z');

    expect(formatted).toContain('14');
    expect(formatted).toContain('2026');
  });
});
