import {DeviceLinkPanel} from '../deviceLink/DeviceLinkPanel';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { useNetwork } from '../../app/NetworkProvider';
import type { RootStackParamList } from '../../app/navigation/types';
import { spacing, useAppColors } from '../../app/theme';
import type { Density } from '../../shared/types/api';
import { useUiTheme } from '../../app/UiThemeProvider';
import { UI_THEMES } from '../../app/uiThemes';
import {
  Button,
  ErrorDetails,
  InlineNotice,
  Panel,
  Screen,
  ScreenHeader,
  SectionTitle,
} from '../../shared/ui/primitives';
import { useAuth } from '../auth/AuthProvider';
import { useAppearance } from '../appearance/AppearanceProvider';
import { useConnection } from '../connection/ConnectionProvider';
import { getBackendVersion } from '../../shared/api/endpoints';
import { mobileSoftware } from '../../shared/errorReport/collect';
import { buildPatchLabel, mobileBuildPatch } from '../../shared/buildPatch';
import { setDebugMode, useDebugMode } from '../../shared/debug/debugMode';

type Props = NativeStackScreenProps<RootStackParamList, 'Settings'>;

/** Version, versionCode and commit: an old APK against a new node is visible at once. */
function clientBuildLabel() {
  const { version, build, commit } = mobileSoftware();
  return [version, build && `сборка ${build}`, commit ? commit.slice(0, 7) : 'коммит неизвестен'].filter(Boolean).join(' · ');
}

function SettingChoice<T extends string>({
  label,
  value,
  selected,
  onPress,
  swatch,
}: {
  label: string;
  value: T;
  selected: T;
  onPress: (value: T) => void;
  swatch?: { background: string; accent: string };
}) {
  const colors = useAppColors();
  const active = selected === value;
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: active }}
      onPress={() => onPress(value)}
      style={({ pressed }) => [
        styles.choice,
        {
          backgroundColor: active ? colors.accentSoft : colors.surface,
          borderColor: active ? colors.accent : colors.border,
          opacity: pressed ? 0.68 : 1,
        },
      ]}
    >
      {swatch ? (
        <View style={[styles.swatch, { backgroundColor: swatch.background, borderColor: colors.border }]}>
          <View style={[styles.swatchAccent, { backgroundColor: swatch.accent }]} />
        </View>
      ) : null}
      <Text style={[styles.choiceText, { color: active ? colors.accentText : colors.text }]}>
        {label}
      </Text>
    </Pressable>
  );
}

export function SettingsScreen({ navigation }: Props) {
  const colors = useAppColors();
  const auth = useAuth();
  const appearance = useAppearance();
  const uiTheme = useUiTheme();
  const connection = useConnection();
  const { isOnline } = useNetwork();
  const debugMode = useDebugMode();
  const [busy, setBusy] = useState(false);
  const [appearanceError, setAppearanceError] = useState<string | null>(null);
  const backendVersion = useQuery({
    queryKey: ['backend-version', connection.nodeOrigin],
    queryFn: getBackendVersion,
    enabled: isOnline && Boolean(connection.nodeOrigin),
    staleTime: 60_000,
    retry: 1,
  });

  useEffect(() => {
    if (backendVersion.data?.version) {
      void connection.rememberBackendVersion(backendVersion.data.version);
    }
  }, [backendVersion.data?.version]);

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  function confirmSignOutAll() {
    Alert.alert(
      'Завершить все сеансы?',
      'Вход будет завершён на всех устройствах этого аккаунта.',
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: 'Завершить',
          style: 'destructive',
          onPress: () => void run(auth.signOutEverywhere),
        },
      ],
    );
  }

  function confirmSwitchNode() {
    Alert.alert(
      'Сменить узел?',
      'Локальные снимки и неотправленные изменения текущего аккаунта будут очищены.',
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: 'Сменить',
          style: 'destructive',
          onPress: () => void run(async () => {
            await auth.signOut();
            await connection.disconnect();
          }),
        },
      ],
    );
  }

  function saveAppearance(
    patch: Parameters<typeof appearance.savePreferences>[0],
  ) {
    setAppearanceError(null);
    void appearance.savePreferences(patch).catch((error) => {
      setAppearanceError(error instanceof Error
        ? error.message
        : 'Не удалось сохранить оформление.');
    });
  }

  return (
    <Screen scroll>
      <ScreenHeader title="Настройки" onBack={() => navigation.goBack()} />
      <DeviceLinkPanel/>

      {!isOnline ? (
        <InlineNotice
          text="Сейчас нет связи с узлом. Локальный выход доступен, а завершение всех сеансов — нет."
          tone="warning"
        />
      ) : null}

      <Panel style={styles.panel}>
        <SectionTitle title="Вид приложения" />
        <Text style={[styles.caption, { color: colors.muted }]}>
          Тема приложения: применяется сразу и хранится на этом телефоне
        </Text>
        <View style={styles.choices}>
          {UI_THEMES.map((theme) => (
            <SettingChoice
              key={theme.id}
              label={theme.label}
              value={theme.id}
              selected={uiTheme.theme}
              onPress={uiTheme.setTheme}
              swatch={{ background: theme.colors.background, accent: theme.colors.accentStrong }}
            />
          ))}
        </View>
        <Text style={[styles.caption, { color: colors.muted }]}>Плотность интерфейса</Text>
        <View style={styles.choices}>
          {([
            ['comfortable', 'Свободная'],
            ['compact', 'Компактная'],
          ] as Array<[Density, string]>).map(([value, label]) => (
            <SettingChoice
              key={value}
              label={label}
              value={value}
              selected={appearance.preferences.density}
              onPress={(density) => saveAppearance({ density })}
            />
          ))}
        </View>
        <View style={styles.choices}>
          <SettingChoice
            label="Обычные анимации"
            value="motion"
            selected={appearance.preferences.reduceMotion ? 'reduced' : 'motion'}
            onPress={() => saveAppearance({ reduceMotion: false })}
          />
          <SettingChoice
            label="Меньше движения"
            value="reduced"
            selected={appearance.preferences.reduceMotion ? 'reduced' : 'motion'}
            onPress={() => saveAppearance({ reduceMotion: true })}
          />
        </View>
        <Text style={[styles.caption, { color: colors.muted }]}>
          Плотность и анимации те же, что в веб-клиенте. Без сети изменение остаётся на
          устройстве и отправится узлу после подключения. Тема у каждого устройства своя.
        </Text>
        {appearanceError ? <InlineNotice text={appearanceError} tone="danger" /> : null}
        {appearance.saving ? <InlineNotice text="Сохраняем оформление…" /> : null}
      </Panel>

      <Panel style={styles.panel}>
        <SectionTitle title="Аккаунт" />
        <View style={styles.valueBlock}>
          <Text style={[styles.primaryValue, { color: colors.text }]}>
            {auth.user?.displayName}
          </Text>
          <Text style={[styles.secondaryValue, { color: colors.muted }]}>
            {auth.user?.email}
          </Text>
        </View>
        <Text style={[styles.caption, { color: colors.muted }]}>
          {auth.isOfflineSession ? 'Открыта сохранённая офлайн-сессия' : 'Сеанс подтверждён узлом'}
        </Text>
      </Panel>

      <Panel style={styles.panel}>
        <SectionTitle title="Узел" />
        <Text style={[styles.node, { color: colors.text }]} selectable>
          {connection.nodeOrigin}
        </Text>
        <Text style={[styles.caption, { color: colors.muted }]}>
          Android-клиент хранит адрес отдельно от данных аккаунта. В мобильной сети подготовленные
          доски обходят недоступный LAN-адрес и сразу используют relay.
        </Text>
        <Button label="Сменить узел" variant="danger" disabled={busy} onPress={confirmSwitchNode} />
      </Panel>

      <Panel style={styles.panel}>
        <SectionTitle title="Сеансы" />
        <Button
          label="Выйти на этом устройстве"
          disabled={busy}
          loading={busy}
          onPress={() => void run(auth.signOut)}
        />
        <Button
          label="Завершить все сеансы"
          variant="danger"
          disabled={busy || !isOnline}
          onPress={confirmSignOutAll}
        />
      </Panel>

      <Panel style={styles.panel}>
        <SectionTitle title="Версии" />
        <View style={styles.versionRow}>
          <Text style={[styles.caption, { color: colors.muted }]}>Android-клиент</Text>
          <Text style={[styles.versionValue, { color: colors.text }]} selectable>
            {clientBuildLabel()}
          </Text>
        </View>
        <View style={styles.versionRow}>
          <Text style={[styles.caption, { color: colors.muted }]}>Собран из патча</Text>
          <Text style={[styles.versionValue, { color: colors.text }]} selectable testID="build-patch">
            {buildPatchLabel(mobileBuildPatch())}
          </Text>
        </View>
        <View style={styles.versionRow}>
          <Text style={[styles.caption, { color: colors.muted }]}>Backend подключённого узла</Text>
          <Text style={[styles.versionValue, { color: colors.text }]} selectable>
            {backendVersion.data?.version
              || connection.backendVersion
              || (backendVersion.isFetching ? 'проверяем…' : 'недоступен')}
          </Text>
        </View>
        <Text style={[styles.caption, { color: colors.muted }]}>
          Если приложение подвисало, скопируйте журнал сразу после перезапуска: в нём
          видно, какая работа шла и сколько JS-поток не отвечал.
        </Text>
        <ErrorDetails message="Журнал по запросу из настроек" operation="Диагностика" screen="Настройки" />
      </Panel>

      <Panel style={styles.panel}>
        <SectionTitle title="Режим отладки" />
        <Text style={[styles.caption, { color: colors.muted }]}>
          {debugMode
            ? 'Включён: журнал пишет каждый шаг синхронизации, смену экрана и сети, хранит 5000 строк и переживает перезапуск. Немного нагружает телефон; выключите, когда разберётесь.'
            : 'Журнал в реальном времени: шаги синхронизации досок, relay, смена сети и экранов. Пароли, токены и ключи вырезаются, тексты карточек не пишутся.'}
        </Text>
        <View style={styles.choices}>
          <SettingChoice
            label="Выключен"
            value="off"
            selected={debugMode ? 'on' : 'off'}
            onPress={() => void setDebugMode(false)}
          />
          <SettingChoice
            label="Включён"
            value="on"
            selected={debugMode ? 'on' : 'off'}
            onPress={() => void setDebugMode(true)}
          />
        </View>
        <Button label="Открыть журнал" onPress={() => navigation.navigate('DebugJournal')} />
      </Panel>
    </Screen>
  );
}

const styles = StyleSheet.create({
  panel: {
    gap: spacing.md,
  },
  valueBlock: {
    gap: spacing.xs,
  },
  primaryValue: {
    fontSize: 18,
    fontWeight: '700',
  },
  secondaryValue: {
    fontSize: 14,
  },
  node: {
    fontSize: 14,
    fontFamily: 'monospace',
  },
  caption: {
    fontSize: 13,
    lineHeight: 19,
  },
  versionRow: {
    gap: spacing.xs,
  },
  versionValue: {
    fontSize: 14,
    fontFamily: 'monospace',
  },
  choices: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  swatch: {
    width: 18,
    height: 18,
    borderRadius: 5,
    borderWidth: 1,
    overflow: 'hidden',
    justifyContent: 'flex-end',
  },
  swatchAccent: {
    height: 6,
  },
  choice: {
    minHeight: 40,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    justifyContent: 'center',
    paddingHorizontal: spacing.sm,
    borderWidth: 1,
    borderRadius: 8,
  },
  choiceText: {
    fontSize: 13,
    fontWeight: '700',
  },
});
