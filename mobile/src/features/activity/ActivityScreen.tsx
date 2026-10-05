import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useQuery } from '@tanstack/react-query';
import { StyleSheet, Text, View } from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import type { RootStackParamList } from '../../app/navigation/types';
import { radius, spacing, useAppColors } from '../../app/theme';
import { getCommonBoardActivity } from './replicatedActivity';
import { activityLabel, changedFieldsLabel } from '../../shared/lib/russian';
import {
  Button,
  InlineNotice,
  Screen,
  ScreenHeader,
  StateView,
} from '../../shared/ui/primitives';

type Props = NativeStackScreenProps<RootStackParamList, 'Activity'>;

function dateTime(value: string) {
  try {
    return new Intl.DateTimeFormat('ru-RU', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function ActivityScreen({ navigation, route }: Props) {
  const { boardId, boardName } = route.params;
  const colors = useAppColors();
  const { isOnline } = useNetwork();
  const query = useQuery({
    queryKey: ['activity', boardId],
    queryFn: () => getCommonBoardActivity(boardId,isOnline),
    refetchInterval: isOnline ? 15_000 : false,
  });

  return (
    <Screen scroll>
      <ScreenHeader title="История" subtitle={boardName} onBack={() => navigation.goBack()} />
      {!isOnline ? (
        <InlineNotice text="Показана сохранённая общая история доски." tone="warning" />
      ) : null}
      {query.data?.stale && isOnline ? <InlineNotice text="Реле недоступны; показана сохранённая общая история." tone="warning" /> : null}
      {query.isPending ? <StateView title="Загружаем историю" busy /> : null}
      {query.isError ? (
        <StateView
          title="История недоступна"
          description={query.error instanceof Error ? query.error.message : undefined}
          action={<Button label="Повторить" onPress={() => void query.refetch()} />}
        />
      ) : null}
      {query.data && !query.data.items.length ? (
        <StateView title="История пока пустая" />
      ) : null}
      <View style={styles.list}>
        {query.data?.items.map((entry) => {
          const changedFields = changedFieldsLabel(entry.fieldMask);
          return (
            <View
              key={entry.id}
              style={[
                styles.entry,
                { backgroundColor: colors.surface, borderColor: colors.border },
              ]}
            >
              <Text style={[styles.entryTitle, { color: colors.text }]}>
                {activityLabel(entry.kind)}
              </Text>
              <Text style={[styles.entryMeta, { color: colors.muted }]}>
                {entry.actor.displayName || 'Система'} · {dateTime(entry.createdAt)}
              </Text>
              {changedFields ? (
                <Text style={[styles.entryFields, { color: colors.muted }]}>
                  Изменено: {changedFields}
                </Text>
              ) : null}
            </View>
          );
        })}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  list: {
    gap: spacing.sm,
  },
  entry: {
    gap: spacing.xs,
    borderWidth: 1,
    borderRadius: radius.sm,
    padding: spacing.md,
  },
  entryTitle: {
    fontSize: 15,
    fontWeight: '700',
  },
  entryMeta: {
    fontSize: 12,
  },
  entryFields: {
    fontSize: 12,
    lineHeight: 17,
  },
});
