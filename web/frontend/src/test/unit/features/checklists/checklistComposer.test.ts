import {
  checklistSubmitHint,
  shouldSubmitChecklistItem,
} from '@/features/checklists/lib/checklistComposer';

const key = (patch: Partial<Parameters<typeof shouldSubmitChecklistItem>[1]> = {}) => ({
  key: 'Enter',
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...patch,
});

describe('checklist item composer mode', () => {
  it('submits plain Enter only in enter mode', () => {
    expect(shouldSubmitChecklistItem('enter', key())).toBe(true);
    expect(shouldSubmitChecklistItem('ctrl_enter', key())).toBe(false);
    expect(shouldSubmitChecklistItem('button', key())).toBe(false);
  });

  it('submits Ctrl+Enter or Command+Enter in ctrl_enter mode', () => {
    expect(shouldSubmitChecklistItem('ctrl_enter', key({ ctrlKey: true }))).toBe(true);
    expect(shouldSubmitChecklistItem('ctrl_enter', key({ metaKey: true }))).toBe(true);
    expect(shouldSubmitChecklistItem('enter', key({ ctrlKey: true }))).toBe(false);
  });

  it('ignores composition, shifted Enter and non-Enter keys', () => {
    expect(shouldSubmitChecklistItem('enter', key({ isComposing: true }))).toBe(false);
    expect(shouldSubmitChecklistItem('enter', key({ shiftKey: true }))).toBe(false);
    expect(shouldSubmitChecklistItem('enter', key({ key: 'Tab' }))).toBe(false);
  });

  it('describes the active shortcut without hiding the plus button', () => {
    expect(checklistSubmitHint('ctrl_enter')).toContain('Ctrl+Enter');
    expect(checklistSubmitHint('enter')).toContain('Enter');
    expect(checklistSubmitHint('button')).toContain('«+»');
  });
});
