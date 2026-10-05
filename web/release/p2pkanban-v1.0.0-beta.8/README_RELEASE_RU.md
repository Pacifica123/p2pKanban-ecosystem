# p2pKanban v1.0.0-beta.8

Этот ZIP обновляет web/backend до beta.8 и исправляет межузловое удаление
карточек. Перед проверкой обновите оба web-узла. Для Android используйте
`1.5.0-mobile.6`.

## Установка

```bash
python bootstrap.py update --source-dir .
python bootstrap.py start --listen lan
```

Миграция `0014` выполняется автоматически. Она создаёт tombstone для старых
soft-delete записей и отправляет их через roaming outbox.

## Smoke

- локальное скрытие не влияет на второй узел;
- возврат из «Скрытые здесь» работает на исходном узле;
- глобальное удаление исчезает на втором узле после reconnect;
- повторный `card.put` не воскрешает tombstoned карточку.
