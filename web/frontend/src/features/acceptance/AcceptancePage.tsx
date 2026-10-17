import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { webSoftware } from '@/shared/errorReport/collect';
import { logLine } from '@/shared/errorReport/journal';
import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { copyText } from '@/shared/ui/ErrorDetails';
import { Panel } from '@/shared/ui/Panel';
import {
  buildAcceptanceReport, renderAcceptanceMarkdown, reportFileName, type AcceptanceReport, type StepResult, type StepStatus,
} from './report';
import { runSteps } from './runner';
import { CROSS_BOARD, newWebContext, TEST_WORKSPACE, WEB_REMAINING, webSteps } from './webSteps';

const TONE: Record<StepStatus, string> = { PASS: 'done', WARN: 'warning', FAIL: 'high', SKIP: 'guest', INFO: 'default' };

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** «Настройки → Проверка приёмки»: docs/ecosystem/self-acceptance.md, уровень C. */
export function AcceptancePage() {
  const cache = useQueryClient();
  const steps = useRef(webSteps()).current;
  const [results, setResults] = useState<StepResult[]>([]);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<AcceptanceReport | null>(null);
  const [copied, setCopied] = useState<boolean | null>(null);
  const stop = useRef<AbortController | null>(null);

  async function start() {
    if (running) return;
    const controller = new AbortController();
    stop.current = controller;
    setRunning(true);
    setResults([]);
    setReport(null);
    setCopied(null);
    const ctx = newWebContext();
    const startedAt = new Date().toISOString();
    logLine('info', 'acceptance', `проверка приёмки ${ctx.runId} начата`);
    const done = await runSteps(steps, ctx, {
      signal: controller.signal,
      onStep: (result) => {
        logLine(result.status === 'FAIL' ? 'warn' : 'info', 'acceptance', `${result.id}: ${result.status}`);
        setResults((current) => [...current, result]);
      },
    });
    setReport(buildAcceptanceReport({
      runId: ctx.runId, startedAt, finishedAt: new Date().toISOString(), software: webSoftware(),
      platform: navigator.userAgent, node: ctx.node, steps: done, remaining: WEB_REMAINING,
    }));
    setRunning(false);
    // Test boards came and went: the sidebar and lists should not show stale data.
    void cache.invalidateQueries();
  }

  async function copy() {
    if (report) setCopied(await copyText(renderAcceptanceMarkdown(report)));
  }

  const summary = report?.summary;
  return <div className="page-shell">
    <header className="page-header"><h2>Проверка приёмки</h2></header>
    <Panel title="Что делает кнопка"
      description="Отладочная проверка: выполняет то, что сделал бы человек, на этом узле и под этим аккаунтом, и собирает отчёт.">
      <p>Создаёт (или находит) личное пространство «{TEST_WORKSPACE}», доску прогона и проходит по ней карточки,
        чек-листы, комментарии, метки, экспорт и импорт копией. На «{CROSS_BOARD}» оставляет карточку для Android и
        отмечает пункт на карточке Android. Проверяет лимит опроса подключения, подробности ошибки, кольцо устройств,
        канал обновления и темы. В конце доска прогона удаляется.</p>
      <p className="muted">Ваши доски не трогаются. Кольцо не создаётся, сеансы не завершаются, узел не обновляется.</p>
      <div className="toolbar">
        <Button variant="primary" disabled={running} onClick={() => void start()} data-testid="acceptance-start">
          {running ? 'Проверяем…' : 'Запустить проверку'}</Button>
        {running && <Button variant="ghost" onClick={() => stop.current?.abort()}>Остановить</Button>}
      </div>
    </Panel>
    {results.length > 0 && <Panel title={summary ? `Итог: ${summary.verdict}` : `Шагов пройдено: ${results.length} из ${steps.length}`}
      description={summary ? `PASS ${summary.PASS} · WARN ${summary.WARN} · FAIL ${summary.FAIL} · SKIP ${summary.SKIP} · INFO ${summary.INFO}` : undefined}
      actions={report ? <div className="toolbar">
        <Button onClick={() => void copy()} data-testid="acceptance-copy">Скопировать отчёт</Button>
        <Button variant="ghost" onClick={() => download(reportFileName(report), renderAcceptanceMarkdown(report))}>Сохранить .md</Button>
      </div> : undefined}>
      {copied === true && <p role="status" className="muted">Отчёт скопирован: вставьте его в сообщение.</p>}
      {copied === false && <p role="status" className="muted">Браузер не дал скопировать: сохраните .md или выделите текст ниже.</p>}
      <ol className="acceptance-steps" data-testid="acceptance-steps">
        {results.map((step) => <li key={step.id}>
          <Badge tone={TONE[step.status]}>{step.status}</Badge> <strong>{step.title}</strong>
          <span className="muted"> · {step.phase}{step.covers.length ? ` · ${step.covers.join(', ')}` : ''}</span>
          {step.detail && <div className="muted" style={{ overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{step.detail}</div>}
        </li>)}
      </ol>
      {report && <details>
        <summary>Текст отчёта</summary>
        <textarea readOnly rows={14} style={{ width: '100%', fontFamily: 'monospace' }} value={renderAcceptanceMarkdown(report)} />
      </details>}
    </Panel>}
  </div>;
}
