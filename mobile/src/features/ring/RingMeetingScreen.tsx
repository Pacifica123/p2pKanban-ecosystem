import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useEffect, useRef, useState } from 'react';
import { StyleSheet, Switch, Text, View } from 'react-native';

import type { RootStackParamList } from '../../app/navigation/types';
import { spacing, useAppColors } from '../../app/theme';
import { trace } from '../../shared/errorReport/journal';
import { Button, InlineNotice, Panel, Screen, ScreenHeader, StateView } from '../../shared/ui/primitives';
import {
  beginMeeting, declineMeeting, joinerPoll, sayHello, sponsorAwaitAck, sponsorConfirm, sponsorPoll,
  type Meeting, type MeetingStep,
} from './service';

type Props = NativeStackScreenProps<RootStackParamList, 'RingMeeting'>;

export const POLL_MS = 2500;
const KIND_TEXT: Record<string, string> = { web: 'веб-узел', android: 'телефон', arch: 'ПК Arch' };
export const REFUSAL_TEXT: Record<string, string> = {
  declined: 'добавление отклонили',
  expired: 'срок QR истёк — покажите новый код',
  contested: 'в почтовый ящик пришли два разных устройства — покажите новый код',
  'session-used': 'этот QR уже использован',
  'ring-merge-unsupported': 'устройство уже в другом кольце с другими участниками; слияние колец пока не поддерживается',
  'key-removed': 'ключ этого устройства удалён из кольца',
  'sponsor-not-admin': 'добавлять устройства может только admin кольца',
  'sponsor-stale': 'журнал или связка поручителя отстают — синхронизируйте кольцо и повторите',
  'joiner-outdated': 'входящему устройству нужна новая версия приложения',
  'welcome-invalid': 'ответ поручителя не прошёл проверку',
};
const message = (error: unknown) => (error instanceof Error ? error.message : String(error));
const terminal = (step: MeetingStep | null) => step?.step === 'done' || step?.step === 'refused';

export function RingMeetingScreen({ navigation, route }: Props) {
  const colors = useAppColors();
  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [step, setStep] = useState<MeetingStep | null>(null);
  const [code, setCode] = useState<string | null>(null);
  const [joiner, setJoiner] = useState<{ publicKey: string; name: string; kind: string } | null>(null);
  const [memberOnly, setMemberOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const inFlight = useRef(false);

  // Read the QR; a joiner says hello at once.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const opened = await beginMeeting(route.params.qrText);
        if (!alive) return;
        setMeeting(opened);
        trace('ring', () => `встреча ${opened.session.slice(0, 8)}: телефон — ${opened.role === 'joiner' ? 'входящий' : 'поручитель'}`);
        if (opened.role === 'joiner') setCode(await sayHello(opened));
        if (alive) setStep({ step: 'waiting' });
      } catch (error) {
        if (alive) setFailure(error);
      }
    })();
    return () => { alive = false; };
  }, [route.params.qrText]);

  // Poll the mailbox while something is expected from the other side.
  useEffect(() => {
    if (!meeting || !step || terminal(step) || step.step === 'confirm') return;
    const timer = setInterval(() => {
      if (inFlight.current) return;
      inFlight.current = true;
      const poll = meeting.role === 'joiner' ? joinerPoll(meeting)
        : step.step === 'welcomed' && joiner ? sponsorAwaitAck(meeting, joiner.publicKey) : sponsorPoll(meeting);
      poll.then(next => {
        if (next.step === 'confirm') {
          setCode(next.code);
          setJoiner(next.hello.device);
        }
        if (next.step !== step.step) setStep(next);
      }).catch(error => trace('ring', () => `опрос встречи: ${message(error)}`))
        .finally(() => { inFlight.current = false; });
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [meeting, step, joiner]);

  async function act(action: () => Promise<MeetingStep>) {
    setBusy(true);
    try { setStep(await action()); }
    catch (error) { setFailure(error); }
    finally { setBusy(false); }
  }

  const header = (
    <ScreenHeader title="Встреча по QR" subtitle={meeting ? (meeting.role === 'joiner' ? 'телефон входит в кольцо' : 'телефон добавляет устройство') : undefined}
      onBack={() => navigation.goBack()} />
  );
  if (failure && !step) {
    return (
      <Screen scroll>
        {header}
        <StateView title="QR не открылся" description={message(failure)} failed error={failure}
          action={<Button label="Сканировать снова" onPress={() => navigation.replace('RingScan')} />} />
      </Screen>
    );
  }
  if (!meeting || !step) {
    return <Screen>{header}<StateView title="Открываем встречу" busy /></Screen>;
  }
  const peer = meeting.qr.n;
  const peerKind = KIND_TEXT[meeting.qr.t] ?? meeting.qr.t;
  const codeView = code ? <Text style={[styles.code, { color: colors.text }]} accessibilityLabel={`Код ${code}`}>{code}</Text> : null;

  return (
    <Screen scroll>
      {header}
      {failure ? <InlineNotice tone="danger" text={message(failure)} error={failure} /> : null}
      <Panel style={styles.panel}>
        <Text style={[styles.caption, { color: colors.muted }]}>
          {meeting.role === 'joiner' ? 'Входим в кольцо' : 'Добавляем в кольцо'} устройства «{peer}» ({peerKind}).
        </Text>

        {step.step === 'waiting' && meeting.role === 'joiner' ? (
          <>
            <Text style={{ color: colors.text }}>Сверьте код с экраном «{peer}» и подтвердите там:</Text>
            {codeView}
            <StateView title="Ждём подтверждения" busy />
          </>
        ) : null}

        {step.step === 'waiting' && meeting.role === 'sponsor' ? <StateView title={`Ждём «${peer}»`} busy /> : null}

        {step.step === 'confirm' ? (
          <>
            <Text style={{ color: colors.text }}>
              {step.alreadyMember ? 'Переподключение участника кольца' : 'Просит войти в кольцо'}: «{joiner?.name}» ({KIND_TEXT[joiner?.kind ?? ''] ?? joiner?.kind}).
              Код на экране «{peer}» должен быть:
            </Text>
            {codeView}
            {!step.alreadyMember ? (
              <View style={styles.row}>
                <Switch value={memberOnly} onValueChange={setMemberOnly} accessibilityLabel="Только участник" />
                <Text style={[styles.caption, styles.flex, { color: colors.muted }]}>
                  Только участник: чужое или временное устройство, не сможет добавлять другие
                </Text>
              </View>
            ) : null}
            <Button label={step.alreadyMember ? 'Код совпадает — переподключить' : 'Код совпадает — принять'} variant="primary" loading={busy}
              onPress={() => void act(() => sponsorConfirm(meeting, step.hello, memberOnly ? 'member' : 'admin'))} />
            <Button label="Код не совпадает — отклонить" variant="danger" disabled={busy} onPress={() => void act(() => declineMeeting(meeting))} />
          </>
        ) : null}

        {step.step === 'welcomed' ? <StateView title={`Кольцо отправлено «${joiner?.name ?? peer}», ждём ответа`} busy /> : null}

        {step.step === 'done' ? (
          <InlineNotice tone="success" text={meeting.role === 'joiner'
            ? `Готово: телефон в кольце «${step.peerName}», устройств: ${step.members}. Доски из связки ставятся сами.`
            : `Готово: «${step.peerName}» в кольце, устройств: ${step.members}.`} />
        ) : null}

        {step.step === 'refused' ? (
          <InlineNotice tone="danger" text={`Встреча остановлена${step.by === 'peer' ? ' другой стороной' : ''}: ${REFUSAL_TEXT[step.refusal.reason] ?? step.refusal.reason}${step.refusal.detail ? `. ${step.refusal.detail}` : ''}`} />
        ) : null}

        {terminal(step) ? (
          <Button label="К кольцу" variant="primary" onPress={() => navigation.navigate('Ring')} />
        ) : step.step !== 'confirm' ? (
          <Button label="Отменить" disabled={busy} onPress={() => void act(() => declineMeeting(meeting))} />
        ) : null}
      </Panel>
    </Screen>
  );
}

const styles = StyleSheet.create({
  panel: { gap: spacing.md },
  caption: { fontSize: 13, lineHeight: 18 },
  code: { fontSize: 36, fontWeight: '700', letterSpacing: 4, textAlign: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  flex: { flex: 1 },
});
