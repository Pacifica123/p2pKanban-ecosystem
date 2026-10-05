import { it, expect } from 'vitest';
import { markdown, insertMarkdown } from '../../shared/markdown/model';
import { orderCards } from '../../shared/lib/cardOrder';
it('renders Markdown vocabulary', () => {
  const html = markdown.render(
    '# H\n\n**bold** *italic* ~~gone~~\n\n- one\n\n1. first\n\n> quote\n\n`inline`\n\n```js\ncode\n```\n\n[link](https://example.org)',
  );
  for (const tag of [
    '<h1>',
    '<strong>',
    '<em>',
    '<s>',
    '<ul>',
    '<ol>',
    '<blockquote>',
    '<code>',
    '<pre>',
    '<a href=',
  ])
    expect(html).toContain(tag);
});
it('blocks HTML, unsafe links and remote images', () => {
  expect(
    markdown.render(
      '<script>alert(1)</script>\n[x](javascript:alert(1))\n![x](https://example.org/x)',
    ),
  ).not.toMatch(/<script|href="javascript|<img/);
});
it('preserves unselected source whitespace', () =>
  expect(insertMarkdown('  one\ntwo  ', 2, 5, '**', '**').value).toBe(
    '  **one**\ntwo  ',
  ));
it('priority sort preserves manual order', () => {
  const cards = [
    { id: 'a', position: 1, priority: 'low' },
    { id: 'b', position: 2, priority: 'urgent' },
    { id: 'c', position: 3, priority: 'urgent' },
  ];
  expect(orderCards(cards, true).map((c) => c.id)).toEqual(['b', 'c', 'a']);
  expect(orderCards(cards, false)).toEqual(cards);
  expect(cards.map((c) => c.position)).toEqual([1, 2, 3]);
});
