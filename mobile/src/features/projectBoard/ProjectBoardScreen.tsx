import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';

import { radius, spacing, useAppColors } from '../../app/theme';
import type { RootStackParamList } from '../../app/navigation/types';
import { useConnection } from '../connection/ConnectionProvider';
import { FormModal, InlineNotice, Screen, ScreenHeader, StateView } from '../../shared/ui/primitives';
import { describeSelection, projectBoardView, type ProjectBoardCardView } from './model';
import { loadLocalProjectBoard, loadProjectBoard, type LoadedProjectBoard } from './store';

type Props = NativeStackScreenProps<RootStackParamList, 'ProjectBoard'>;

// contracts/project-board/1: the ecosystem's own board, read-only and outside
// the replica, so linking nodes never duplicates it. The screen never waits for
// the node: the APK copy and the saved copy render first.
export function ProjectBoardScreen({ navigation }: Props) {
  const colors = useAppColors();
  const { nodeOrigin } = useConnection();
  const { width } = useWindowDimensions();
  const [loaded, setLoaded] = useState<LoadedProjectBoard | null>(null);
  const [checking, setChecking] = useState(true);
  const [openCard, setOpenCard] = useState<ProjectBoardCardView | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadLocalProjectBoard().then((local) => { if (!cancelled) setLoaded((current) => current ?? local); });
    void loadProjectBoard(nodeOrigin)
      .then((fresh) => { if (!cancelled) setLoaded(fresh); })
      .finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, [nodeOrigin]);

  const view = useMemo(() => (loaded?.raw ? projectBoardView(loaded.raw) : null), [loaded?.raw]);
  const described = loaded ? describeSelection(loaded.selection, loaded.node) : null;
  const columnWidth = Math.min(320, Math.max(260, width - spacing.lg * 3));

  return (
    <Screen>
      <ScreenHeader
        title="Доска проекта"
        subtitle={described?.line ?? 'Загружаем…'}
        onBack={() => navigation.goBack()}
      />
      {!view ? (
        <StateView title="Открываем доску проекта" busy />
      ) : (
        <>
          <View style={styles.notes}>
            <InlineNotice text="Только чтение. Это доска, на которой p2pKanban ведёт свою разработку: она встроена в приложение и не входит в ваши пространства." />
            {checking ? <Text style={[styles.note, { color: colors.muted }]}>Проверяем узел…</Text> : null}
            {described?.notes.map((note) => (
              <Text key={note} style={[styles.note, { color: colors.muted }]}>{note}</Text>
            ))}
          </View>
          <ScrollView horizontal contentContainerStyle={styles.columns} showsHorizontalScrollIndicator={false}>
            {view.columns.map((column) => (
              <View
                key={column.id}
                style={[styles.column, { width: columnWidth, backgroundColor: colors.surfaceMuted, borderColor: colors.border }]}
              >
                <Text style={[styles.columnTitle, { color: colors.text }]}>{column.name}</Text>
                <Text style={[styles.columnCount, { color: colors.muted }]}>{column.cards.length}</Text>
                <ScrollView contentContainerStyle={styles.cards}>
                  {column.cards.map((card) => (
                    <Pressable
                      key={card.id}
                      accessibilityRole="button"
                      onPress={() => setOpenCard(card)}
                      style={({ pressed }) => [
                        styles.card,
                        { backgroundColor: colors.surface, borderColor: colors.border, opacity: pressed ? 0.7 : 1 },
                      ]}
                    >
                      <Text style={[styles.cardTitle, { color: colors.text }]}>{card.title}</Text>
                      <Labels card={card} />
                      {card.total ? (
                        <Text style={[styles.meta, { color: colors.muted }]}>Чек-лист {card.done}/{card.total}</Text>
                      ) : null}
                      {card.comments.length ? (
                        <Text style={[styles.meta, { color: colors.muted }]}>Комментариев: {card.comments.length}</Text>
                      ) : null}
                    </Pressable>
                  ))}
                </ScrollView>
              </View>
            ))}
          </ScrollView>
        </>
      )}
      <FormModal visible={Boolean(openCard)} title={openCard?.title ?? ''} onClose={() => setOpenCard(null)}>
        {openCard ? <CardDetails card={openCard} /> : null}
      </FormModal>
    </Screen>
  );
}

function Labels({ card }: { card: ProjectBoardCardView }) {
  const colors = useAppColors();
  if (!card.labels.length) return null;
  return (
    <View style={styles.labels}>
      {card.labels.map((label) => (
        <View key={label.name} style={[styles.label, { borderColor: label.color }]}>
          <View style={[styles.dot, { backgroundColor: label.color }]} />
          <Text style={[styles.labelText, { color: colors.muted }]}>{label.name}</Text>
        </View>
      ))}
    </View>
  );
}

function CardDetails({ card }: { card: ProjectBoardCardView }) {
  const colors = useAppColors();
  return (
    <View style={styles.details}>
      <Text style={[styles.meta, { color: colors.muted }]}>Только чтение</Text>
      <Labels card={card} />
      <Text style={[styles.body, { color: colors.text }]}>{card.description || 'Без описания.'}</Text>
      {card.checklists.map((checklist) => (
        <View key={checklist.id} style={styles.section}>
          <Text style={[styles.sectionTitle, { color: colors.text }]}>{checklist.title}</Text>
          {checklist.items.map((item) => (
            <Text key={item.id} style={[styles.body, { color: item.isDone ? colors.muted : colors.text }]}>
              {item.isDone ? '✓' : '○'} {item.title}
            </Text>
          ))}
        </View>
      ))}
      {card.comments.length ? (
        <View style={styles.section}>
          <Text style={[styles.sectionTitle, { color: colors.text }]}>Комментарии</Text>
          {card.comments.map((comment) => (
            <View key={comment.id} style={[styles.comment, { borderColor: colors.border, backgroundColor: colors.surfaceMuted }]}>
              {comment.createdAt ? <Text style={[styles.meta, { color: colors.muted }]}>{comment.createdAt.slice(0, 10)}</Text> : null}
              <Text style={[styles.body, { color: colors.text }]}>{comment.body}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  notes: { gap: spacing.xs, paddingVertical: spacing.sm },
  note: { fontSize: 13, lineHeight: 18 },
  columns: { gap: spacing.sm, paddingBottom: spacing.md },
  column: { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, gap: spacing.xs },
  columnTitle: { fontSize: 16, fontWeight: '700' },
  columnCount: { fontSize: 12 },
  cards: { gap: spacing.sm, paddingBottom: spacing.lg },
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, gap: 6 },
  cardTitle: { fontSize: 15, fontWeight: '600', lineHeight: 20 },
  labels: { flexDirection: 'row', flexWrap: 'wrap', gap: 4 },
  label: { flexDirection: 'row', alignItems: 'center', gap: 4, borderWidth: 1, borderRadius: 999, paddingHorizontal: 6, paddingVertical: 1 },
  dot: { width: 7, height: 7, borderRadius: 4 },
  labelText: { fontSize: 11 },
  meta: { fontSize: 12 },
  details: { gap: spacing.sm },
  body: { fontSize: 14, lineHeight: 20 },
  section: { gap: 4 },
  sectionTitle: { fontSize: 15, fontWeight: '700', marginTop: spacing.xs },
  comment: { borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm, gap: 2 },
});
