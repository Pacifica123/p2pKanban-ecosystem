import { DurableObject } from 'cloudflare:workers';

import {
  boardRoute,
  parsePullWindow,
  validateCoordinatorEvent,
  type CoordinatorEvent,
  type ValidatedCoordinatorEvent,
} from './protocol';

interface Env {
  BOARD_COORDINATOR: DurableObjectNamespace<BoardCoordinator>;
  COORDINATOR_ADMIN_TOKEN: string;
}

interface MemberInput {
  actorKey: string;
  role: 'owner' | 'admin' | 'member' | 'viewer';
  epoch: number;
  active?: boolean;
}

interface SessionAttachment {
  actorKey: string;
}

interface StoredEventRow extends Record<string, SqlStorageValue> {
  server_order: number;
  event_id: string;
  replica_id: string;
  replica_seq: number;
  actor_key: string;
  membership_epoch: number;
  envelope_json: string;
  accepted_at: string;
}

interface MemberRow extends Record<string, SqlStorageValue> {
  actor_key: string;
  role: string;
  epoch: number;
  active: number;
}

const JSON_HEADERS = { 'content-type': 'application/json; charset=utf-8' };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === '/health') {
      return json({ ok: true, service: 'p2p-kanban-edge-coordinator' });
    }

    const route = boardRoute(url.pathname);
    if (!route) return json({ error: 'not_found' }, 404);

    const id = env.BOARD_COORDINATOR.idFromName(route.boardTag);
    const stub = env.BOARD_COORDINATOR.get(id);
    const headers = new Headers(request.headers);
    headers.set('x-p2p-kanban-board-tag', route.boardTag);
    headers.set('x-p2p-kanban-route', route.suffix);
    return stub.fetch(new Request(request, { headers }));
  },
} satisfies ExportedHandler<Env>;

export class BoardCoordinator extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.ensureSchema();
  }

  async fetch(request: Request): Promise<Response> {
    const route = request.headers.get('x-p2p-kanban-route') || '/';
    const url = new URL(request.url);

    if (route === '/admin/provision' && request.method === 'POST') {
      return this.provision(request);
    }
    if (route === '/admin/members' && request.method === 'POST') {
      return this.upsertMember(request);
    }
    if (route === '/sessions' && request.method === 'POST') {
      return this.createSession(request);
    }
    if (route === '/ws' && request.method === 'GET') {
      return this.upgradeWebSocket(request);
    }
    if (route === '/events' && request.method === 'POST') {
      const actorKey = await this.authorizeMember(request);
      if (actorKey instanceof Response) return actorKey;
      return this.pushEvent(await readJson(request), actorKey);
    }
    if (route === '/events' && request.method === 'GET') {
      const actorKey = await this.authorizeMember(request);
      if (actorKey instanceof Response) return actorKey;
      return this.pullEvents(url);
    }
    if (route === '/cursors' && request.method === 'POST') {
      const actorKey = await this.authorizeMember(request);
      if (actorKey instanceof Response) return actorKey;
      return this.advanceCursor(await readJson(request), actorKey);
    }
    if (route === '/status' && request.method === 'GET') {
      const actorKey = await this.authorizeMember(request);
      if (actorKey instanceof Response) return actorKey;
      return this.status();
    }
    return json({ error: 'not_found' }, 404);
  }

  async webSocketMessage(webSocket: WebSocket, message: string | ArrayBuffer): Promise<void> {
    try {
      if (typeof message !== 'string') {
        webSocket.send(JSON.stringify({ type: 'error', error: 'binary_messages_are_not_supported' }));
        return;
      }
      const body = JSON.parse(message) as { type?: string; event?: CoordinatorEvent };
      if (body.type !== 'push') {
        webSocket.send(JSON.stringify({ type: 'error', error: 'unsupported_message_type' }));
        return;
      }
      const attachment = webSocket.deserializeAttachment() as SessionAttachment | null;
      if (!attachment?.actorKey) {
        webSocket.close(4401, 'missing session');
        return;
      }
      const result = await this.acceptEvent(body.event, attachment.actorKey);
      webSocket.send(JSON.stringify({ type: 'ack', ...result }));
    } catch (error) {
      webSocket.send(JSON.stringify({
        type: 'error',
        error: error instanceof Error ? error.message : 'invalid_message',
      }));
    }
  }

  webSocketClose(webSocket: WebSocket, code: number, reason: string): void {
    webSocket.close(code, reason);
  }

  private ensureSchema(): void {
    this.ctx.storage.sql.exec(`
      create table if not exists meta (
        key text primary key,
        value text not null
      );
      create table if not exists members (
        actor_key text primary key,
        role text not null,
        epoch integer not null,
        active integer not null default 1,
        updated_at text not null
      );
      create table if not exists events (
        server_order integer primary key autoincrement,
        event_id text not null unique,
        replica_id text not null,
        replica_seq integer not null,
        actor_key text not null,
        membership_epoch integer not null,
        envelope_json text not null,
        accepted_at text not null,
        unique (replica_id, replica_seq)
      );
      create table if not exists cursors (
        actor_key text not null,
        replica_id text not null,
        last_server_order integer not null,
        updated_at text not null,
        primary key (actor_key, replica_id)
      );
      create table if not exists sessions (
        ticket_hash text primary key,
        actor_key text not null,
        expires_at integer not null
      );
      create index if not exists idx_events_order on events (server_order);
      create index if not exists idx_sessions_expiry on sessions (expires_at);
    `);
  }

  private async provision(request: Request): Promise<Response> {
    if (!this.isAdmin(request)) return json({ error: 'forbidden' }, 403);
    const body = await readJson(request) as {
      boardToken?: string;
      ownerKey?: string;
      epoch?: number;
    };
    if (!body.boardToken || body.boardToken.length < 32) {
      return json({ error: 'boardToken must contain at least 32 characters' }, 400);
    }
    if (!body.ownerKey || body.ownerKey.length < 16) {
      return json({ error: 'ownerKey is required' }, 400);
    }
    const epoch = Number.isSafeInteger(body.epoch) && Number(body.epoch) > 0
      ? Number(body.epoch)
      : 1;
    const tokenHash = await sha256(body.boardToken);
    const now = new Date().toISOString();
    this.ctx.storage.sql.exec(
      "insert into meta (key, value) values ('board_token_hash', ?) on conflict(key) do update set value = excluded.value",
      tokenHash,
    );
    this.ctx.storage.sql.exec(
      "insert into meta (key, value) values ('membership_epoch', ?) on conflict(key) do update set value = excluded.value",
      String(epoch),
    );
    this.ctx.storage.sql.exec(
      `insert into members (actor_key, role, epoch, active, updated_at)
       values (?, 'owner', ?, 1, ?)
       on conflict(actor_key) do update set role = 'owner', epoch = excluded.epoch, active = 1, updated_at = excluded.updated_at`,
      body.ownerKey,
      epoch,
      now,
    );
    return json({ status: 'provisioned', ownerKey: body.ownerKey, membershipEpoch: epoch }, 201);
  }

  private async upsertMember(request: Request): Promise<Response> {
    if (!this.isAdmin(request)) return json({ error: 'forbidden' }, 403);
    const body = await readJson(request) as Partial<MemberInput>;
    if (!body.actorKey || !body.role || !Number.isSafeInteger(body.epoch) || Number(body.epoch) < 1) {
      return json({ error: 'actorKey, role and positive epoch are required' }, 400);
    }
    const active = body.active === false ? 0 : 1;
    this.ctx.storage.sql.exec(
      `insert into members (actor_key, role, epoch, active, updated_at)
       values (?, ?, ?, ?, ?)
       on conflict(actor_key) do update set
         role = excluded.role,
         epoch = excluded.epoch,
         active = excluded.active,
         updated_at = excluded.updated_at`,
      body.actorKey,
      body.role,
      body.epoch,
      active,
      new Date().toISOString(),
    );
    this.ctx.storage.sql.exec(
      `insert into meta (key, value) values ('membership_epoch', ?)
       on conflict(key) do update set value =
         cast(max(cast(meta.value as integer), cast(excluded.value as integer)) as text)`,
      String(body.epoch),
    );
    return json({ status: active ? 'active' : 'revoked', actorKey: body.actorKey });
  }

  private async createSession(request: Request): Promise<Response> {
    const actorKey = await this.authorizeMember(request);
    if (actorKey instanceof Response) return actorKey;
    this.ctx.storage.sql.exec('delete from sessions where expires_at < ?', Date.now());
    const ticket = randomToken();
    const ticketHash = await sha256(ticket);
    const expiresAt = Date.now() + 60_000;
    this.ctx.storage.sql.exec(
      'insert into sessions (ticket_hash, actor_key, expires_at) values (?, ?, ?)',
      ticketHash,
      actorKey,
      expiresAt,
    );
    return json({ ticket, expiresAt });
  }

  private async upgradeWebSocket(request: Request): Promise<Response> {
    if (request.headers.get('Upgrade')?.toLowerCase() !== 'websocket') {
      return json({ error: 'websocket_upgrade_required' }, 426);
    }
    const ticket = new URL(request.url).searchParams.get('ticket');
    if (!ticket) return json({ error: 'ticket_required' }, 401);
    const ticketHash = await sha256(ticket);
    const rows = this.ctx.storage.sql.exec<{ actor_key: string; expires_at: number }>(
      'select actor_key, expires_at from sessions where ticket_hash = ?',
      ticketHash,
    ).toArray();
    this.ctx.storage.sql.exec('delete from sessions where ticket_hash = ?', ticketHash);
    const session = rows[0];
    if (!session || session.expires_at < Date.now()) {
      return json({ error: 'invalid_or_expired_ticket' }, 401);
    }

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);
    server.serializeAttachment({ actorKey: session.actor_key } satisfies SessionAttachment);
    this.ctx.acceptWebSocket(server);
    return new Response(null, { status: 101, webSocket: client });
  }

  private async pushEvent(input: unknown, actorKey: string): Promise<Response> {
    try {
      const result = await this.acceptEvent(input, actorKey);
      return json(result, result.status === 'accepted' ? 201 : 200);
    } catch (error) {
      return json({ error: error instanceof Error ? error.message : 'invalid_event' }, 400);
    }
  }

  private async acceptEvent(
    input: unknown,
    authenticatedActorKey: string,
  ): Promise<{ status: 'accepted' | 'duplicate'; eventId: string; serverOrder: number }> {
    const validation = validateCoordinatorEvent(input);
    if (!validation.ok || !validation.event) {
      throw new Error(validation.error || 'invalid event');
    }
    const event = validation.event;
    if (event.actorKey !== authenticatedActorKey) {
      throw new Error('actorKey does not match authenticated member');
    }
    this.assertMembership(event);

    const duplicate = this.findDuplicate(event);
    if (duplicate) {
      return { status: 'duplicate', eventId: duplicate.event_id, serverOrder: duplicate.server_order };
    }

    const acceptedAt = new Date().toISOString();
    const inserted = this.ctx.storage.sql.exec<{ server_order: number }>(
      `insert into events (
         event_id, replica_id, replica_seq, actor_key, membership_epoch, envelope_json, accepted_at
       ) values (?, ?, ?, ?, ?, ?, ?)
       returning server_order`,
      event.eventId,
      event.replicaId,
      event.replicaSeq,
      event.actorKey,
      event.membershipEpoch,
      event.encodedEnvelope,
      acceptedAt,
    ).toArray()[0];
    const serverOrder = inserted.server_order;
    const broadcast = JSON.stringify({
      type: 'event',
      event: {
        ...event,
        encodedEnvelope: undefined,
        serverOrder,
        acceptedAt,
      },
    });
    for (const socket of this.ctx.getWebSockets()) {
      try {
        socket.send(broadcast);
      } catch {
        socket.close(1011, 'broadcast failed');
      }
    }
    return { status: 'accepted', eventId: event.eventId, serverOrder };
  }

  private assertMembership(event: ValidatedCoordinatorEvent): void {
    const member = this.ctx.storage.sql.exec<MemberRow>(
      'select actor_key, role, epoch, active from members where actor_key = ?',
      event.actorKey,
    ).toArray()[0];
    if (!member || member.active !== 1) throw new Error('member is not active');
    if (member.role === 'viewer') throw new Error('viewer cannot publish events');
    if (event.membershipEpoch < member.epoch) throw new Error('membership epoch is stale');
    const epoch = Number(this.meta('membership_epoch') || '1');
    if (event.membershipEpoch !== epoch) throw new Error('membership epoch does not match coordinator');
  }

  private findDuplicate(event: ValidatedCoordinatorEvent): StoredEventRow | null {
    return this.ctx.storage.sql.exec<StoredEventRow>(
      `select server_order, event_id, replica_id, replica_seq, actor_key,
              membership_epoch, envelope_json, accepted_at
       from events
       where event_id = ? or (replica_id = ? and replica_seq = ?)
       order by case when event_id = ? then 0 else 1 end
       limit 1`,
      event.eventId,
      event.replicaId,
      event.replicaSeq,
      event.eventId,
    ).toArray()[0] || null;
  }

  private pullEvents(url: URL): Response {
    const { after, limit } = parsePullWindow(url);
    const rows = this.ctx.storage.sql.exec<StoredEventRow>(
      `select server_order, event_id, replica_id, replica_seq, actor_key,
              membership_epoch, envelope_json, accepted_at
       from events where server_order > ? order by server_order asc limit ?`,
      after,
      limit + 1,
    ).toArray();
    const hasMore = rows.length > limit;
    const page = rows.slice(0, limit);
    return json({
      events: page.map(rowToEvent),
      nextCursor: page.at(-1)?.server_order ?? after,
      hasMore,
    });
  }

  private advanceCursor(input: unknown, actorKey: string): Response {
    const body = input as { replicaId?: string; lastServerOrder?: number };
    if (!body.replicaId || !Number.isSafeInteger(body.lastServerOrder) || Number(body.lastServerOrder) < 0) {
      return json({ error: 'replicaId and non-negative lastServerOrder are required' }, 400);
    }
    this.ctx.storage.sql.exec(
      `insert into cursors (actor_key, replica_id, last_server_order, updated_at)
       values (?, ?, ?, ?)
       on conflict(actor_key, replica_id) do update set
         last_server_order = max(cursors.last_server_order, excluded.last_server_order),
         updated_at = excluded.updated_at`,
      actorKey,
      body.replicaId,
      body.lastServerOrder,
      new Date().toISOString(),
    );
    return json({ status: 'advanced', lastServerOrder: body.lastServerOrder });
  }

  private status(): Response {
    const eventCount = this.ctx.storage.sql.exec<{ count: number }>(
      'select count(*) as count from events',
    ).toArray()[0]?.count ?? 0;
    const maxServerOrder = this.ctx.storage.sql.exec<{ value: number }>(
      'select coalesce(max(server_order), 0) as value from events',
    ).toArray()[0]?.value ?? 0;
    const activeMembers = this.ctx.storage.sql.exec<{ count: number }>(
      'select count(*) as count from members where active = 1',
    ).toArray()[0]?.count ?? 0;
    return json({
      healthy: true,
      eventCount,
      maxServerOrder,
      activeMembers,
      connectedSockets: this.ctx.getWebSockets().length,
      membershipEpoch: Number(this.meta('membership_epoch') || '0'),
    });
  }

  private async authorizeMember(request: Request): Promise<string | Response> {
    const token = request.headers.get('x-board-token');
    const actorKey = request.headers.get('x-actor-key');
    if (!token || !actorKey) return json({ error: 'board_token_and_actor_key_required' }, 401);
    const expectedHash = this.meta('board_token_hash');
    if (!expectedHash || !timingSafeEqual(await sha256(token), expectedHash)) {
      return json({ error: 'invalid_board_token' }, 401);
    }
    const member = this.ctx.storage.sql.exec<MemberRow>(
      'select actor_key, role, epoch, active from members where actor_key = ?',
      actorKey,
    ).toArray()[0];
    if (!member || member.active !== 1) return json({ error: 'member_not_active' }, 403);
    return actorKey;
  }

  private isAdmin(request: Request): boolean {
    const supplied = request.headers.get('authorization') || '';
    const expected = `Bearer ${this.env.COORDINATOR_ADMIN_TOKEN || ''}`;
    return expected.length > 'Bearer '.length && timingSafeEqual(supplied, expected);
  }

  private meta(key: string): string | null {
    return this.ctx.storage.sql.exec<{ value: string }>(
      'select value from meta where key = ?',
      key,
    ).toArray()[0]?.value ?? null;
  }
}

function rowToEvent(row: StoredEventRow) {
  return {
    eventId: row.event_id,
    replicaId: row.replica_id,
    replicaSeq: row.replica_seq,
    actorKey: row.actor_key,
    membershipEpoch: row.membership_epoch,
    envelope: JSON.parse(row.envelope_json),
    serverOrder: row.server_order,
    acceptedAt: row.accepted_at,
  };
}

async function readJson(request: Request): Promise<unknown> {
  const contentType = request.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) throw new Error('application/json is required');
  return request.json();
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: JSON_HEADERS });
}

async function sha256(value: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('');
}

function timingSafeEqual(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

function randomToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
}
