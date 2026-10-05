import type { ChecklistItemSubmitMode } from '@/shared/types/api';

export interface ChecklistComposerKey {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
  isComposing?: boolean;
}

export function shouldSubmitChecklistItem(
  mode: ChecklistItemSubmitMode,
  event: ChecklistComposerKey,
) {
  if (event.key !== 'Enter' || event.isComposing) return false;

  if (mode === 'enter') {
    return !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;
  }

  if (mode === 'ctrl_enter') {
    return (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey;
  }

  return false;
}

export function checklistSubmitHint(mode: ChecklistItemSubmitMode) {
  if (mode === 'enter') return 'Enter — добавить пункт';
  if (mode === 'ctrl_enter') return 'Ctrl+Enter — добавить пункт';
  return 'Добавление только кнопкой «+»';
}
