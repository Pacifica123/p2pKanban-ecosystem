import * as ExpoCrypto from 'expo-crypto';

type CryptoWithRandomValues = {
  getRandomValues?: typeof ExpoCrypto.getRandomValues;
};

const root = globalThis as unknown as {
  crypto?: CryptoWithRandomValues;
};

if (!root.crypto) {
  Object.defineProperty(root, 'crypto', {
    configurable: true,
    value: {},
  });
}

if (typeof root.crypto?.getRandomValues !== 'function') {
  Object.defineProperty(root.crypto, 'getRandomValues', {
    configurable: true,
    value: ExpoCrypto.getRandomValues,
  });
}
