# Лента APK лаунчера

`p2p-kanban-launcher-apk-feed/1` — как лаунчер узнаёт ссылку на свежий APK
Android и замечает, что в `mobile/` есть коммит без новой сборки.
Решение — [E-ADR-004](../../docs/ecosystem/adr/E-ADR-004-ecosystem-launcher.md) п.6.

```text
eas build (John) ──► EAS (expo.dev)
                         ▲  GraphQL, токен из секрета EXPO_TOKEN
GitHub Action launcher-apk-feed ──► ветка launcher-feed: apk.json
                                         ▲  raw.githubusercontent.com, без токена
                                     лаунчеры
```

## Что нужно сделать один раз

1. На expo.dev: Account settings → Access tokens → Create token (personal access token).
2. В репозитории GitHub: Settings → Secrets and variables → Actions → New repository
   secret, имя `EXPO_TOKEN`, значение — токен.
3. Settings → Actions → General → Workflow permissions: «Read and write
   permissions» (или оставить как есть, если workflow-у разрешено задавать
   `permissions: contents: write` самому).
4. Actions → launcher-apk-feed → Run workflow. Дальше лента обновляется сама:
   после каждого push в `main`, менявшего `mobile/`, и раз в 20 минут.

Токен не попадает ни в репозиторий, ни в ленту, ни на машины с лаунчером.

## apk.json

| Поле | Что |
|---|---|
| `schema` | `p2p-kanban-launcher-apk-feed/1` |
| `generatedAt` | когда Action спросил EAS |
| `repository`, `project` | откуда: `ecosystem.json#repository` и `mobile.eas` |
| `buildsPage` | страница сборок проекта на expo.dev |
| `mobileHead` | последний коммит `main`, менявший `mobile/`: `sha`, `date`, `subject` |
| `latest` | последняя завершённая Android-сборка профиля с `.apk`: `id`, `appVersion`, `versionCode`, `gitCommit`, `createdAt`, `completedAt`, `expiresAt`, `apkUrl`, `page` |
| `building` | самая новая сборка в `NEW`, `IN_QUEUE`, `IN_PROGRESS` или `null` |
| `lastFailed` | упавшая сборка новее `latest` или `null` |
| `fresh` | входит ли `mobileHead` в историю `latest.gitCommit`: `true`, `false`; `null` — коммит сборки неизвестен `main` (собрано из локальных правок) |
| `error` | почему ленты нет или она неполная: нет секрета, EAS не ответил |

## Что показывает лаунчер

| Вердикт | Когда |
|---|---|
| свежий APK | `fresh: true`, и лента видела последний коммит `mobile/` в `main` |
| ожидайте APK | в `mobile/` есть коммит новее сборки, и ничего не собирается |
| собирается | сборка идёт |
| ссылка истекла | у последней сборки истёк срок хранения в EAS |
| сборок ещё нет | в EAS нет завершённых Android-сборок профиля |
| свежесть неизвестна | ленты нет (Action не запускался, нет сети) или коммит сборки неизвестен; карточка ведёт на страницу сборок |

Запасной путь: если на машине задан `EXPO_TOKEN`, а ленты нет, лаунчер
собирает её сам тем же `apk_feed.py`.
