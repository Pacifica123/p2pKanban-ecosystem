import { registerRootComponent } from 'expo';

import './src/shared/crypto/installCryptoPolyfill';
import App from './App';

registerRootComponent(App);
