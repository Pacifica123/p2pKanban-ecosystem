import MarkdownIt from 'markdown-it';
export const markdown = new MarkdownIt({
  html: false,
  linkify: false,
  breaks: true,
}).disable(['image']);
export const safeMarkdownLink = (href: string) =>
  /^(https?:\/\/|mailto:)/i.test(href) && !/[\u0000-\u0020]/.test(href);
markdown.validateLink = safeMarkdownLink;
export const markdownActions = [
  ['H', '## ', ''],
  ['B', '**', '**'],
  ['I', '*', '*'],
  ['S', '~~', '~~'],
  ['•', '- ', ''],
  ['1.', '1. ', ''],
  ['❝', '> ', ''],
  ['`', '`', '`'],
  ['```', '\n```\n', '\n```\n'],
  ['↗', '[', '](https://example.org)'],
] as const;
export function insertMarkdown(
  source: string,
  start: number,
  end: number,
  before: string,
  after: string,
) {
  const prefix =
    /^(## |-|1\. |> )/.test(before) && start > 0 && source[start - 1] !== '\n'
      ? '\n'
      : '';
  const selected = source.slice(start, end) || 'текст';
  return {
    value:
      source.slice(0, start) +
      prefix +
      before +
      selected +
      after +
      source.slice(end),
    start: start + prefix.length + before.length,
    end: start + prefix.length + before.length + selected.length,
  };
}
