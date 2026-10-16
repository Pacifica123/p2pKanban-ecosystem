import { registerRootComponent } from 'expo';

import './src/shared/crypto/installCryptoPolyfill';
import { installJournal } from './src/shared/errorReport/journal';
import { installStallWatch } from './src/shared/lib/stallWatch';
import App from './App';

installJournal();
installStallWatch();
registerRootComponent(App);
