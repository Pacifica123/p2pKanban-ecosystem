import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { spacing, useAppColors } from '../../app/theme';
import { ApiError } from '../../shared/api/client';
import {
  Button,
  Field,
  InlineNotice,
  Panel,
  Screen,
} from '../../shared/ui/primitives';
import { useConnection } from '../connection/ConnectionProvider';
import { useAuth } from './AuthProvider';

type Mode = 'sign-in' | 'sign-up';

function readableError(error: unknown) {
  if (!(error instanceof Error)) return 'Не удалось выполнить вход.';
  if (error instanceof ApiError && error.status === 401) return 'Неверная почта или пароль.';
  return error.message;
}

export function AuthScreen() {
  const colors = useAppColors();
  const auth = useAuth();
  const connection = useConnection();
  const [mode, setMode] = useState<Mode>('sign-in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (busy) return;
    if (password.length < 8) {
      setError('Пароль должен содержать не меньше восьми символов.');
      return;
    }
    if (mode === 'sign-up' && displayName.trim().length < 2) {
      setError('Имя должно содержать не меньше двух символов.');
      return;
    }

    setBusy(true);
    setError(null);
    try {
      if (mode === 'sign-in') {
        await auth.signIn({ email: email.trim(), password });
      } else {
        await auth.signUp({
          email: email.trim(),
          password,
          displayName: displayName.trim(),
        });
      }
    } catch (reason) {
      setError(readableError(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen scroll contentStyle={styles.content}>
      <View style={styles.hero}>
        <Text style={[styles.brand, { color: colors.accent }]}>p2pKanban</Text>
        <Text style={[styles.title, { color: colors.text }]}>
          {mode === 'sign-in' ? 'Вход' : 'Новый аккаунт'}
        </Text>
        <Text style={[styles.node, { color: colors.muted }]} numberOfLines={2}>
          Узел: {connection.nodeOrigin}
        </Text>
      </View>

      <View style={[styles.tabs, { backgroundColor: colors.surfaceMuted }]}>
        <Button
          label="Войти"
          variant={mode === 'sign-in' ? 'primary' : 'ghost'}
          compact
          onPress={() => {
            setMode('sign-in');
            setError(null);
          }}
        />
        <Button
          label="Регистрация"
          variant={mode === 'sign-up' ? 'primary' : 'ghost'}
          compact
          onPress={() => {
            setMode('sign-up');
            setError(null);
          }}
        />
      </View>

      <Panel style={styles.form}>
        {mode === 'sign-up' ? (
          <Field
            label="Имя"
            value={displayName}
            onChangeText={setDisplayName}
            autoCapitalize="words"
            placeholder="Как вас показывать"
          />
        ) : null}
        <Field
          label="Почта"
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          placeholder="name@example.org"
        />
        <Field
          label="Пароль"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          autoCapitalize="none"
          returnKeyType="go"
          onSubmitEditing={() => void submit()}
          placeholder="Не меньше 8 символов"
        />
        {error ? <InlineNotice text={error} tone="danger" /> : null}
        <Button
          label={mode === 'sign-in' ? 'Войти' : 'Создать аккаунт'}
          variant="primary"
          loading={busy}
          disabled={!email.trim() || !password}
          onPress={() => void submit()}
        />
      </Panel>

      <Button
        label="Выбрать другой узел"
        variant="ghost"
        onPress={() => void connection.disconnect()}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: {
    justifyContent: 'center',
    paddingVertical: spacing.xl,
  },
  hero: {
    gap: spacing.xs,
  },
  brand: {
    fontSize: 15,
    fontWeight: '800',
    letterSpacing: 0.8,
  },
  title: {
    fontSize: 30,
    fontWeight: '800',
  },
  node: {
    fontSize: 13,
    lineHeight: 18,
  },
  tabs: {
    flexDirection: 'row',
    gap: spacing.xs,
    padding: spacing.xs,
    borderRadius: 9,
  },
  form: {
    gap: spacing.md,
  },
});
