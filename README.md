# launcher-feed

Служебная ветка лаунчера экосистемы. Её целиком, одним коммитом без истории,
перезаписывает GitHub Action `.github/workflows/launcher-apk-feed.yml` из
`main`. Руками не править, в `main` не сливать.

`apk.json` (`p2p-kanban-launcher-apk-feed/1`) — последняя готовая APK из EAS,
сборка, которая идёт сейчас, и последний коммит `main` по `mobile/` с
признаком, вошёл ли он в эту APK. Описание — `launcher/feed/README.md` в `main`
и E-ADR-004 п.6.
