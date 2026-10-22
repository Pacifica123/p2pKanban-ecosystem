import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { POLL_MS, RingQrMeeting, type Meeting } from '@/features/deviceLink/RingQrMeeting';

const api = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock('@/shared/api/client', () => api);

const phone = 'df53cdd4693df19cd9e2b2931013244b1e67c569f6ff5ed217a62e968dec1896';
const base: Meeting = {
  sessionId: 'r_CHGQQKynHyiBZh14MAyN4jI_jFTJnEfhThs4VVLRY', mode: 'invite', status: 'waiting',
  qrText: 'p2pkanban:rv1:eyJrIjoiYjk5OWVj', expiresAt: Math.floor(Date.now() / 1000) + 600,
  relays: ['wss://relay-a.example'], code: null, peer: null, outcome: null,
};
const asking: Meeting = { ...base, status: 'confirm', code: '324 647',
  peer: { publicKey: phone, name: 'Телефон', kind: 'android', alreadyMember: false, software: { direction: 'mobile', version: '2.2.0' } } };

function renderMeeting(hasRing = true, members = 1) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><RingQrMeeting hasRing={hasRing} members={members} /></QueryClientProvider>);
}

describe('RingQrMeeting (R4)', () => {
  beforeEach(() => { api.apiRequest.mockReset(); vi.useFakeTimers({ shouldAdvanceTime: true }); });
  afterEach(() => vi.useRealTimers());

  it('shows the QR, then the phone and its code, and admits it as member only on request', async () => {
    const polls = [asking];
    api.apiRequest.mockImplementation(async (path: string, init?: { body?: string }) => {
      if (path === '/ring/rendezvous') return base;
      if (path === `/ring/rendezvous/${base.sessionId}`) return polls.shift() ?? asking;
      if (path === `/ring/rendezvous/${base.sessionId}/confirm`) {
        expect(JSON.parse(init!.body!)).toEqual({ role: 'member' });
        return { ...asking, status: 'done', qrText: null };
      }
      throw new Error(path);
    });
    renderMeeting();
    fireEvent.click(screen.getByRole('button', { name: 'Показать QR: телефон входит в кольцо узла' }));
    expect(await screen.findByTestId('ring-qr')).toBeTruthy();
    await act(async () => { vi.advanceTimersByTime(POLL_MS + 10); });
    expect(await screen.findByText('324 647')).toBeTruthy();
    expect(screen.getByText(/Просит войти в кольцо: «Телефон» \(Android, mobile 2.2.0\)/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Только участник/));
    fireEvent.click(screen.getByRole('button', { name: 'Код совпадает — принять в кольцо' }));
    expect(await screen.findByTestId('ring-meeting-done')).toHaveTextContent('Готово: «Телефон»');
  });

  it('join mode shows the code at once; without a ring only join is offered', async () => {
    api.apiRequest.mockResolvedValue({ ...base, mode: 'join', code: '110 220' });
    renderMeeting(false, 0);
    expect(screen.queryByRole('button', { name: /телефон входит/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Показать QR: добавить узел в кольцо телефона' }));
    await waitFor(() => expect(api.apiRequest).toHaveBeenCalledWith('/ring/rendezvous', { method: 'POST', body: JSON.stringify({ mode: 'join' }) }));
    expect(await screen.findByTestId('ring-code')).toHaveTextContent('110 220');
  });

  it('names the reason when the meeting stops', async () => {
    api.apiRequest.mockImplementation(async (path: string) => path === '/ring/rendezvous' ? base
      : { ...base, status: 'refused', qrText: null, outcome: { reason: 'ring-merge-unsupported', detail: 'Рабочий ПК уже состоит в другом кольце из 3 устройств.' } });
    renderMeeting();
    fireEvent.click(screen.getByRole('button', { name: /телефон входит/ }));
    await screen.findByTestId('ring-qr');
    await act(async () => { vi.advanceTimersByTime(POLL_MS + 10); });
    expect(await screen.findByTestId('ring-meeting-stopped')).toHaveTextContent('слияние колец пока не поддерживается. Рабочий ПК');
  });
});
