import { useRef, useState } from 'react';
import { markdown, markdownActions, insertMarkdown } from './model';
export function MarkdownView({ source }: { source: string }) {
  return (
    <div
      className="markdown-view"
      dangerouslySetInnerHTML={{ __html: markdown.render(source) }}
    />
  );
}
export function MarkdownEditor({
  value,
  onChange,
  readOnly = false,
}: {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  const [preview, setPreview] = useState(false);
  return (
    <div className="markdown-editor">
      <div className="toolbar">
        <strong>Описание · Markdown</strong>
        {!readOnly && (
          <button type="button" onClick={() => setPreview(!preview)}>
            {preview ? 'Редактировать' : 'Предпросмотр'}
          </button>
        )}
      </div>
      {readOnly || preview ? (
        <MarkdownView source={value} />
      ) : (
        <>
          <div className="toolbar" aria-label="Форматирование Markdown">
            {markdownActions.map(([label, before, after]) => (
              <button
                type="button"
                key={label}
                aria-label={`Markdown ${label}`}
                onClick={() => {
                  const el = input.current;
                  if (!el) return;
                  const next = insertMarkdown(
                    value,
                    el.selectionStart,
                    el.selectionEnd,
                    before,
                    after,
                  );
                  onChange(next.value);
                  requestAnimationFrame(() => {
                    el.focus();
                    el.setSelectionRange(next.start, next.end);
                  });
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <textarea
            ref={input}
            aria-label="Описание · Markdown source"
            className="field__textarea"
            rows={7}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        </>
      )}
    </div>
  );
}
