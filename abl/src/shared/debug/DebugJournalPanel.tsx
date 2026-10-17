import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { ablSoftware } from '../errorReport/collect';
import { copyText } from '../errorReport/ErrorDetails';
import { journalEntries, platformText, subscribeJournal, type JournalEntry } from '../errorReport/journal';
import { redact } from '../errorReport/report';
import { previousRunLines, setDebugMode, useDebugMode } from './debugMode';
import { renderDebugJournal } from './export';

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

/** «Журнал отладки»: the WebView journal live, without secrets, copied as Markdown. */
export function DebugJournalPanel({ onClose }: { onClose: () => void }) {
  const debugMode = useDebugMode();
  const [paused, setPaused] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const [source, setSource] = useState<Source>('now');
  const [fallback, setFallback] = useState<string | null>(null);
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

  async function copy() {
    const text = renderDebugJournal({
      software: ablSoftware(),
      platform: platformText() || null,
      exportedAt: new Date().toISOString(),
      lines: journalEntries().map((entry) => entry.line),
      previous,
      debugMode,
    }).text;
    if (await copyText(text)) {
      setFallback(null);
      setNotice('Журнал скопирован в Markdown: вставьте в сообщение или в файл .md.');
    } else {
      setFallback(text);
      setNotice('WebView не дал скопировать: выделите текст ниже.');
    }
  }

  const choice = (active: boolean) => (active ? 'debug-journal__choice is-active' : 'debug-journal__choice');

  return (
    <section className="debug-journal" aria-label="Журнал отладки">
      <div className="debug-journal__head">
        <strong>Журнал отладки</strong>
        <span>
          {debugMode
            ? 'Режим включён до закрытия приложения: подробные шаги, 5000 строк.'
            : 'Режим выключен: только вызовы desktop API и ошибки, последние 200 строк.'}
          {' '}Секреты вырезаются, тексты карточек не пишутся. После перезапуска журнал начинается заново.
        </span>
        <button type="button" onClick={onClose}>Закрыть</button>
      </div>
      <div className="debug-journal__controls">
        <button type="button" onClick={() => setDebugMode(!debugMode)}>
          {debugMode ? 'Выключить режим отладки' : 'Включить режим отладки'}
        </button>
        <button type="button" className={choice(source === 'now')} onClick={() => setSource('now')}>Этот запуск</button>
        {previous.length ? <button type="button" className={choice(source === 'previous')} onClick={() => setSource('previous')}>Прошлый запуск</button> : null}
        <button type="button" className={choice(filter === 'all')} onClick={() => setFilter('all')}>Всё</button>
        <button type="button" className={choice(filter === 'problems')} onClick={() => setFilter('problems')}>Ошибки</button>
        {source === 'now' ? <button type="button" className={choice(paused)} onClick={() => setPaused(!paused)}>{paused ? 'Продолжить' : 'Пауза'}</button> : null}
        <button type="button" onClick={() => void copy()}>Скопировать .md</button>
        <span>{lines.length} строк</span>
      </div>
      <pre ref={listRef} className="debug-journal__lines">
        {lines.length ? lines.map((line, index) => <div key={index} className={levelClass(line)}>{line}</div>) : 'Строк пока нет.'}
      </pre>
      {notice ? <span role="status">{notice}</span> : null}
      {fallback ? <textarea className="error-details__text" readOnly value={fallback} rows={10} onFocus={(e) => e.currentTarget.select()} /> : null}
    </section>
  );
}
