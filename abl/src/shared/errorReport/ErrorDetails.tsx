import { useState } from 'react';
import { collectReport } from './collect';
import { renderReport } from './report';

/** Copy text: the async clipboard first, then execCommand, else leave it for manual selection. */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* the WebView may refuse; fall through */ }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  let copied = false;
  try { copied = document.execCommand('copy'); } catch { copied = false; }
  area.remove();
  return copied;
}

/** «Скопировать подробности» for the error banner (contracts/error-report/1). */
export function ErrorDetails({ message, error }: { message: string; error?: unknown }) {
  const [text, setText] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean | null>(null);
  async function copy() {
    const next = renderReport(collectReport({ message, error }));
    setText(next);
    setCopied(await copyText(next));
  }
  return (
    <div className="error-details">
      <button type="button" onClick={() => void copy()}>Скопировать подробности</button>
      {copied === true ? <span role="status"> Скопировано: вставьте в сообщение.</span> : null}
      {copied === false && text ? (
        <>
          <span role="status"> WebView не дал скопировать: выделите текст ниже.</span>
          <textarea className="error-details__text" readOnly value={text} rows={8} onFocus={(e) => e.currentTarget.select()} />
        </>
      ) : null}
    </div>
  );
}
