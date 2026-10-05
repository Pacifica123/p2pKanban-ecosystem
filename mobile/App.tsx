import { StatusBar } from 'expo-status-bar';

import { AppProviders } from './src/app/AppProviders';
import { RootNavigator } from './src/app/navigation/RootNavigator';
import { useResolvedTheme } from './src/app/theme';

function AppContent() {
  const theme = useResolvedTheme();
  return (
    <>
      <StatusBar style={theme === 'dark' ? 'light' : 'dark'} />
      <RootNavigator />
    </>
  );
}

export default function App() {
  return (
    <AppProviders>
      <AppContent />
    </AppProviders>
  );
}
