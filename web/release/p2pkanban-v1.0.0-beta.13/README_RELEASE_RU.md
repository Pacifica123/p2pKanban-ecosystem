# p2pKanban v1.0.0-beta.13

Recovery-релиз для legacy Docker deployment.

- Усыновляет работающий beta.10 stack без перезапуска контейнеров.
- Сохраняет порт, PostgreSQL data и deployment secrets volumes.
- Переносит controller из `UserTestSpace` в постоянный runtime root.
- Возвращает корректную GitHub-плашку и UI update на текущем web-порту.

Применение выполняется devctl-патчем. Полные изменения:
`docs/product/v1.0.0-beta.13-release-notes.md`.
