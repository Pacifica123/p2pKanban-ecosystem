import {
  DarkTheme,
  DefaultTheme,
  NavigationContainer,
  type Theme,
} from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { useEffect } from 'react';

import { ActivityScreen } from '../../features/activity/ActivityScreen';
import { useAuth } from '../../features/auth/AuthProvider';
import { AuthScreen } from '../../features/auth/AuthScreen';
import { BoardScreen } from '../../features/boards/BoardScreen';
import { BoardsScreen } from '../../features/boards/BoardsScreen';
import { useConnection } from '../../features/connection/ConnectionProvider';
import { ConnectionScreen } from '../../features/connection/ConnectionScreen';
import { SettingsScreen } from '../../features/settings/SettingsScreen';
import { useAppearance } from '../../features/appearance/AppearanceProvider';
import { WorkspacesScreen } from '../../features/workspaces/WorkspacesScreen';
import { WorkspaceAccessScreen } from '../../features/workspaces/WorkspaceAccessScreen';
import { Screen, StateView } from '../../shared/ui/primitives';
import { useAppColors, useResolvedTheme } from '../theme';
import type { RootStackParamList } from './types';
import { flushReminderTarget, navigationRef } from './navigationService';

const Stack = createNativeStackNavigator<RootStackParamList>();

function LoadingRoot() {
  return (
    <Screen>
      <StateView title="Открываем p2pKanban" busy />
    </Screen>
  );
}

export function RootNavigator() {
  const connection = useConnection();
  const auth = useAuth();
  const { preferences } = useAppearance();
  const colors = useAppColors();
  const isDark = useResolvedTheme() === 'dark';
  const base = isDark ? DarkTheme : DefaultTheme;
  const theme: Theme = {
    ...base,
    colors: {
      ...base.colors,
      primary: colors.accent,
      background: colors.background,
      card: colors.surface,
      text: colors.text,
      border: colors.border,
      notification: colors.danger,
    },
  };

  useEffect(() => {
    flushReminderTarget(auth.status === 'authenticated');
  }, [auth.status]);

  if (connection.status === 'loading' || (connection.nodeOrigin && auth.status === 'loading')) {
    return <LoadingRoot />;
  }

  return (
    <NavigationContainer
      ref={navigationRef}
      theme={theme}
      onReady={() => flushReminderTarget(auth.status === 'authenticated')}
    >
      <Stack.Navigator screenOptions={{
        headerShown: false,
        animation: preferences.reduceMotion ? 'none' : 'slide_from_right',
      }}>
        {!connection.nodeOrigin ? (
          <Stack.Screen name="Connection" component={ConnectionScreen} />
        ) : auth.status === 'anonymous' ? (
          <Stack.Screen name="Auth" component={AuthScreen} />
        ) : (
          <>
            <Stack.Screen name="Workspaces" component={WorkspacesScreen} />
            <Stack.Screen name="WorkspaceAccess" component={WorkspaceAccessScreen} />
            <Stack.Screen name="Boards" component={BoardsScreen} />
            <Stack.Screen name="Board" component={BoardScreen} />
            <Stack.Screen name="Activity" component={ActivityScreen} />
            <Stack.Screen name="Settings" component={SettingsScreen} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
