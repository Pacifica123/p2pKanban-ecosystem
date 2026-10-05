import {
  formatFloatingLocalDateTime,
  parseFloatingLocalDateTime,
  reminderFromFields,
  reminderFields,
} from './model';

describe('local card reminder date', () => {
  it('round-trips local wall-clock components without UTC conversion', () => {
    const local = new Date(2026, 7, 16, 9, 35, 0, 0);
    const value = formatFloatingLocalDateTime(local);
    expect(value).toBe('2026-08-16T09:35');
    expect(parseFloatingLocalDateTime(value)?.getHours()).toBe(9);
  });

  it('rejects impossible local dates and pasting errors', () => {
    expect(parseFloatingLocalDateTime('2026-02-30T09:00')).toBeNull();
    expect(parseFloatingLocalDateTime('2026-08-16T24:00')).toBeNull();
    expect(reminderFromFields('16/08/2026', '09:00')).toBeNull();
  });

  it('converts the minimalist date and time fields', () => {
    const value = reminderFromFields('16.08.2026', '09:35');
    expect(value).toBe('2026-08-16T09:35');
    expect(reminderFields(value)).toEqual({ date: '16.08.2026', time: '09:35' });
  });
});
