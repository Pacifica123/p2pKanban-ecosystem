import { registerRootComponent } from 'expo';

import './src/shared/crypto/installCryptoPolyfill';
import { installJournal } from './src/shared/errorReport/journal';
import App from './App';

installJournal();
registerRootComponent(App);
