# p2pKanban v1.0.0-beta.10

Совместимый Android-клиент: `1.5.0-mobile.8`.

## Запуск

```bash
python bootstrap.py
```

После запуска web сам предложит следующий commit `main`. Обновление из UI и
`python bootstrap.py update` используют один и тот же backup/rollback pipeline.
Внешний порт остаётся за stable gateway; при переключении появляется progress
или maintenance page на прежнем URL.

## Главное

- локальное напоминание на карточку в web и Android;
- Android применяет web-палитры, акцент, wallpaper и display settings;
- immutable commit SHA после согласия пользователя;
- `pg_dump`, versioned images, core data counts и rollback;
- никакого Docker socket внутри web/backend;
- закреплённый порт не смещается без явного `--port`.

APK не обновляется из source автоматически: для этого нужен подписанный build
с тем же key и подтверждение Android installer либо совместимый OTA runtime.

Полные изменения: `docs/product/v1.0.0-beta.10-release-notes.md`.
