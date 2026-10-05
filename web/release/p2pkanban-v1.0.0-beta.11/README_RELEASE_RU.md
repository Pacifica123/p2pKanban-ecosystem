# p2pKanban v1.0.0-beta.11

Совместимый Android-клиент: `1.5.0-mobile.9`.

## Запуск

```bash
python bootstrap.py
```

Работающая beta.10 на loopback может предложить этот commit в web. Обновление
из UI и `python bootstrap.py update` используют один backup/rollback pipeline,
а stable gateway сохраняет прежний URL и порт.

## Главное

- колонка — единственное состояние карточки, фиксированный status удалён;
- Android card details: имя колонки, 0–4 звезды приоритета и облегчённые чек-листы;
- оформление доски передаётся между web/Android через coordinator и relay;
- tombstone-aware слияние не затирает свежие checklist items старым snapshot;
- backend параллельно получает roaming-доски вместо суммы timeout;
- web восстанавливает access token одним refresh и не создаёт 401 storm;
- card details в обоих клиентах наследуют board palette.

APK не обновляется из source автоматически: для этого нужен заранее
подписанный build с тем же key и подтверждение Android installer либо
совместимый OTA runtime.

Полные изменения: `docs/product/v1.0.0-beta.11-release-notes.md`.
