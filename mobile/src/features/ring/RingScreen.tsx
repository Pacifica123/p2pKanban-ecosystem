import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useCallback, useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { RootStackParamList } from '../../app/navigation/types';
import { spacing, useAppColors } from '../../app/theme';
import { Button, Field, InlineNotice, Panel, Screen, ScreenHeader, SectionTitle, StateView } from '../../shared/ui/primitives';
import { createRing, deviceName, loadRing, saveDeviceName, syncRing, type RingView } from './service';

type Props = NativeStackScreenProps<RootStackParamList, 'Ring'>;

const KIND_TEXT = { web: 'веб-узел', android: 'телефон', arch: 'ПК Arch' } as const;
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const short = (key: string) => `${key.slice(0, 8)}…${key.slice(-4)}`;
const when = (seconds: number) => new Date(seconds * 1000).toLocaleString();

export function RingScreen({ navigation }: Props) {
  const colors = useAppColors();
  const [view, setView] = useState<RingView | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState<'create' | 'sync' | 'name' | null>(null);
  const [notice, setNotice] = useState<{ text: string; tone: 'danger' | 'success'; error?: unknown } | null>(null);

  const reload = useCallback(async () => {
    setView(await loadRing());
    setName(await deviceName());
  }, []);

  useEffect(() => navigation.addListener('focus', () => { void reload(); }), [navigation, reload]);

  async function run(kind: 'create' | 'sync' | 'name', action: () => Promise<unknown>, done: string) {
    setBusy(kind);
    setNotice(null);
    try {
      await action();
      await reload();
      setNotice({ text: done, tone: 'success' });
    } catch (error) {
      setNotice({ text: message(error), tone: 'danger', error });
    } finally {
      setBusy(null);
    }
  }

  if (!view) {
    return <Screen><StateView title="Читаем кольцо" busy /></Screen>;
  }
  const { state, stored } = view;
  const stale = new Map(view.skew.map(s => [s.publicKey, s]));
  const report = stored?.lastSync ?? null;
  const boards = view.items.filter(i => i.kind === 'board' && i.deleted !== true).length;
  const spaces = view.items.filter(i => i.kind === 'space' && i.deleted !== true).length;

  return (
    <Screen scroll>
      <ScreenHeader title="Кольцо устройств" subtitle={state ? `${state.members.length} устр.` : 'кольца нет'} onBack={() => navigation.goBack()} />

      {notice ? <InlineNotice text={notice.text} tone={notice.tone} error={notice.error} /> : null}

      <Panel style={styles.panel}>
        <SectionTitle title="Добавить по QR" />
        <Text style={[styles.caption, { color: colors.muted }]}>
          Узел показывает QR в «Настройках → Кольцо устройств». Телефон всегда сканирует: QR «телефон входит» вводит
          телефон в кольцо узла, QR «добавить узел» добавляет узел в кольцо телефона. Потом сравните код из шести цифр
          на обоих экранах.
        </Text>
        <Button label="Сканировать QR" variant="primary" onPress={() => navigation.navigate('RingScan')} />
      </Panel>

      <Panel style={styles.panel}>
        <SectionTitle title="Это устройство" detail={short(view.me)} />
        <Field label="Имя в кольце" value={name} onChangeText={setName} maxLength={64}
          hint="Так телефон видят другие устройства кольца." />
        <Button label="Сохранить имя" compact loading={busy === 'name'} disabled={busy !== null}
          onPress={() => void run('name', () => saveDeviceName(name), 'Имя сохранено; другие увидят его в новом устройстве или после R5.')} />
      </Panel>

      {!state ? (
        <Panel style={styles.panel}>
          <SectionTitle title="Своё кольцо" />
          <Text style={[styles.caption, { color: colors.muted }]}>
            Если узла с кольцом нет, телефон может начать кольцо сам и потом добавить узел по QR «добавить узел».
            Relay берутся из досок, которые телефон уже знает от узла.
          </Text>
          <Button label="Создать кольцо на этом телефоне" loading={busy === 'create'} disabled={busy !== null}
            onPress={() => void run('create', () => createRing(name), 'Кольцо создано и отправлено в relay.')} />
        </Panel>
      ) : (
        <>
          <Panel style={styles.panel}>
            <SectionTitle title="Устройства" detail={`кольцо ${state.accountId.slice(0, 8)}`} />
            {state.members.map(member => {
              const skew = stale.get(member.publicKey);
              const seen = stored?.presences[member.publicKey]?.seenAt;
              return (
                <View key={member.publicKey} style={[styles.member, { borderColor: colors.border }]}>
                  <Text style={[styles.memberName, { color: colors.text }]}>
                    {member.name}{member.publicKey === view.me ? ' (это устройство)' : ''}
                  </Text>
                  <Text style={[styles.caption, { color: colors.muted }]}>
                    {KIND_TEXT[member.kind] ?? member.kind} · {member.role === 'admin' ? 'admin' : 'участник'} · {short(member.publicKey)}
                  </Text>
                  {member.publicKey !== view.me ? (
                    <Text style={[styles.caption, { color: skew ? colors.danger : colors.muted }]}>
                      {seen ? `был в сети ${when(seen)}` : 'присутствия ещё не было'}
                      {skew?.staleRing ? ' · журнал отстаёт' : ''}
                      {skew?.missingProtocols.length ? ` · не знает ${skew.missingProtocols.join(', ')}` : ''}
                    </Text>
                  ) : null}
                </View>
              );
            })}
            {state.readerOutdated.length ? (
              <InlineNotice tone="warning" text="В журнале есть записи новее этой версии приложения: обновите телефон, чтобы добавлять устройства." />
            ) : null}
          </Panel>

          <Panel style={styles.panel}>
            <SectionTitle title="Связка ключей" detail={`${spaces} простр. · ${boards} досок`} />
            <Text style={[styles.caption, { color: colors.muted }]}>
              Доски других устройств ставятся на телефон сами и дальше идут через relay, без узла.
            </Text>
            <Text style={[styles.caption, { color: colors.muted }]}>
              Relay кольца: {state.relays?.urls.join(', ') || 'нет'} (нужно подтверждение от {state.relays?.minAcks ?? 1})
            </Text>
            {report ? (
              <Text style={[styles.caption, { color: report.errors.length || !report.quorum ? colors.danger : colors.muted }]}>
                Последний обмен {when(report.at)}: кворум {report.quorum ? 'собран' : 'не собран'}, получено {report.fetched},
                новых записей {report.newEntries}, связок {report.keyringCopies}, поставлено досок {report.installedBoards}
                {report.errors.length ? `. Ошибки: ${report.errors.slice(0, 4).join('; ')}` : ''}
              </Text>
            ) : null}
            <Button label="Обменяться сейчас" loading={busy === 'sync'} disabled={busy !== null}
              onPress={() => void run('sync', syncRing, 'Обмен с relay кольца завершён.')} />
          </Panel>
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  panel: { gap: spacing.md },
  caption: { fontSize: 13, lineHeight: 18 },
  member: { gap: 2, paddingBottom: spacing.sm, borderBottomWidth: StyleSheet.hairlineWidth },
  memberName: { fontSize: 15, fontWeight: '600' },
});
