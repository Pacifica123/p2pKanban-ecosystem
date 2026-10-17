import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import * as Clipboard from 'expo-clipboard';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Platform, StyleSheet, Text, View } from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import type { RootStackParamList } from '../../app/navigation/types';
import { spacing, useAppColors } from '../../app/theme';
import { useUiTheme } from '../../app/UiThemeProvider';
import { mobileSoftware } from '../../shared/errorReport/collect';
import { logLine } from '../../shared/errorReport/journal';
import { Button, InlineNotice, Panel, Screen, ScreenHeader, SectionTitle } from '../../shared/ui/primitives';
import { useAuth } from '../auth/AuthProvider';
import { useConnection } from '../connection/ConnectionProvider';
import { useLocalBoard, type LocalBoardRuntime } from '../localFirst/useLocalBoard';
import { CROSS_BOARD, MOBILE_REMAINING, mobileSteps, newMobileContext, TEST_WORKSPACE, type Prompt } from './mobileSteps';
import {
  buildAcceptanceReport, renderAcceptanceMarkdown, reportFileName, type AcceptanceReport, type StepResult, type StepStatus,
} from './report';
import { runSteps } from './runner';

type Props = NativeStackScreenProps<RootStackParamList, 'Acceptance'>;
type Target = { boardId: string; workspaceId: string };

/** How long the network has to stay as asked before the check goes on. */
const SETTLE_MS = 5000;

/** The board runtime of the board screen, without its UI. */
function BoardHost({ target, onRuntime }: { target: Target; onRuntime: (runtime: LocalBoardRuntime, boardId: string) => void }) {
  const runtime = useLocalBoard(target.boardId, target.workspaceId, 1, true, { active: true });
  useEffect(() => { onRuntime(runtime, target.boardId); });
  return null;
}

function platformLabel() {
  const constants = Platform.constants as { Release?: string; Model?: string } | undefined;
  return `Android ${constants?.Release ?? '?'} (API ${Platform.Version})${constants?.Model ? ` · ${constants.Model}` : ''}`;
}

/** «Настройки → Проверка приёмки»: docs/ecosystem/self-acceptance.md, уровень C. */
export function AcceptanceScreen({ navigation }: Props) {
  const colors = useAppColors();
  const network = useNetwork();
  const auth = useAuth();
  const connection = useConnection();
  const uiTheme = useUiTheme();
  const steps = useRef(mobileSteps()).current;
  const [results, setResults] = useState<StepResult[]>([]);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<AcceptanceReport | null>(null);
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [readySince, setReadySince] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [target, setTarget] = useState<Target | null>(null);

  const networkRef = useRef(network);
  networkRef.current = network;
  const backgroundRef = useRef(colors.background);
  backgroundRef.current = colors.background;
  const themeRef = useRef(uiTheme);
  themeRef.current = uiTheme;
  const runtimeRef = useRef<{ runtime: LocalBoardRuntime; boardId: string } | null>(null);
  const mounted = () => runtimeRef.current;
  const answerRef = useRef<((done: boolean) => void) | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const answer = useCallback((done: boolean) => {
    const resolve = answerRef.current;
    answerRef.current = null;
    setPrompt(null);
    setReadySince(null);
    resolve?.(done);
  }, []);

  // A prompt goes on by itself once the network has stayed as asked for SETTLE_MS.
  useEffect(() => {
    if (!prompt) return;
    let since: number | null = null;
    const timer = setInterval(() => {
      const ready = prompt.ready({ isOnline: networkRef.current.isOnline, type: networkRef.current.networkType });
      since = ready ? since ?? Date.now() : null;
      setReadySince(since);
      if (since !== null && Date.now() - since >= SETTLE_MS) {
        clearInterval(timer);
        answer(true);
      }
    }, 500);
    return () => clearInterval(timer);
  }, [prompt, answer]);

  // Leaving the screen stops the run: nothing keeps working behind the person's back.
  useEffect(() => () => {
    abortRef.current?.abort();
    answerRef.current?.(false);
  }, []);

  async function start() {
    if (running) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setResults([]);
    setReport(null);
    setNotice(null);
    const ctx = newMobileContext({
      nodeOrigin: connection.nodeOrigin,
      user: auth.user ? { id: auth.user.id, email: auth.user.email } : null,
      network: () => ({ isOnline: networkRef.current.isOnline, type: networkRef.current.networkType }),
      ask: (next) => new Promise<boolean>((resolve) => {
        if (controller.signal.aborted) { resolve(false); return; }
        answerRef.current = resolve;
        setReadySince(null);
        setPrompt(next);
      }),
      board: {
        open: async (boardId, workspaceId) => {
          runtimeRef.current = null;
          setTarget({ boardId, workspaceId });
          const deadline = Date.now() + 30_000;
          for (;;) {
            // Read through a function: TypeScript would keep the `null` assigned above.
            const current = mounted();
            if (current?.boardId === boardId && current.runtime.hydrated) return current.runtime;
            if (Date.now() > deadline) throw new Error('доска не открылась за 30 с');
            await new Promise((done) => setTimeout(done, 250));
          }
        },
        current: () => runtimeRef.current?.runtime ?? null,
        close: () => { runtimeRef.current = null; setTarget(null); },
      },
      ui: {
        theme: () => themeRef.current.theme,
        setTheme: (id) => themeRef.current.setTheme(id),
        background: () => backgroundRef.current,
      },
    });
    const startedAt = new Date().toISOString();
    logLine('info', 'acceptance', `проверка приёмки ${ctx.runId} начата`);
    const done = await runSteps(steps, ctx, {
      signal: controller.signal,
      onStep: (result) => {
        logLine(result.status === 'FAIL' ? 'warn' : 'info', 'acceptance', `${result.id}: ${result.status}`);
        setResults((current) => [...current, result]);
      },
    });
    setTarget(null);
    setReport(buildAcceptanceReport({
      runId: ctx.runId, startedAt, finishedAt: new Date().toISOString(), software: mobileSoftware(),
      platform: platformLabel(), node: ctx.node, steps: done, remaining: MOBILE_REMAINING,
    }));
    setRunning(false);
  }

  async function copy() {
    if (!report) return;
    try {
      await Clipboard.setStringAsync(renderAcceptanceMarkdown(report));
      setNotice('Отчёт скопирован: вставьте его в сообщение.');
    } catch {
      setNotice('Не удалось скопировать: поделитесь файлом.');
    }
  }

  async function share() {
    if (!report) return;
    try {
      const file = new File(Paths.cache, reportFileName(report));
      file.write(renderAcceptanceMarkdown(report));
      await Sharing.shareAsync(file.uri, { mimeType: 'text/markdown', dialogTitle: 'Отчёт проверки приёмки' });
    } catch (error) {
      setNotice(`Не удалось поделиться: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  const tone: Record<StepStatus, string> = {
    PASS: colors.success, WARN: colors.warning, FAIL: colors.danger, SKIP: colors.muted, INFO: colors.text,
  };
  const summary = report?.summary;
  const settleLeft = readySince ? Math.max(0, Math.ceil((SETTLE_MS - (Date.now() - readySince)) / 1000)) : null;

  return (
    <Screen scroll>
      <ScreenHeader title="Проверка приёмки" onBack={() => navigation.goBack()} />
      {target ? <BoardHost target={target} onRuntime={(runtime, boardId) => { runtimeRef.current = { runtime, boardId }; }} /> : null}

      <Panel style={styles.panel}>
        <SectionTitle title="Что делает кнопка" />
        <Text style={[styles.body, { color: colors.text }]}>
          Делает то, что сделал бы человек, на этом узле и под этим аккаунтом. Находит или создаёт личное пространство
          «{TEST_WORKSPACE}», две доски прогона и проходит карточки, чек-листы и архив через ту же очередь, что экран доски.
          Оставляет карточку на «{CROSS_BOARD}» для web. Потом попросит выключить Wi-Fi, включить режим полёта и вернуть
          Wi-Fi — и сама увидит, что сеть сменилась.
        </Text>
        <Text style={[styles.caption, { color: colors.muted }]}>
          Начинайте в Wi-Fi той же сети, что узел, и держите экран включённым. Ваши доски не трогаются; в конце доски
          прогона удаляются. Будет одна попытка входа с неверным паролем — так проверяется текст ошибки.
        </Text>
        <Button label={running ? 'Проверяем…' : 'Запустить проверку'} variant="primary" loading={running}
          disabled={running} onPress={() => void start()} />
        {running ? <Button label="Остановить" variant="ghost" onPress={() => { abortRef.current?.abort(); answer(false); }} /> : null}
      </Panel>

      {prompt ? (
        <Panel style={styles.panel}>
          <SectionTitle title={prompt.title} />
          <Text style={[styles.body, { color: colors.text }]}>{prompt.text}</Text>
          <Text style={[styles.caption, { color: colors.muted }]}>
            Сейчас: {network.networkType}{network.isOnline ? '' : ', нет связи'}
            {settleLeft !== null ? ` · продолжим через ${settleLeft} с` : ''}
          </Text>
          <Button label="Пропустить эту фазу" variant="ghost" onPress={() => answer(false)} />
        </Panel>
      ) : null}

      {results.length ? (
        <Panel style={styles.panel}>
          <SectionTitle title={summary ? `Итог: ${summary.verdict}` : `Шагов: ${results.length} из ${steps.length}`} />
          {summary ? (
            <Text style={[styles.caption, { color: colors.muted }]}>
              PASS {summary.PASS} · WARN {summary.WARN} · FAIL {summary.FAIL} · SKIP {summary.SKIP} · INFO {summary.INFO}
            </Text>
          ) : null}
          {results.map((step) => (
            <View key={step.id} style={styles.step}>
              <Text style={[styles.stepTitle, { color: colors.text }]}>
                <Text style={{ color: tone[step.status] }}>{step.status}</Text> {step.title}
              </Text>
              {step.detail ? <Text style={[styles.caption, { color: colors.muted }]} selectable>{step.detail}</Text> : null}
            </View>
          ))}
          {report ? (
            <>
              <Button label="Скопировать отчёт" onPress={() => void copy()} />
              <Button label="Поделиться файлом .md" variant="ghost" onPress={() => void share()} />
            </>
          ) : null}
          {notice ? <InlineNotice text={notice} /> : null}
        </Panel>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  panel: { gap: spacing.md },
  body: { fontSize: 14, lineHeight: 20 },
  caption: { fontSize: 13, lineHeight: 19 },
  step: { gap: spacing.xs },
  stepTitle: { fontSize: 14, fontWeight: '700' },
});
