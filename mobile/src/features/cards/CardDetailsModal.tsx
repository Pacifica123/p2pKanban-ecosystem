import {MarkdownEditor} from '../../shared/markdown/MarkdownEditor';
import {shareCardMarkdown,openCardInObsidian} from '../integrations/obsidian';
import { useCallback, useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { radius, spacing, useAppColors } from '../../app/theme';
import type { LocalBoardRuntime } from '../localFirst/useLocalBoard';
import type {
  BoardColumn,
  BoardLabel,
  Card,
  CardPriority,
  Comment,
} from '../../shared/types/api';
import {
  createBoardLabel,
  createComment,
  deleteBoardLabel,
  deleteComment,
  getBoardLabels,
  getCardComments,
  replaceCardLabels,
  updateBoardLabel,
  updateComment,
} from '../../shared/api/endpoints';
import {
  Button,
  Field,
  FormModal,
  InlineNotice,
  SectionTitle,
} from '../../shared/ui/primitives';
import {
  quickReminder,
  reminderFields,
  reminderFromFields,
} from '../reminders/model';
import { loadCardReminder } from '../reminders/storage';
import {
  cancelCardReminder,
  scheduleCardReminder,
  updateCardReminderTitle,
} from '../reminders/service';

const priorityLevels: Array<Exclude<CardPriority, null>> = [
  'low', 'medium', 'high', 'urgent',
];

const priorityLabels: Record<Exclude<CardPriority, null>, string> = {
  low: 'Низкий',
  medium: 'Средний',
  high: 'Высокий',
  urgent: 'Срочно',
};

function PriorityStars({
  value,
  onChange,
  disabled = false,
}: {
  value: CardPriority;
  onChange: (value: CardPriority) => void;
  disabled?: boolean;
}) {
  const colors = useAppColors();
  const selectedIndex = value ? priorityLevels.indexOf(value) : -1;
  const activeColor = value === 'urgent'
    ? colors.danger
    : value === 'high'
      ? colors.warning
      : value === 'medium'
        ? colors.accent
        : colors.muted;
  return (
    <View style={styles.priorityLine} accessibilityRole="radiogroup">
      <Text style={[styles.priorityLabel, { color: colors.text }]}>Приоритет</Text>
      <View style={styles.stars}>
        {priorityLevels.map((level, index) => (
          <Pressable
            key={level}
            accessibilityRole="radio"
            accessibilityState={{ checked: value === level }}
            accessibilityLabel={`${priorityLabels[level]}, ${index + 1} из 4`}
            disabled={disabled}
            onPress={() => onChange(value === level ? null : level)}
            hitSlop={4}
            style={({ pressed }) => [styles.starHit, { opacity: pressed ? 0.5 : 1 }]}
          >
            <Text style={[
              styles.star,
              { color: index <= selectedIndex ? activeColor : colors.muted },
            ]}>
              {index <= selectedIndex ? '★' : '☆'}
            </Text>
          </Pressable>
        ))}
      </View>
      <Text style={[styles.priorityValue, { color: colors.muted }]} numberOfLines={1}>
        {value ? priorityLabels[value] : 'Без приоритета'}
      </Text>
    </View>
  );
}

function SmallAction({
  label,
  danger = false,
  onPress,
}: {
  label: string;
  danger?: boolean;
  onPress: () => void;
}) {
  const colors = useAppColors();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.smallAction,
        {
          opacity: pressed ? 0.65 : 1,
        },
      ]}
    >
      <Text style={[styles.smallActionText, { color: danger ? colors.danger : colors.muted }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function CardDetailsModal({
  card,
  columns,
  runtime,
  readOnly = false,
  onClose,
}: {
  card: Card | null;
  columns: BoardColumn[];
  runtime: LocalBoardRuntime;
  readOnly?: boolean;
  onClose: () => void;
}) {
  const colors = useAppColors();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<CardPriority>(null);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newChecklistTitle, setNewChecklistTitle] = useState('');
  const [newItemByChecklist, setNewItemByChecklist] = useState<Record<string, string>>({});
  const [editingChecklist, setEditingChecklist] = useState<{ id: string; title: string } | null>(null);
  const [editingItem, setEditingItem] = useState<{
    checklistId: string;
    id: string;
    title: string;
  } | null>(null);
  const [labels, setLabels] = useState<BoardLabel[]>([]);
  const [comments, setComments] = useState<Comment[]>([]);
  const [extrasLoading, setExtrasLoading] = useState(false);
  const [extrasError, setExtrasError] = useState<string | null>(null);
  const [newLabelName, setNewLabelName] = useState('');
  const [newLabelColor, setNewLabelColor] = useState('#6255d9');
  const [editingLabel, setEditingLabel] = useState<{
    id: string;
    name: string;
    color: string;
  } | null>(null);
  const [newCommentBody, setNewCommentBody] = useState('');
  const [editingComment, setEditingComment] = useState<{ id: string; body: string } | null>(null);
  const [reminderDate, setReminderDate] = useState('');
  const [reminderTime, setReminderTime] = useState('');
  const [hasReminder, setHasReminder] = useState(false);
  const checklists = card ? runtime.getCardChecklists(card.id) : [];
  const columnName = columns.find((column) => column.id === card?.columnId)?.name
    || 'Колонка недоступна';

  const loadCoordinatorExtras = useCallback(async (currentCard: Card) => {
    setExtrasLoading(true);
    setExtrasError(null);
    const [labelResult, commentResult] = await Promise.allSettled([
      getBoardLabels(currentCard.boardId),
      getCardComments(currentCard.id),
    ]);
    if (labelResult.status === 'fulfilled') setLabels(labelResult.value.items);
    if (commentResult.status === 'fulfilled') setComments(commentResult.value.items);
    if (labelResult.status === 'rejected' || commentResult.status === 'rejected') {
      setExtrasError(
        'Метки и комментарии доступны при связи с локальным узлом. Чек-листы продолжают работать независимо.',
      );
    }
    setExtrasLoading(false);
  }, []);

  useEffect(() => {
    if (!card) return;
    let active = true;
    setTitle(card.title);
    setDescription(card.description || '');
    setPriority(card.priority);
    setError(null);
    setEditingChecklist(null);
    setEditingItem(null);
    setEditingLabel(null);
    setEditingComment(null);
    void loadCoordinatorExtras(card);
    void loadCardReminder(card.id).then((reminder) => {
      if (!active) return;
      const fields = reminderFields(reminder?.localDateTime);
      setReminderDate(fields.date);
      setReminderTime(fields.time);
      setHasReminder(Boolean(reminder));
    });
    return () => {
      active = false;
    };
  }, [card?.id, loadCoordinatorExtras]);

  async function run(key: string, action: () => Promise<void>) {
    if (busyKey) return;
    setBusyKey(key);
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось сохранить изменение.');
    } finally {
      setBusyKey(null);
    }
  }

  async function save() {
    if (!card || !title.trim()) return;
    await run('card.save', async () => {
      await runtime.updateCard(card.id, {
        title: title.trim(),
        description: description || null,
        priority,
      });
      await updateCardReminderTitle(card.id, title.trim());
      onClose();
    });
  }

  function applyQuickReminder(kind: 'hour' | 'tomorrow') {
    const fields = reminderFields(quickReminder(kind));
    setReminderDate(fields.date);
    setReminderTime(fields.time);
  }

  async function saveReminder() {
    if (!card || !runtime.snapshot) return;
    const localDateTime = reminderFromFields(reminderDate, reminderTime);
    if (!localDateTime) {
      setError('Введите дату как ДД.ММ.ГГГГ, а время как ЧЧ:ММ.');
      return;
    }
    await run('reminder.save', async () => {
      await scheduleCardReminder({
        cardId: card.id,
        boardId: card.boardId,
        boardName: runtime.snapshot!.board.name,
        workspaceId: runtime.snapshot!.workspaceId,
        cardTitle: title.trim() || card.title,
        localDateTime,
      });
      setHasReminder(true);
    });
  }

  async function removeReminder() {
    if (!card) return;
    await run('reminder.cancel', async () => {
      await cancelCardReminder(card.id);
      setHasReminder(false);
    });
  }

  function confirmArchive() {
    if (!card) return;
    const restoring = card.isArchived;
    Alert.alert(
      restoring ? 'Вернуть карточку?' : 'Архивировать карточку?',
      restoring
        ? 'Карточка снова появится на доске.'
        : 'Карточку можно вернуть через режим показа архива.',
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: restoring ? 'Вернуть' : 'Архивировать',
          style: restoring ? 'default' : 'destructive',
          onPress: () => {
            void run('card.archive', async () => {
              if (restoring) await runtime.unarchiveCard(card.id);
              else await runtime.archiveCard(card.id);
              onClose();
            });
          },
        },
      ],
    );
  }

  function confirmDelete() {
    if (!card) return;
    Alert.alert(
      'Что сделать с карточкой?',
      '«Скрыть здесь» действует только на этом телефоне и допускает возврат. «Удалить везде» распространяет tombstone и не даёт старым копиям воскресить карточку.',
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: 'Скрыть здесь',
          onPress: () => {
            void run('card.hide-local', async () => {
              await runtime.hideCardLocally(card.id);
              await cancelCardReminder(card.id);
              onClose();
            });
          },
        },
        {
          text: 'Удалить везде',
          style: 'destructive',
          onPress: () => {
            Alert.alert(
              'Удалить на всех устройствах?',
              'Это глобальное удаление. Автоматического восстановления из старой локальной копии не будет.',
              [
                { text: 'Отмена', style: 'cancel' },
                {
                  text: 'Удалить везде',
                  style: 'destructive',
                  onPress: () => {
                    void run('card.delete', async () => {
                      await runtime.deleteCard(card.id);
                      await cancelCardReminder(card.id);
                      onClose();
                    });
                  },
                },
              ],
            );
          },
        },
      ],
    );
  }

  async function createChecklist() {
    if (!card || !newChecklistTitle.trim()) return;
    await run('checklist.create', async () => {
      await runtime.createChecklist(card.id, newChecklistTitle.trim());
      setNewChecklistTitle('');
    });
  }

  async function renameChecklist() {
    if (!card || !editingChecklist?.title.trim()) return;
    await run(`checklist.update:${editingChecklist.id}`, async () => {
      await runtime.updateChecklist(
        card.id,
        editingChecklist.id,
        editingChecklist.title.trim(),
      );
      setEditingChecklist(null);
    });
  }

  function confirmDeleteChecklist(checklistId: string, checklistTitle: string) {
    if (!card) return;
    Alert.alert(`Удалить чек-лист «${checklistTitle}»?`, 'Все его пункты будут удалены.', [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          void run(`checklist.delete:${checklistId}`, () =>
            runtime.deleteChecklist(card.id, checklistId));
        },
      },
    ]);
  }

  async function createItem(checklistId: string) {
    if (!card) return;
    const value = (newItemByChecklist[checklistId] || '').trim();
    if (!value) return;
    await run(`item.create:${checklistId}`, async () => {
      await runtime.createChecklistItem(card.id, checklistId, value);
      setNewItemByChecklist((current) => ({ ...current, [checklistId]: '' }));
    });
  }

  async function saveItem() {
    if (!card || !editingItem?.title.trim()) return;
    await run(`item.update:${editingItem.id}`, async () => {
      await runtime.updateChecklistItem(
        card.id,
        editingItem.checklistId,
        editingItem.id,
        { title: editingItem.title.trim() },
      );
      setEditingItem(null);
    });
  }

  async function toggleItem(checklistId: string, itemId: string, isDone: boolean) {
    if (!card) return;
    await run(`item.toggle:${itemId}`, () =>
      runtime.toggleChecklistItem(card.id, checklistId, itemId, isDone));
  }

  function confirmDeleteItem(checklistId: string, itemId: string, itemTitle: string) {
    if (!card) return;
    Alert.alert(`Удалить пункт «${itemTitle}»?`, undefined, [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          void run(`item.delete:${itemId}`, () =>
            runtime.deleteChecklistItem(card.id, checklistId, itemId));
        },
      },
    ]);
  }

  async function createLabel() {
    if (!card || !newLabelName.trim() || !newLabelColor.trim()) return;
    await run('label.create', async () => {
      const created = await createBoardLabel(card.boardId, {
        name: newLabelName.trim(),
        color: newLabelColor.trim(),
      });
      setLabels((current) => [...current, created]);
      setNewLabelName('');
    });
  }

  async function saveLabel() {
    if (!editingLabel?.name.trim() || !editingLabel.color.trim()) return;
    await run(`label.update:${editingLabel.id}`, async () => {
      const updated = await updateBoardLabel(editingLabel.id, {
        name: editingLabel.name.trim(),
        color: editingLabel.color.trim(),
      });
      setLabels((current) => current.map((label) =>
        label.id === updated.id ? updated : label));
      setEditingLabel(null);
    });
  }

  function confirmDeleteLabel(label: BoardLabel) {
    if (!card) return;
    Alert.alert(`Удалить метку «${label.name}»?`, 'Она будет снята со всех карточек.', [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          void run(`label.delete:${label.id}`, async () => {
            await deleteBoardLabel(label.id);
            setLabels((current) => current.filter((candidate) => candidate.id !== label.id));
            await runtime.mergeCoordinatorCard({
              ...card,
              labelIds: (card.labelIds || []).filter((id) => id !== label.id),
            });
          });
        },
      },
    ]);
  }

  async function toggleLabel(labelId: string) {
    if (!card) return;
    const current = card.labelIds || [];
    const next = current.includes(labelId)
      ? current.filter((id) => id !== labelId)
      : [...current, labelId];
    await run(`label.toggle:${labelId}`, async () => {
      const updated = await replaceCardLabels(card.id, next);
      await runtime.mergeCoordinatorCard(updated);
    });
  }

  async function createCardComment() {
    if (!card || !newCommentBody.trim()) return;
    await run('comment.create', async () => {
      const created = await createComment(card.id, newCommentBody.trim());
      setComments((current) => [...current, created]);
      setNewCommentBody('');
      await runtime.mergeCoordinatorCard({
        ...card,
        commentCount: (card.commentCount || 0) + 1,
      });
    });
  }

  async function saveComment() {
    if (!editingComment?.body.trim()) return;
    await run(`comment.update:${editingComment.id}`, async () => {
      const updated = await updateComment(editingComment.id, editingComment.body.trim());
      setComments((current) => current.map((comment) =>
        comment.id === updated.id ? updated : comment));
      setEditingComment(null);
    });
  }

  function confirmDeleteComment(comment: Comment) {
    if (!card) return;
    Alert.alert('Удалить комментарий?', undefined, [
      { text: 'Отмена', style: 'cancel' },
      {
        text: 'Удалить',
        style: 'destructive',
        onPress: () => {
          void run(`comment.delete:${comment.id}`, async () => {
            await deleteComment(comment.id);
            setComments((current) => current.filter((candidate) => candidate.id !== comment.id));
            await runtime.mergeCoordinatorCard({
              ...card,
              commentCount: Math.max((card.commentCount || 1) - 1, 0),
            });
          });
        },
      },
    ]);
  }

  return (
    <FormModal visible={Boolean(card)} title="Карточка" onClose={onClose}>
      {readOnly ? <InlineNotice text="Гостевой доступ: карточка открыта только для чтения." tone="neutral" /> : null}
      <Field label="Название" value={title} editable={!readOnly} onChangeText={setTitle} />
      <MarkdownEditor value={description} onChange={setDescription} readOnly={readOnly}/>
      <View style={{flexDirection:'row',flexWrap:'wrap',gap:8}}>
       <Button label="Поделиться .md" compact onPress={()=>{void run('export.markdown',async()=>{if(card)await shareCardMarkdown({...card,title,description});});}}/>
       <Button label="В Obsidian" compact onPress={()=>{void run('export.obsidian',async()=>{if(card)await openCardInObsidian({...card,title,description});});}}/>
      </View>

      <View style={styles.cardMetaBlock}>
        <View style={styles.columnIndicator}>
          <Text style={[styles.metaLabel, { color: colors.muted }]}>Колонка</Text>
          <Text style={[styles.columnName, { color: colors.text }]} numberOfLines={1}>
            {columnName}
          </Text>
        </View>
        <PriorityStars value={priority} onChange={setPriority} disabled={readOnly} />
      </View>

      <View style={styles.section}>
        <SectionTitle
          title="Напоминание"
          detail={hasReminder ? 'включено' : 'выключено'}
        />
        <Text style={[styles.sectionCaption, { color: colors.muted }]}>
          Только на этом устройстве, по его локальным дате и времени.
        </Text>
        <View style={styles.reminderFields}>
          <View style={styles.reminderField}>
            <Field
              label="Дата"
              value={reminderDate}
              keyboardType="numbers-and-punctuation"
              placeholder="ДД.ММ.ГГГГ"
              onChangeText={setReminderDate}
            />
          </View>
          <View style={styles.reminderTimeField}>
            <Field
              label="Время"
              value={reminderTime}
              keyboardType="numbers-and-punctuation"
              placeholder="ЧЧ:ММ"
              onChangeText={setReminderTime}
            />
          </View>
        </View>
        <View style={styles.inlineActions}>
          <Button label="Через час" compact variant="ghost" onPress={() => applyQuickReminder('hour')} />
          <Button label="Завтра 09:00" compact variant="ghost" onPress={() => applyQuickReminder('tomorrow')} />
        </View>
        <View style={styles.inlineActions}>
          <Button
            label={hasReminder ? 'Обновить' : 'Запланировать'}
            compact
            variant="primary"
            loading={busyKey === 'reminder.save'}
            onPress={() => void saveReminder()}
          />
          {hasReminder ? (
            <Button
              label="Выключить"
              compact
              variant="danger"
              loading={busyKey === 'reminder.cancel'}
              onPress={() => void removeReminder()}
            />
          ) : null}
        </View>
      </View>

      <View style={styles.section}>
        <View style={styles.checklistSectionHeader}>
          <Text style={[styles.sectionEyebrow, { color: colors.muted }]}>Чек-листы</Text>
          <Text style={[styles.sectionCount, { color: colors.muted }]}>
            {checklists.reduce((sum, checklist) => sum + checklist.items.filter((item) => item.isDone).length, 0)}/{checklists.reduce((sum, checklist) => sum + checklist.items.length, 0)}
          </Text>
        </View>
        {checklists.map((checklist) => (
          <View
            key={checklist.id}
            style={[
              styles.checklist,
              { borderColor: colors.border },
            ]}
          >
            {editingChecklist?.id === checklist.id ? (
              <View style={styles.inlineEditor}>
                <Field
                  label="Название чек-листа"
                  value={editingChecklist.title}
                  onChangeText={(value) => setEditingChecklist({ ...editingChecklist, title: value })}
                />
                <View style={styles.inlineActions}>
                  <Button label="Сохранить" compact variant="primary" onPress={() => void renameChecklist()} />
                  <Button label="Отмена" compact variant="ghost" onPress={() => setEditingChecklist(null)} />
                </View>
              </View>
            ) : (
              <View style={styles.entityHeader}>
                <Text style={[styles.checklistTitle, { color: colors.text }]}> 
                  {checklist.title}
                </Text>
                {!readOnly ? <><SmallAction
                  label="✎"
                  onPress={() => setEditingChecklist({
                    id: checklist.id,
                    title: checklist.title,
                  })}
                />
                <SmallAction
                  label="×"
                  danger
                  onPress={() => confirmDeleteChecklist(checklist.id, checklist.title)}
                /></> : null}
              </View>
            )}

            {checklist.items.map((item) => (
              editingItem?.id === item.id ? (
                <View key={item.id} style={styles.inlineEditor}>
                  <Field
                    label="Текст пункта"
                    value={editingItem.title}
                    onChangeText={(value) => setEditingItem({ ...editingItem, title: value })}
                  />
                  <View style={styles.inlineActions}>
                    <Button label="Сохранить" compact variant="primary" onPress={() => void saveItem()} />
                    <Button label="Отмена" compact variant="ghost" onPress={() => setEditingItem(null)} />
                  </View>
                </View>
              ) : (
                <View key={item.id} style={styles.checklistItemRow}>
                  <Pressable
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: item.isDone }}
                    disabled={readOnly}
                    onPress={() => void toggleItem(checklist.id, item.id, !item.isDone)}
                    style={({ pressed }) => [
                      styles.checklistItem,
                      { opacity: pressed || busyKey === `item.toggle:${item.id}` ? 0.58 : 1 },
                    ]}
                  >
                    <View
                      style={[
                        styles.checkbox,
                        {
                          backgroundColor: item.isDone ? colors.accent : 'transparent',
                          borderColor: item.isDone ? colors.accent : colors.border,
                        },
                      ]}
                    >
                      {item.isDone ? (
                        <Text style={[styles.checkboxMark, { color: colors.background }]}>✓</Text>
                      ) : null}
                    </View>
                    <Text
                      style={[
                        styles.checklistItemText,
                        {
                          color: item.isDone ? colors.muted : colors.text,
                          textDecorationLine: item.isDone ? 'line-through' : 'none',
                        },
                      ]}
                    >
                      {item.title}
                    </Text>
                  </Pressable>
                  {!readOnly ? <><SmallAction
                    label="✎"
                    onPress={() => setEditingItem({
                      checklistId: checklist.id,
                      id: item.id,
                      title: item.title,
                    })}
                  />
                  <SmallAction
                    label="×"
                    danger
                    onPress={() => confirmDeleteItem(checklist.id, item.id, item.title)}
                  /></> : null}
                </View>
              )
            ))}
            {!checklist.items.length ? (
              <Text style={[styles.emptyChecklist, { color: colors.muted }]}>
                В этом чек-листе пока нет пунктов
              </Text>
            ) : null}
            {!readOnly ? <View style={styles.composerRow}>
              <View style={styles.composerField}>
                <Field
                  label="Новый пункт"
                  value={newItemByChecklist[checklist.id] || ''}
                  onChangeText={(value) => setNewItemByChecklist((current) => ({
                    ...current,
                    [checklist.id]: value,
                  }))}
                  placeholder="Что проверить"
                />
              </View>
              <Button
                label="+"
                compact
                variant="primary"
                disabled={!(newItemByChecklist[checklist.id] || '').trim()}
                onPress={() => void createItem(checklist.id)}
              />
            </View> : null}
          </View>
        ))}
        {!readOnly ? <View style={styles.composerRow}>
          <View style={styles.composerField}>
            <Field
              label="Новый чек-лист"
              value={newChecklistTitle}
              onChangeText={setNewChecklistTitle}
              placeholder="Например, Перед релизом"
            />
          </View>
          <Button
            label="+"
            compact
            variant="primary"
            disabled={!newChecklistTitle.trim()}
            onPress={() => void createChecklist()}
          />
        </View> : null}
      </View>

      <View style={styles.section}>
        <SectionTitle title="Метки" detail={extrasLoading ? 'загрузка' : undefined} />
        {extrasError ? <InlineNotice text={extrasError} tone="warning" /> : null}
        {labels.map((label) => {
          const selected = Boolean(card?.labelIds?.includes(label.id));
          return editingLabel?.id === label.id ? (
            <View key={label.id} style={styles.inlineEditor}>
              <Field
                label="Название метки"
                value={editingLabel.name}
                onChangeText={(value) => setEditingLabel({ ...editingLabel, name: value })}
              />
              <Field
                label="Цвет"
                value={editingLabel.color}
                onChangeText={(value) => setEditingLabel({ ...editingLabel, color: value })}
              />
              <View style={styles.inlineActions}>
                <Button label="Сохранить" compact variant="primary" onPress={() => void saveLabel()} />
                <Button label="Отмена" compact variant="ghost" onPress={() => setEditingLabel(null)} />
              </View>
            </View>
          ) : (
            <View key={label.id} style={styles.labelRow}>
              <Pressable
                disabled={readOnly}
                onPress={() => void toggleLabel(label.id)}
                style={({ pressed }) => [
                  styles.labelChoice,
                  {
                    backgroundColor: selected ? colors.accentSoft : colors.surface,
                    borderColor: selected ? colors.accent : colors.border,
                    opacity: pressed ? 0.68 : 1,
                  },
                ]}
              >
                <View style={[styles.labelDot, { backgroundColor: label.color }]} />
                <Text style={[styles.labelText, { color: colors.text }]}>{label.name}</Text>
                <Text style={[styles.labelState, { color: colors.muted }]}>
                  {selected ? 'выбрана' : 'не выбрана'}
                </Text>
              </Pressable>
              {!readOnly ? <><SmallAction
                label="Изм."
                onPress={() => setEditingLabel({
                  id: label.id,
                  name: label.name,
                  color: label.color,
                })}
              />
              <SmallAction label="×" danger onPress={() => confirmDeleteLabel(label)} /></> : null}
            </View>
          );
        })}
        {!readOnly ? <View style={styles.inlineEditor}>
          <Field
            label="Новая метка"
            value={newLabelName}
            onChangeText={setNewLabelName}
            placeholder="Например, Ошибка"
          />
          <Field
            label="Цвет"
            value={newLabelColor}
            onChangeText={setNewLabelColor}
            placeholder="#6255d9"
          />
          <Button
            label="Добавить метку"
            compact
            variant="primary"
            disabled={!newLabelName.trim() || !newLabelColor.trim()}
            onPress={() => void createLabel()}
          />
        </View> : null}
      </View>

      <View style={styles.section}>
        <SectionTitle title="Комментарии" detail={`${comments.length}`} />
        {comments.map((comment) => (
          editingComment?.id === comment.id ? (
            <View key={comment.id} style={styles.inlineEditor}>
              <Field
                label="Комментарий"
                value={editingComment.body}
                onChangeText={(value) => setEditingComment({ ...editingComment, body: value })}
                multiline
              />
              <View style={styles.inlineActions}>
                <Button label="Сохранить" compact variant="primary" onPress={() => void saveComment()} />
                <Button label="Отмена" compact variant="ghost" onPress={() => setEditingComment(null)} />
              </View>
            </View>
          ) : (
            <View
              key={comment.id}
              style={[
                styles.comment,
                { borderColor: colors.border },
              ]}
            >
              <Text style={[styles.commentBody, { color: colors.text }]}>{comment.body}</Text>
              {!readOnly ? <View style={styles.inlineActions}>
                <SmallAction
                  label="Изменить"
                  onPress={() => setEditingComment({ id: comment.id, body: comment.body })}
                />
                <SmallAction label="Удалить" danger onPress={() => confirmDeleteComment(comment)} />
              </View> : null}
            </View>
          )
        ))}
        {!readOnly ? <><Field
          label="Новый комментарий"
          value={newCommentBody}
          onChangeText={setNewCommentBody}
          multiline
          placeholder="Напишите заметку"
        />
        <Button
          label="Добавить комментарий"
          compact
          variant="primary"
          disabled={!newCommentBody.trim()}
          onPress={() => void createCardComment()}
        /></> : null}
      </View>

      {error ? <InlineNotice text={error} tone="danger" /> : null}
      {!readOnly ? <><Button
        label="Сохранить карточку"
        variant="primary"
        loading={busyKey === 'card.save'}
        disabled={!title.trim()}
        onPress={() => void save()}
      />
      <Button
        label={card?.isArchived ? 'Вернуть из архива' : 'Архивировать'}
        onPress={confirmArchive}
      />
      <Button label="Убрать карточку…" variant="danger" onPress={confirmDelete} /></> : null}
    </FormModal>
  );
}

const styles = StyleSheet.create({
  section: {
    gap: spacing.sm,
  },
  sectionCaption: {
    fontSize: 12,
    lineHeight: 17,
  },
  cardMetaBlock: {
    gap: spacing.xs,
    paddingVertical: spacing.xs,
  },
  columnIndicator: {
    minHeight: 32,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  metaLabel: {
    width: 72,
    fontSize: 12,
    fontWeight: '700',
  },
  columnName: {
    flex: 1,
    fontSize: 16,
    fontWeight: '800',
  },
  priorityLine: {
    minHeight: 36,
    flexDirection: 'row',
    alignItems: 'center',
  },
  priorityLabel: {
    width: 72,
    fontSize: 12,
    fontWeight: '700',
  },
  stars: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  starHit: {
    width: 30,
    minHeight: 34,
    alignItems: 'center',
    justifyContent: 'center',
  },
  star: {
    fontSize: 24,
    lineHeight: 28,
  },
  priorityValue: {
    flex: 1,
    minWidth: 0,
    marginLeft: spacing.xs,
    fontSize: 11,
    textAlign: 'right',
  },
  reminderFields: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  reminderField: {
    flex: 1.45,
  },
  reminderTimeField: {
    flex: 1,
  },
  checklistSectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionEyebrow: {
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.7,
    textTransform: 'uppercase',
  },
  sectionCount: {
    fontSize: 11,
    fontWeight: '700',
  },
  checklist: {
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  entityHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  checklistTitle: {
    flex: 1,
    fontSize: 17,
    lineHeight: 22,
    fontWeight: '800',
  },
  checklistItemRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  checklistItem: {
    minHeight: 38,
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  checkbox: {
    width: 22,
    height: 22,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderRadius: 6,
  },
  checkboxMark: {
    fontSize: 14,
    fontWeight: '900',
  },
  checklistItemText: {
    flex: 1,
    fontSize: 14,
    lineHeight: 19,
  },
  emptyChecklist: {
    fontSize: 12,
    lineHeight: 17,
  },
  composerRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.xs,
  },
  composerField: {
    flex: 1,
  },
  inlineEditor: {
    gap: spacing.xs,
  },
  inlineActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  smallAction: {
    minHeight: 32,
    minWidth: 32,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  smallActionText: {
    fontSize: 17,
    fontWeight: '800',
  },
  labelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  labelChoice: {
    minHeight: 42,
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
  },
  labelDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
  },
  labelText: {
    flex: 1,
    fontSize: 13,
    fontWeight: '700',
  },
  labelState: {
    fontSize: 10,
  },
  comment: {
    gap: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingVertical: spacing.sm,
  },
  commentBody: {
    fontSize: 14,
    lineHeight: 20,
  },
});
