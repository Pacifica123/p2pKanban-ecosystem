# Домашний coordinator через Tailscale

Профиль запускает Rust backend и PostgreSQL на старом Linux-ноутбуке или
мини-ПК. Наружу доступна только сеть Tailscale; PostgreSQL не имеет host-порта.

## Запуск

```bash
cd deploy/home-coordinator
cp home-coordinator.example.env runtime.env
# Заполните runtime.env и никогда не добавляйте его в Git.
docker compose --env-file runtime.env up -d --build
```

Если auth key не задан:

```bash
docker compose --env-file runtime.env exec tailscale tailscale up
```

Покажите API через Tailscale HTTPS, чтобы secure refresh cookies продолжали
работать:

```bash
docker compose --env-file runtime.env exec tailscale \
  tailscale serve --bg --https=443 http://127.0.0.1:18080
```

Клиенты настраиваются на адрес:

```text
VITE_API_BASE_URL=https://p2p-kanban-home.<tailnet-name>.ts.net/api/v1
```

## Резервное копирование

Volume `postgres_data` содержит каноническое состояние coordinator. Делайте
backup через `pg_dump` и отдельно проверяйте восстановление. Tailscale volume
не является backup данных доски.

Nostr shadow можно включить на той же машине через `NOSTR_*` в `runtime.env`,
минимум три независимых relay и `NOSTR_SHADOW_ENABLED=true`. Он не заменяет
PostgreSQL backup, пока полностью не пройдена проверка восстановления из
`docs/deployment/free-hosting-transports-v1.md`.

