import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { spacing, useAppColors } from '../../app/theme';
import {
  Button,
  Field,
  InlineNotice,
  Panel,
  Screen,
} from '../../shared/ui/primitives';
import { useConnection } from './ConnectionProvider';

export function ConnectionScreen() {
  const colors = useAppColors();
  const { connect } = useConnection();
  const [address, setAddress] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleConnect() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await connect(address);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось подключиться к узлу.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen scroll contentStyle={styles.content}>
      <View style={styles.hero}>
        <Text style={[styles.brand, { color: colors.accent }]}>p2pKanban</Text>
        <Text style={[styles.title, { color: colors.text }]}>Подключение к узлу</Text>
        <Text style={[styles.subtitle, { color: colors.muted }]}> 
          Для первой привязки приложение подключается к вашему узлу. Подготовленные доски затем
          синхронизируются через зашифрованный relay-журнал из любой сети.
        </Text>
      </View>

      <Panel style={styles.form}>
        <Field
          label="Адрес p2pKanban"
          value={address}
          onChangeText={setAddress}
          onSubmitEditing={() => void handleConnect()}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          returnKeyType="go"
          placeholder="http://192.168.1.42:порт"
          hint="Укажите адрес, который bootstrap показал после запуска в LAN-режиме."
        />
        {error ? <InlineNotice text={error} tone="danger" /> : null}
        <Button
          label="Проверить и подключиться"
          variant="primary"
          loading={busy}
          disabled={!address.trim()}
          onPress={() => void handleConnect()}
        />
      </Panel>

      <Panel style={styles.help}>
        <Text style={[styles.helpTitle, { color: colors.text }]}>На компьютере</Text>
        <Text style={[styles.code, { color: colors.text, backgroundColor: colors.surfaceMuted }]}>
          python bootstrap.py start --listen lan
        </Text>
        <Text style={[styles.helpText, { color: colors.muted }]}>
          Общая доверенная сеть нужна только для первой привязки аккаунта и получения ключей досок.
          Для Android Emulator вместо адреса компьютера обычно используется 10.0.2.2.
        </Text>
      </Panel>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: {
    justifyContent: 'center',
    paddingVertical: spacing.xl,
  },
  hero: {
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  brand: {
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: 0.8,
  },
  title: {
    fontSize: 30,
    lineHeight: 36,
    fontWeight: '800',
  },
  subtitle: {
    fontSize: 15,
    lineHeight: 22,
  },
  form: {
    gap: spacing.md,
  },
  help: {
    gap: spacing.sm,
  },
  helpTitle: {
    fontSize: 16,
    fontWeight: '700',
  },
  code: {
    padding: spacing.sm,
    borderRadius: 7,
    fontFamily: 'monospace',
    fontSize: 13,
  },
  helpText: {
    fontSize: 13,
    lineHeight: 19,
  },
});
