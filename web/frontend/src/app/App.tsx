import { AppProviders } from '@/app/providers/AppProviders';
import { AppRouter } from '@/app/router';

export default function App() {
  return (
    <div data-testid="app-root">
      <AppProviders>
        <AppRouter />
      </AppProviders>
    </div>
  );
}
