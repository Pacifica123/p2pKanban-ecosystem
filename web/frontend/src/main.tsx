import React from 'react';
import ReactDOM from 'react-dom/client';
import App from '@/app/App';
import '@/app/styles/reset.css';
import '@/app/styles/themes.css';
import '@/app/styles/globals.css';
import { installJournal } from '@/shared/errorReport/journal';
import { applyUiTheme, readStoredUiTheme } from '@/shared/appearance/uiThemes';

installJournal();
applyUiTheme(readStoredUiTheme());

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
