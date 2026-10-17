import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import * as Clipboard from 'expo-clipboard';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import type { RootStackParamList } from '../../app/navigation/types';
import { spacing, useAppColors } from '../../app/theme';
import { previousRunLines, setDebugMode, useDebugMode } from '../../shared/debug/debugMode';
import { debugJournalFilename, renderDebugJournal } from '../../shared/debug/export';
import { mobilePlatform, mobileSoftware } from '../../shared/errorReport/collect';
import { journalEntries, subscribeJournal, type JournalEntry } from '../../shared/errorReport/journal';
import { redact } from '../../shared/errorReport/report';
import { Button, Screen, ScreenHeader } from '../../shared/ui/primitives';

type Props = NativeStackScreenProps<RootStackParamList, 'DebugJournal'>;
type Filter = 'all' | 'problems';
type Source = 'now' | 'previous';

const REDRAW_MS = 300;

function useJournal(paused: boolean) {
  const [entries, setEntries] = useState<JournalEntry[]>(journalEntries);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = subscribeJournal(() => {
      if (pausedRef.current || timer) return;
      timer = setTimeout(() => { timer = null; setEntries(journalEntries()); }, REDRAW_MS);
    });
    if (!paused) setEntries(journalEntries());
    return () => { unsubscribe(); if (timer) clearTimeout(timer); };
  }, [paused]);
  return entries;
}

function Chip({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  const colors = useAppColors();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: active }}
      onPress={onPress}
      style={({ pressed }) => [styles.chip, {
        backgroundColor: active ? colors.accentSoft : colors.surface,
        borderColor: active ? colors.accent : colors.border,
        opacity: pressed ? 0.68 : 1,
      }]}
    >
      <Text style={[styles.chipText, { color: active ? colors.accentText : colors.text }]}>{label}</Text>
    </Pressable>
  );
}

export function DebugJournalScreen({ navigation }: Props) {
  const colors = useAppColors();
  const debugMode = useDebugMode();
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const [source, setSource] = useState<Source>('now');
  const [notice, setNotice] = useState<string | null>(null);
  const entries = useJournal(paused);
  const listRef = useRef<FlatList<string>>(null);
  const previous = previousRunLines();

  const lines = useMemo(() => {
    if (source === 'previous') {
      return filter === 'all' ? previous : previous.filter((line) => / (warn|error) /.test(line));
    }
    const shown = filter === 'all' ? entries : entries.filter((entry) => entry.level === 'warn' || entry.level === 'error');
    return shown.map((entry) => redact(entry.line)[0]);
  }, [entries, filter, previous, source]);

  function exportText() {
    return renderDebugJournal({
      software: mobileSoftware(),
      platform: mobilePlatform(),
      exportedAt: new Date().toISOString(),
      lines: journalEntries().map((entry) => entry.line),
      previous,
      debugMode,
    }).text;
  }

  async function copy() {
    try {
      await Clipboard.setStringAsync(exportText());
      setNotice('Журнал скопирован в Markdown: вставьте в сообщение.');
    } catch {
      setNotice('Не удалось скопировать журнал.');
    }
  }

  async function share() {
    try {
      const at = new Date().toISOString();
      const file = new File(Paths.cache, debugJournalFilename('mobile', at));
      file.write(exportText());
      await Sharing.shareAsync(file.uri, { mimeType: 'text/markdown', dialogTitle: 'Журнал отладки p2pKanban' });
      setNotice(null);
    } catch {
      setNotice('Не удалось сохранить файл журнала.');
    }
  }

  const levelColor = (line: string) => / error /.test(line) ? colors.danger : / warn /.test(line) ? colors.warning : colors.text;

  return (
    <Screen>
      <ScreenHeader
        title="Журнал отладки"
        subtitle={`${debugMode ? 'Режим отладки включён' : 'Режим выключен'} · ${lines.length} строк`}
        onBack={() => navigation.goBack()}
      />
      <View style={styles.controls}>
        <Button
          label={debugMode ? 'Выключить режим отладки' : 'Включить режим отладки'}
          variant={debugMode ? 'secondary' : 'primary'}
          compact
          onPress={() => void setDebugMode(!debugMode)}
        />
        {!debugMode ? (
          <Text style={[styles.caption, { color: colors.muted }]}>
            Без режима отладки здесь только запросы к узлу и ошибки, последние 200 строк.
          </Text>
        ) : null}
        <View style={styles.row}>
          <Chip label="Этот запуск" active={source === 'now'} onPress={() => setSource('now')} />
          {previous.length ? (
            <Chip label="Прошлый запуск" active={source === 'previous'} onPress={() => setSource('previous')} />
          ) : null}
          <Chip label="Всё" active={filter === 'all'} onPress={() => setFilter('all')} />
          <Chip label="Ошибки" active={filter === 'problems'} onPress={() => setFilter('problems')} />
          {source === 'now' ? (
            <Chip label={paused ? 'Продолжить' : 'Пауза'} active={paused} onPress={() => setPaused(!paused)} />
          ) : null}
        </View>
      </View>
      <FlatList
        ref={listRef}
        style={[styles.list, { borderColor: colors.border, backgroundColor: colors.surface }]}
        data={lines}
        keyExtractor={(_, index) => String(index)}
        renderItem={({ item }) => (
          <Text selectable style={[styles.line, { color: levelColor(item) }]}>{item}</Text>
        )}
        onContentSizeChange={() => { if (!paused && source === 'now') listRef.current?.scrollToEnd({ animated: false }); }}
        initialNumToRender={40}
        windowSize={7}
        ListEmptyComponent={<Text style={[styles.caption, { color: colors.muted }]}>Строк пока нет.</Text>}
      />
      <View style={styles.row}>
        <Button label="Скопировать" compact onPress={() => void copy()} />
        <Button label="Сохранить .md" compact onPress={() => void share()} />
      </View>
      {notice ? <Text style={[styles.caption, { color: colors.muted }]}>{notice}</Text> : null}
      <Text style={[styles.caption, { color: colors.muted }]}>
        Пароли, токены и ключи вырезаются по тем же правилам, что в «Скопировать подробности».
        Тексты карточек в журнал не пишутся: только id, виды операций и числа.
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  controls: {
    gap: spacing.sm,
  },
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  chip: {
    minHeight: 34,
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
    borderWidth: 1,
    borderRadius: 8,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '700',
  },
  list: {
    flex: 1,
    borderWidth: 1,
    borderRadius: 8,
    padding: spacing.xs,
  },
  line: {
    fontFamily: 'monospace',
    fontSize: 11,
    lineHeight: 15,
    paddingVertical: 1,
  },
  caption: {
    fontSize: 13,
    lineHeight: 19,
  },
});
