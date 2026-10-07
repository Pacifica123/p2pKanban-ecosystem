import { useState } from 'react';
import { collectReport, type ReportContext } from '@/shared/errorReport/collect';
import { renderReport } from '@/shared/errorReport/report';
import { Button } from '@/shared/ui/Button';

/** Copy text even where navigator.clipboard is missing (a node opened over plain http on the LAN). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch { /* fall through to the textarea route */ }
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

/** «Скопировать подробности» under any error the person sees (contracts/error-report/1). */
export function ErrorDetails(props: ReportContext) {
  const [text, setText] = useState<string | null>(null);
  const [copied, setCopied] = useState<boolean | null>(null);
  async function copy() {
    const next = renderReport(collectReport(props));
    setText(next);
    setCopied(await copyText(next));
  }
  return <div className="error-details">
    <Button variant="ghost" onClick={() => void copy()} data-testid="copy-error-details">Скопировать подробности</Button>
    {copied === true && <span role="status" className="muted"> Скопировано: вставьте в сообщение.</span>}
    {copied === false && text && <>
      <span role="status" className="muted"> Браузер не дал скопировать: выделите текст ниже.</span>
      <textarea className="error-details__text" readOnly value={text} rows={8} onFocus={(e) => e.currentTarget.select()} />
    </>}
  </div>;
}
