import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { previousRunLines, setDebugMode, useDebugMode } from '@/shared/debug/debugMode';
import { debugJournalFilename, renderDebugJournal } from '@/shared/debug/export';
import { webSoftware } from '@/shared/errorReport/collect';
import { journalEntries, subscribeJournal, type JournalEntry } from '@/shared/errorReport/journal';
import { redact } from '@/shared/errorReport/report';
import { Button } from '@/shared/ui/Button';
import { copyText } from '@/shared/ui/ErrorDetails';

type Filter = 'all' | 'problems';
type Source = 'now' | 'previous';

const REDRAW_MS = 300;

function useJournal(paused: boolean) {
  const [entries, setEntries] = useState<JournalEntry[]>(journalEntries);
  useEffect(() => {
    if (paused) return undefined;
    setEntries(journalEntries());
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = subscribeJournal(() => {
      if (timer) return;
      timer = setTimeout(() => { timer = null; setEntries(journalEntries()); }, REDRAW_MS);
    });
    return () => { unsubscribe(); if (timer) clearTimeout(timer); };
  }, [paused]);
  return entries;
}

function levelClass(line: string) {
  return / error /.test(line) ? 'debug-journal__line--error' : / warn /.test(line) ? 'debug-journal__line--warn' : '';
}

/** «Журнал отладки»: the client journal live, without secrets, with a Markdown export. */
export function DebugJournalPage() {
  const debugMode = useDebugMode();
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const [source, setSource] = useState<Source>('now');
  const [notice, setNotice] = useState<string | null>(null);
  const entries = useJournal(paused);
  const listRef = useRef<HTMLPreElement>(null);
  const previous = previousRunLines();

  const lines = useMemo(() => {
    if (source === 'previous') return filter === 'all' ? previous : previous.filter((line) => / (warn|error) /.test(line));
    const shown = filter === 'all' ? entries : entries.filter((entry) => entry.level === 'warn' || entry.level === 'error');
    return shown.map((entry) => redact(entry.line)[0]);
  }, [entries, filter, previous, source]);

  useLayoutEffect(() => {
    if (!paused && source === 'now' && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [lines, paused, source]);

  function exportText() {
    return renderDebugJournal({
      software: webSoftware(),
      platform: navigator.userAgent,
      exportedAt: new Date().toISOString(),
      lines: journalEntries().map((entry) => entry.line),
      previous,
      debugMode,
    }).text;
  }

  async function copy() {
    setNotice(await copyText(exportText())
      ? 'Журнал скопирован в Markdown: вставьте в сообщение.'
      : 'Браузер не дал скопировать: используйте «Сохранить .md».');
  }

  function download() {
    const url = URL.createObjectURL(new Blob([exportText()], { type: 'text/markdown' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = debugJournalFilename('web', new Date().toISOString());
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setNotice(null);
  }

  return <div className="page-shell debug-journal" data-testid="debug-journal">
    <header className="page-header">
      <h2>Журнал отладки</h2>
      <p className="muted">
        {debugMode
          ? 'Режим отладки включён: журнал пишет смену страниц и подробные шаги, хранит 5000 строк и переживает перезагрузку страницы.'
          : 'Режим выключен: здесь только запросы к узлу и ошибки, последние 200 строк.'}
        {' '}Пароли, токены и ключи вырезаются, тексты карточек в журнал не пишутся. Журнал узла — в bootstrap.py logs.
      </p>
    </header>
    <div className="debug-journal__controls">
      <Button variant={debugMode ? 'default' : 'primary'} onClick={() => setDebugMode(!debugMode)} data-testid="debug-mode-toggle">
        {debugMode ? 'Выключить режим отладки' : 'Включить режим отладки'}
      </Button>
      <Button variant={source === 'now' ? 'primary' : 'ghost'} onClick={() => setSource('now')}>Эта загрузка</Button>
      {previous.length ? <Button variant={source === 'previous' ? 'primary' : 'ghost'} onClick={() => setSource('previous')}>Прошлая загрузка</Button> : null}
      <Button variant={filter === 'all' ? 'primary' : 'ghost'} onClick={() => setFilter('all')}>Всё</Button>
      <Button variant={filter === 'problems' ? 'primary' : 'ghost'} onClick={() => setFilter('problems')}>Ошибки</Button>
      {source === 'now' ? <Button variant={paused ? 'primary' : 'ghost'} onClick={() => setPaused(!paused)}>{paused ? 'Продолжить' : 'Пауза'}</Button> : null}
      <span className="muted">{lines.length} строк</span>
    </div>
    <pre ref={listRef} className="debug-journal__lines" data-testid="debug-journal-lines">
      {lines.length ? lines.map((line, index) => <div key={index} className={levelClass(line)}>{line}</div>) : <span className="muted">Строк пока нет.</span>}
    </pre>
    <div className="debug-journal__controls">
      <Button onClick={() => void copy()}>Скопировать</Button>
      <Button onClick={download}>Сохранить .md</Button>
      {notice ? <span role="status" className="muted">{notice}</span> : null}
    </div>
  </div>;
}
