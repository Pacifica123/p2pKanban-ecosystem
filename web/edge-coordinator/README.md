# Edge coordinator p2pKanban

Небольшой совместимый coordinator на Cloudflare Durable Object. Он хранит
только:

- активный состав участников и membership epoch;
- dedupe по `eventId` и `(replicaId, replicaSeq)`;
- возрастающий `serverOrder`;
- cursor каждой replica;
- компактный JSON event log;
- hibernatable WebSocket sessions.

Карточки, колонки, настройки внешнего вида, PostgreSQL-таблицы и merge policy
здесь не хранятся.

## Локальные проверки

```bash
npm ci
npm run typecheck
npm test
```

## Первое развёртывание

```bash
npx wrangler secret put COORDINATOR_ADMIN_TOKEN
npm run deploy
```

Примеры provision и запросов находятся в
`docs/deployment/free-hosting-transports-v1.md`. Admin token и board tokens
нельзя записывать в `wrangler.jsonc`.

Сервис пока не проверяет асимметричную подпись каждого события и поэтому
остаётся экспериментом совместимости, а не заменой основного backend.

