import { ApiError } from '../../shared/api/client';

export type Mode = 'sign-in' | 'sign-up';

// Accounts are node-local: a correct password for an account made on another node is a 401 too.
export function readableError(error: unknown, mode: Mode, node: string | null) {
  if (!(error instanceof Error)) return 'Не удалось выполнить вход.';
  if (error instanceof ApiError && error.status === 401 && mode === 'sign-in') {
    return `${node ? `Узел ${node}` : 'Узел'} не принял эту почту и пароль. Аккаунт хранится только на узле, где его создали: `
      + 'другой узел его не знает, пока аккаунт туда не перенесён. '
      + 'Проверьте пароль или выберите узел, на котором регистрировались.';
  }
  return error.message;
}
