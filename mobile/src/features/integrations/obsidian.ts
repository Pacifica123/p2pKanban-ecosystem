import { Alert, Linking } from 'react-native';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';
import type { Card } from '../../shared/types/api';
export function cardMarkdown(
  c: Pick<Card, 'id' | 'title' | 'description' | 'priority'>,
) {
  return `# ${c.title.replace(/[\r\n]/g, ' ')}\n\n${c.description || ''}\n\n---\np2pKanban card: ${c.id}\nPriority: ${c.priority || 'none'}\n`;
}
export function cardMarkdownFilename(c: Pick<Card, 'id' | 'title'>) {
  return `${c.title.replace(/[\/\\:*?"<>|\u0000-\u001f]/g, '-').slice(0, 70) || 'card'}-${c.id.slice(0, 8)}.md`;
}
export async function shareCardMarkdown(c: Card) {
  const file = new File(Paths.cache, cardMarkdownFilename(c));
  file.write(cardMarkdown(c));
  await Sharing.shareAsync(file.uri, {
    mimeType: 'text/markdown',
    dialogTitle: 'Экспорт карточки в Markdown',
  });
}
export async function openCardInObsidian(c: Card) {
  const content = cardMarkdown(c);
  if (content.length > 12000) {
    await shareCardMarkdown(c);
    return;
  }
  await new Promise<void>((resolve, reject) =>
    Alert.alert(
      'Создать заметку в Obsidian?',
      'Будут переданы название и Markdown карточки. Дальнейшей синхронизации нет.',
      [
        { text: 'Отмена', style: 'cancel', onPress: () => resolve() },
        {
          text: 'Открыть',
          onPress: () => {
            void Linking.openURL(
              `obsidian://new?name=${encodeURIComponent(cardMarkdownFilename(c).replace(/\.md$/, ''))}&content=${encodeURIComponent(content)}`,
            )
              .then(() => resolve())
              .catch(() => shareCardMarkdown(c).then(resolve, reject));
          },
        },
      ],
      { cancelable: true, onDismiss: () => resolve() },
    ),
  );
}
