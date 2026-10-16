import { ApiError } from '../../shared/api/client';
import { readableError } from './signInError';

const rejected = new ApiError('Invalid email or password', { status: 401 });

test('a rejected sign-in names the node and the other-node cause', () => {
  const text = readableError(rejected, 'sign-in', 'http://192.168.0.101:8082');
  expect(text).toContain('Узел http://192.168.0.101:8082 не принял');
  expect(text).toContain('только на узле, где его создали');
});

test('other failures keep their own message', () => {
  expect(readableError(new ApiError('Узел не ответил вовремя.', { status: 0 }), 'sign-in', null)).toBe('Узел не ответил вовремя.');
  expect(readableError(rejected, 'sign-up', null)).toBe('Invalid email or password');
  expect(readableError('boom', 'sign-in', null)).toBe('Не удалось выполнить вход.');
});
