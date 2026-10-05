# Полевые проверки и продолжение v1

- Актуально на: 2026-08-23
- Базовая линия: `v1` (`1.0.0`)

## Закрыто функционально

- [x] Web CRUD workspace/board/column/card.
- [x] Метки, чек-листы, комментарии, activity и audit.
- [x] Web local snapshot и очередь карточек.
- [x] Backend push/pull baseline и roaming transport.
- [x] Export, preview и board import-as-copy.
- [x] Zero-config Docker bootstrap, update и rollback кода.
- [x] Native auth и Android-клиент.
- [x] Базовый Android CRUD и перенос карточек между колонками.
- [x] Исправление направления Android → backend → web.
- [x] Актуальная карта документации и универсальная концепция GitHub/devctl.
- [x] Явный перенос identity и owned-досок на чистый второй web-узел.
- [x] Разделение «Скрыть здесь» и tombstone-удаления «Удалить везде» для
  web/Android, включая migration backfill старых `deleted_at`.
- [x] Entity-delta для checklist roaming, защита от устаревших snapshot и
  фильтрация ложной activity.
- [x] Relay-first для подготовленной Android-доски в мобильной сети и экраны
  версий web/Android/backend.
- [x] Локальные per-card reminders в web и Android без cross-device sync.
- [x] Android v1 применяет переносимые настройки оформления web через coordinator/relay.
- [x] Column-state заменяет фиксированный status карточки во всех активных контрактах.
- [x] Checklist snapshot merge учитывает элементы и tombstone, backend relay pull выполняется конкурентно.
- [x] UI updater `main` через loopback control plane и стабильный gateway/порт.

## Обязательное полевое подтверждение v1

- [ ] Выполнить два последовательных
  `python -B tools/devbootstrap.py release-gates --profile full-local-release`
  на одном чистом commit.
- [ ] Собрать release ZIP из точного тега через
  `python tools/build_release_bundle.py --require-tag`.
- [ ] Проверить распакованный ZIP на чистой Windows-машине.
- [ ] Проверить тот же ZIP на Linux.
- [ ] Подтвердить сохранение данных после stop/start, update и rollback.
- [ ] Выполнить PostgreSQL backup/restore drill по runbook и сверить counts.
- [ ] Пройти cross-client матрицу web → Android и Android → web для create,
  edit, move, archive, global delete и checklist CRUD.
- [ ] Пройти web → web матрицу на Linux/Windows: initial link, edit, move,
  archive, local hide/restore, global delete и checklist CRUD в обе стороны
  через общий relay.
- [ ] Установить Android v1 поверх mobile.9 и проверить сохранение локальных
  данных, немедленный Back во время загрузки и повторное открытие доски.
- [ ] Подтвердить import-as-copy smoke на итоговом bundle.
- [ ] Проверить ZIP на секреты, `.env`, локальные БД и generated-каталоги.
- [ ] Выбрать публичную лицензию либо явно зафиксировать отсутствие лицензии.
- [ ] После исправлений повторить gates и сохранить evidence bundle с
  контрольными суммами.

## Полезное полевое доказательство, но не замена release gates

- Продукт используется владельцем с `beta.3`; серьёзных потерь данных не
  замечено.
- Stop/start и обычная работа выглядят устойчиво в реальном сценарии.
- Это снижает риск, но не заменяет воспроизводимый update/rollback/restore
  прогон точного v1 commit.

## Будущие продуктовые срезы

- GitHub/devctl и другие внешние интеграции;
- coordinator-free режим;
- Iroh в браузере;
- MFA/passkeys;
- E2EE локальных snapshot;
- merge/destructive import;
- AppImage и отдельный Windows `.exe`.

Отдельного stable-канала больше нет. Этот список остаётся evidence-картой для
текущей линии и не откладывает пользовательское имя v1.
