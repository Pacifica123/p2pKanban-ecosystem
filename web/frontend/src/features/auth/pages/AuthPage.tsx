import { NetworkConnect } from '@/features/deviceLink/NetworkConnect';
import {DeviceLinkPanel} from '@/features/deviceLink/DeviceLinkPanel';
import { FormEvent, useMemo, useState } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { ApiError } from '@/shared/api/errors';
import { useAuthSession } from '@/app/providers/AuthSessionProvider';
import { Panel } from '@/shared/ui/Panel';
import { TextField } from '@/shared/ui/Field';
import { Button } from '@/shared/ui/Button';

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Не удалось связаться с сервером.';
}

export function AuthPage() {
  const [searchParams] = useSearchParams();
  const { status, signInWithPassword, signUpWithPassword, signInFromAnotherNode } = useAuthSession();
  const [mode, setMode] = useState<'sign_in' | 'node_link' | 'sign_up'>('sign_in');
  const [sourceUrl, setSourceUrl] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const title = useMemo(() => {
    if (mode === 'sign_in') return 'Вход на этом узле';
    if (mode === 'node_link') return 'Подключение существующего аккаунта';
    return 'Новый отдельный аккаунт';
  }, [mode]);

  if (status === 'authenticated') {
    const next = searchParams.get('next');
    const safeNext = next?.startsWith('/') && !next.startsWith('//') ? next : '/';
    return <Navigate to={safeNext} replace />;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setSubmitError(null);

    try {
      if (mode === 'sign_in') {
        await signInWithPassword({ email, password });
      } else if (mode === 'node_link') {
        await signInFromAnotherNode({ sourceUrl: sourceUrl.trim(), email, password });
      } else {
        await signUpWithPassword({ email, password, displayName });
      }
    } catch (error) {
      setSubmitError(errorMessage(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="content-stack" data-testid="auth-page" style={{ maxWidth: 560, margin: '40px auto' }}>
      <NetworkConnect first />
      <DeviceLinkPanel destination/>
      <Panel title="p2pKanban" description="Ваши доски в собственном локальном окружении.">
        <div className="toolbar">
          <Button data-testid="auth-mode-sign-in" variant={mode === 'sign_in' ? 'primary' : 'default'} onClick={() => setMode('sign_in')}>
            Войти
          </Button>
          <Button data-testid="auth-mode-node-link" variant={mode === 'node_link' ? 'primary' : 'default'} onClick={() => setMode('node_link')}>
            Подключить с другого узла
          </Button>
          <Button data-testid="auth-mode-sign-up" variant={mode === 'sign_up' ? 'primary' : 'default'} onClick={() => setMode('sign_up')}>
            Создать отдельный аккаунт
          </Button>
        </div>
      </Panel>

      <Panel
        title={title}
        description={
          mode === 'sign_in'
            ? 'Входит только в аккаунт, который уже существует в локальной базе этого узла.'
            : mode === 'node_link'
              ? 'Целевой узел должен быть чистым. Оба web-узла должны быть запущены и доступны друг другу в доверенной локальной сети.'
              : 'Создаёт новую независимую идентичность. Совпадающий email на другом узле не связывает аккаунты.'
        }
      >
        <form className="stack" onSubmit={onSubmit}>
          {mode === 'node_link' ? (
            <TextField
              data-testid="auth-source-url"
              label="Адрес исходного web-узла"
              type="url"
              placeholder="http://192.168.1.42:8080"
              value={sourceUrl}
              onChange={(event) => setSourceUrl(event.target.value)}
              required
            />
          ) : null}
          <TextField data-testid="auth-email" label="Email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          <TextField data-testid="auth-password" label="Пароль" type="password" autoComplete={mode === 'sign_up' ? 'new-password' : 'current-password'} value={password} onChange={(event) => setPassword(event.target.value)} required />
          {mode === 'sign_up' ? (
            <TextField data-testid="auth-display-name" label="Имя" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
          ) : null}

          {submitError ? <p className="error-text" data-testid="auth-error">{submitError}</p> : null}

          <div className="toolbar">
            <Button data-testid="auth-submit" type="submit" variant="primary" disabled={isSubmitting}>
              {isSubmitting
                ? 'Подождите…'
                : mode === 'sign_in'
                  ? 'Войти'
                  : mode === 'node_link'
                    ? 'Подключить и перенести доски'
                    : 'Создать отдельный аккаунт'}
            </Button>
          </div>
        </form>
      </Panel>
    </div>
  );
}
