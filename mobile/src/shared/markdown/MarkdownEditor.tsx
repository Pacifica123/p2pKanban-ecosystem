import { useRef, useState, type ReactNode } from 'react';
import {
  Linking,
  Pressable,
  Text,
  TextInput,
  View,
  type TextStyle,
} from 'react-native';
import type Token from 'markdown-it/lib/token.mjs';
import { useAppColors } from '../../app/theme';
import {
  markdown,
  markdownActions,
  insertMarkdown,
  safeMarkdownLink,
} from './model';
export function MarkdownView({ source }: { source: string }) {
  const colors = useAppColors();
  function inline(tokens: Token[]): ReactNode[] {
    const styles: TextStyle[] = [];
    let href: string | undefined;
    return tokens.map((t, i) => {
      if (t.type === 'link_open') {
        href = t.attrGet('href') || undefined;
        return null;
      }
      if (t.type === 'link_close') {
        href = undefined;
        return null;
      }
      if (t.nesting === 1) {
        styles.push(
          t.type === 'strong_open'
            ? { fontWeight: '700' }
            : t.type === 'em_open'
              ? { fontStyle: 'italic' }
              : t.type === 's_open'
                ? { textDecorationLine: 'line-through' }
                : {},
        );
        return null;
      }
      if (t.nesting === -1) {
        styles.pop();
        return null;
      }
      const link = href;
      return (
        <Text
          key={i}
          accessibilityRole={link ? 'link' : undefined}
          onPress={
            link && safeMarkdownLink(link)
              ? () => {
                  void Linking.openURL(link).catch(() => undefined);
                }
              : undefined
          }
          style={[
            ...styles,
            t.type === 'code_inline'
              ? {
                  fontFamily: 'monospace',
                  backgroundColor: colors.surfaceMuted,
                }
              : {},
            link
              ? { color: colors.accent, textDecorationLine: 'underline' }
              : {},
          ]}
        >
          {t.type === 'softbreak' || t.type === 'hardbreak' ? '\n' : t.content}
        </Text>
      );
    });
  }
  let heading = 0,
    quote = 0,
    marker = '';
  const lists: Array<{ ordered: boolean; count: number }> = [];
  return (
    <View style={{ gap: 6 }}>
      {markdown.parse(source, {}).map((t, i) => {
        if (t.type === 'heading_open') heading = Number(t.tag.slice(1));
        if (t.type === 'heading_close') heading = 0;
        if (t.type === 'blockquote_open') quote++;
        if (t.type === 'blockquote_close') quote--;
        if (t.type === 'bullet_list_open' || t.type === 'ordered_list_open')
          lists.push({
            ordered: t.type === 'ordered_list_open',
            count: Number(t.attrGet('start') || 1),
          });
        if (t.type === 'bullet_list_close' || t.type === 'ordered_list_close')
          lists.pop();
        if (t.type === 'list_item_open') {
          const l = lists[lists.length - 1];
          marker = l?.ordered ? `${l.count++}. ` : '• ';
        }
        if (t.type === 'inline') {
          const bullet = marker;
          marker = '';
          return (
            <Text
              selectable
              key={i}
              style={{
                color: colors.text,
                fontSize: heading ? 26 - heading * 2 : 15,
                fontWeight: heading ? '700' : '400',
                lineHeight: heading ? 30 : 23,
                marginLeft: lists.length * 12,
                paddingLeft: quote ? 12 : 0,
                borderLeftWidth: quote ? 3 : 0,
                borderColor: colors.accent,
              }}
            >
              {bullet}
              {inline(t.children || [])}
            </Text>
          );
        }
        if (t.type === 'fence' || t.type === 'code_block')
          return (
            <Text
              selectable
              key={i}
              style={{
                color: colors.text,
                fontFamily: 'monospace',
                backgroundColor: colors.surfaceMuted,
                padding: 10,
              }}
            >
              {t.content}
            </Text>
          );
        if (t.type === 'hr')
          return (
            <View
              key={i}
              style={{ borderBottomWidth: 1, borderColor: colors.border }}
            />
          );
        return null;
      })}
    </View>
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
  const colors = useAppColors(),
    input = useRef<TextInput>(null);
  const [preview, setPreview] = useState(false),
    [selection, setSelection] = useState({ start: 0, end: 0 });
  return (
    <View style={{ gap: 8 }}>
      <Text style={{ color: colors.text }}>Описание · Markdown</Text>
      {!readOnly && (
        <Pressable
          accessibilityRole="button"
          onPress={() => setPreview(!preview)}
        >
          <Text style={{ color: colors.accent }}>
            {preview ? 'Редактировать' : 'Предпросмотр'}
          </Text>
        </Pressable>
      )}
      {readOnly || preview ? (
        <MarkdownView source={value} />
      ) : (
        <>
          <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
            {markdownActions.map(([label, before, after]) => (
              <Pressable
                key={label}
                accessibilityRole="button"
                accessibilityLabel={`Markdown ${label}`}
                style={{ padding: 8 }}
                onPress={() => {
                  const next = insertMarkdown(
                    value,
                    selection.start,
                    selection.end,
                    before,
                    after,
                  );
                  onChange(next.value);
                  setSelection({ start: next.start, end: next.end });
                  input.current?.focus();
                }}
              >
                <Text style={{ color: colors.accent }}>{label}</Text>
              </Pressable>
            ))}
          </View>
          <TextInput
            ref={input}
            accessibilityLabel="Описание · Markdown source"
            multiline
            value={value}
            onChangeText={onChange}
            selection={selection}
            onSelectionChange={(e) => setSelection(e.nativeEvent.selection)}
            style={{
              minHeight: 130,
              color: colors.text,
              backgroundColor: colors.surfaceMuted,
              padding: 12,
              textAlignVertical: 'top',
            }}
          />
        </>
      )}
    </View>
  );
}
