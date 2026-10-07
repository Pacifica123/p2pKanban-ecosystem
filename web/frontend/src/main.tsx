import React from 'react';
import ReactDOM from 'react-dom/client';
import App from '@/app/App';
import '@/app/styles/reset.css';
import '@/app/styles/globals.css';
import { installJournal } from '@/shared/errorReport/journal';

installJournal();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
