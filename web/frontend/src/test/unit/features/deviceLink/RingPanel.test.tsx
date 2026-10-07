import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RingPanel, skewText, type RingView } from '@/features/deviceLink/RingPanel';

const api = vi.hoisted(() => ({ apiRequest: vi.fn() }));
vi.mock('@/shared/api/client', () => api);

const node = 'b999ec6cda9226c00f7e2156fbd65866b4bec7e30fad42773216682deee02a51';
const phone = 'df53cdd4693df19cd9e2b2931013244b1e67c569f6ff5ed217a62e968dec1896';
const before: RingView = {
  enabled: true, nodePublicKey: node, ring: null, keyring: null, presences: [], skew: [], lastSync: null,
  legacy: [{ publicKey: phone, approvedAt: '2026-10-01T10:00:00Z' }],
  relays: { urls: ['wss://relay-a.example', 'wss://relay-b.example'], minAcks: 2 },
};
const ring = {
  accountId: 'ad0c2572ae5abb2eb300b6160a50eb4eb0b364899e54ed64a978c4de0fb220ce',
  members: [
    { publicKey: node, name: 'Домашний узел', kind: 'web' as const, role: 'admin', addedBy: null },
    { publicKey: phone, name: 'Телефон', kind: 'android' as const, role: 'admin', addedBy: node },
  ],
  removed: [], relays: { urls: ['wss://relay-a.example'], minAcks: 1 }, rejected: [], pending: [], readerOutdated: [],
};
const after: RingView = {
  ...before, legacy: [], ring,
  keyring: { summary: { boards: 1, items: 3 }, copies: 1, items: [
    { kind: 'board', id: 'b1', name: 'Планы', rev: 1, deleted: false, onThisNode: true },
    { kind: 'space', id: 's2', name: 'Поездка', rev: 1, deleted: false, onThisNode: false },
  ] },
  presences: [{ publicKey: phone, seenAt: 1791300000, software: { direction: 'mobile', version: '2.1.0' } }],
  skew: [{ publicKey: phone, missingProtocols: ['p2p-kanban-account-ring/1'], staleRing: true }],
  lastSync: { at: 1791300100, quorum: false, fetched: 3, newEntries: 1, keyringCopies: 1, presences: 1,
    published: [{ recordType: 'ring-log', accepted: [], failed: ['wss://relay-a.example'] }], errors: ['fetch: timeout'] },
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><RingPanel /></QueryClientProvider>);
}

describe('RingPanel (R2)', () => {
  beforeEach(() => api.apiRequest.mockReset());

  it('creates the ring, then moves an old-style trusted phone into it', async () => {
    api.apiRequest.mockImplementation(async (path: string) => {
      if (path === '/ring') return before;
      if (path === '/ring/genesis') return { ...before, ring: { ...ring, members: [ring.members[0]] } };
      if (path === '/ring/migrate') return after;
      throw new Error(path);
    });
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Создать кольцо' }));
    await waitFor(() => expect(api.apiRequest).toHaveBeenCalledWith('/ring/genesis',
      { method: 'POST', body: JSON.stringify({ name: 'Домашний узел' }) }));
    fireEvent.change(await screen.findByLabelText('Имя устройства'), { target: { value: 'Телефон' } });
    fireEvent.click(screen.getByRole('button', { name: 'Перенести в кольцо' }));
    await waitFor(() => expect(api.apiRequest).toHaveBeenCalledWith('/ring/migrate',
      { method: 'POST', body: JSON.stringify({ publicKey: phone, name: 'Телефон', kind: 'android' }) }));
    expect(await screen.findAllByTestId('ring-member')).toHaveLength(2);
  });

  it('shows version skew, keyring items from other devices and why the relays failed', async () => {
    api.apiRequest.mockResolvedValue(after);
    renderPanel();
    expect(await screen.findByText(/mobile 2\.1\.0/)).toBeInTheDocument();
    expect(screen.getByText('отстаёт')).toBeInTheDocument();
    expect(screen.getByText(/«Поездка»/)).toBeInTheDocument();
    expect(screen.getByTestId('ring-last-sync')).toHaveTextContent('кворум relay не собран');
    expect(screen.getByRole('alert')).toHaveTextContent('fetch: timeout');
  });

  it('explains skew in plain words', () => {
    expect(skewText({ publicKey: phone, missingProtocols: ['p2p-kanban-keyring/1'], staleRing: true }))
      .toBe('не знает p2p-kanban-keyring/1 — нужна новая версия; видит старый журнал кольца');
  });
});
