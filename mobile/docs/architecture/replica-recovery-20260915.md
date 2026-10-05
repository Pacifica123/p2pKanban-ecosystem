# p2pKanban: восстановление независимой реплики

Дата: 2026-09-15. База: web `8fbdae9`, Android `9c4cac7`; сравнение: web `11d8524`, Android `7a89518`. Версия приложения остаётся 2.0.0, Android versionCode повышен до 22.

**Это исправление зависимости уже подготовленных досок от HTTP-узла. Полный TARGET MODEL для всего пространства пока не достигнут.** Каталог новых досок и универсальная репликация структуры остаются незавершёнными; патчи не следует интерпретировать как решение этих ограничений.

## 1. Причины и хронология

Архивы являются снимками, без Git-истории. Поэтому точный introducing commit установить нельзя. Обе сравнительные v1-версии декларируют версию 1.0.0. ADR-007 от 2026-07-28 уже требует независимых реплик, локального журнала, подтверждений relay вместо подтверждения другого пользовательского устройства.

Сравнение байтов показало: `localFirst/delivery.ts`, `roaming/primeBoards.ts`, `roaming/merge.ts` и `roaming/storage.ts` одинаковы в сравнительном Android v1 и приложенном текущем Android. Следовательно, часть регрессионной модели уже присутствовала в удачном v1-снимке, хотя не обязательно проявлялась в его условиях эксплуатации. Приписывать её появление исключительно v2 было бы неверно.

| Причинная цепочка | Следствие | Исправление |
| --- | --- | --- |
| v1: локальный snapshot + capability + зашифрованные relay-события позволяют читать без ПК → delivery сохраняет `relay_pending` до HTTP-проекции | Другой peer фактически становится обязательным подтверждающим сервером | Устойчивая локальная запись события; relay ACK завершает публикацию, получения всеми peers не обещает |
| Подготовка каждой доски снова вызывает `provisionRoamingBoard` до проверки сохранённых данных | На мобильной сети требуется LAN-адрес ПК; подготовка не проходит | Сначала установленный capability и локальный snapshot; при отсутствии snapshot — relay |
| HTTP refresh 401/403 вызывает очистку session-bound storage | Истечение HTTP-токена стирает независимую реплику и очередь | HTTP-сессия перестала определять сохранность реплики; явный выход и смена пользователя остаются отдельными действиями |
| Параллельные первые подготовки читают пустой SecureStore и создают разные device keys; параллельные записи теряют элементы capability-index | Часть досок привязана к ключу, которым устройство уже не подписывает | Единственный in-flight create ключа; последовательные записи capability-index |
| Событие отмечается seen без исходного snapshot; отдельные inbox/projection записи не атомарны | Поздний baseline не восстанавливает пропущенную операцию | Единый journal с seed, событиями, pending и часами; повторная материализация при поздних предпосылках |
| Backend конструирует содержимое outbox из актуального состояния при каждой отправке; собственные версии узнаёт через loopback | Один eventId может означать разные значения; локальная запись проигрывает неверно | Новая миграция фиксирует событие и версии полей в транзакции изменения; повтор отправляет сохранённое событие |
| Backend не публиковал собственный baseline; стартовый backfill мог переиздавать импортированное состояние | Для восстановления нужна HTTP-подготовка Android; возникает новое ложное намерение при рестарте | Устойчивые baseline известной доски; backfill только без предшествующих событий |
| v2: ограниченный срок delegation применяется к продолжающейся репликации | Устройство вынуждено регулярно обращаться к выдавшему право peer | Срок ограничивает новое подключение; состоявшееся подключение действует в capability epoch, без живого issuer |
| React Native сообщает одинаковую cancellation при разных причинах, deadline не полностью объяснён UI | `fetch request has been canceled` маскирует timeout/уход экрана | Различены TIMEOUT, CANCELED и NETWORK_ERROR; deadline включает чтение body |

Из v1 сохранены формат `p2p-kanban-roaming/1`, Nostr kinds, XChaCha20-Poly1305, подписи, board capabilities и сравнение версий `(logicalClock, replicaId, eventId)`. Восстановлены свойства ADR-007, а не выполнен wholesale rollback. Изменения portable bootstrap, Markdown, Obsidian, priority и devctl-интеграции не откатывались.

## 2. Фактическая архитектура после изменения

Android владеет локальным snapshot и журналом операций. В существующей PostgreSQL-реплике web продолжает обращаться к своему backend; этот backend является peer. Relay переносит подписанные зашифрованные данные и хранит их по своим условиям, но не выполняет merge и не определяет истину.

### Жизненный цикл известной доски

1. Первое получение права: существующий HTTP enrollment либо уже имеющийся device-link передаёт capability/key. Без ключа расшифровка невозможна; это не зависимость от доступности конкретного ПК после подключения.
2. `prepare/open`: если capability и данные сохранены, обращение к ПК не требуется. Если есть ключ, но нет snapshot, Android может восстановить опубликованный relay-baseline.
3. `create/update/delete`: для карточек, checklist и appearance сначала сохраняется неизменяемое событие и локальный результат. Часы продвигаются за полученные версии. Сетевая отправка не удерживает блокировку локального UI-хранилища.
4. `outbox`: отправляет journal pending. Неуспех relay оставляет данные локально; следующая попытка использует тот же eventId и в Android тот же подписанный ciphertext. Кворум ACK относится только к публикации.
5. `inbox/merge`: Android сохраняет полученные события вместе в journal и материализует их повторно. Поздний baseline не теряет ранее полученные delta. Baseline переносит версии и свидетельства удаления. Backend применяет поддерживаемые события к собственной PostgreSQL-реплике.
6. В активном Android-экране flush/pull возобновляются периодически и при возвращении приложения на передний план. Постоянный Android background service не добавлен.

Потерянный или устаревший HTTP-токен не уничтожает ключи и данные. Это не разрешает выполнять закрытые HTTP-запросы без авторизации. Отзыв доступа остаётся вопросом capability epoch. Правила нового pairing/expiry/replay сохранены; для продолжающейся репликации цепь проверяется на момент состоявшегося enrollment. Старые backend-записи, отклонённые проверкой авторизации, допускают повторную проверку после исправления, вместо вечного пропуска по eventId.

### Фактические файлы

Android: `roaming/journal.ts`, `service.ts`, `merge.ts`, `storage.ts`, `primeBoards.ts`; `localFirst/useLocalBoard.ts`, `repository.ts`, `delivery.ts`; `auth/AuthProvider.tsx`; `shared/api/client.ts`; `deviceLink/protocol.ts`; тексты Boards/BoardScreen, versionCode и contract-check. Добавлены regression-тесты журнала, HTTP-сессии, SecureStore, HTTP cancellation; обновлены тесты delivery/delegation.

Web: **новая** `backend/migrations/0020_replica_event_journal.sql`; `backend/src/transports/roaming.rs`; выдача capability в `modules/sync/service.rs`; проверка delegation и signed_at в `crates/nostr-transport`. Старые SQL-миграции не редактировались. SQL-триггер фиксирует исходное событие и field versions; baseline строится одной MVCC-командой вместе с версиями. Для старой незамороженной очереди создаётся новый eventId: восстановить её первоначальное содержимое из текущих строк доказуемо нельзя.

## 3. Проверки

Актуальные машинные результаты находятся в приложенном архиве evidence. Ни один mock-тест ниже не выдается за испытание на физическом Android или публичном relay.

- Android TypeScript и contract-check; Jest: локальная очередь/relay, merge, ключи, HTTP 401/403, cancellation, delegated membership и остальной существующий набор.
- PostgreSQL: PGlite 0.3.14 исполняет все 20 реальных миграций. Проверены atomic commit/rollback события и версий, неизменность retry, восстановление старого outbox с новым eventId, шаг часов после будущего peer clock, lifecycle checklist и отсутствие echo импортированной activity.
- Совместимость: реальное событие SQL-триггера помещено в общий fixture; проверяется Rust codec и Android signed/encrypted relay ingestion.
- Web production build и Expo Android Hermes export. Expo export не является сборкой APK.
- Rust backend + nostr-transport unit tests, включая codec/delegation. Тест с настоящим отдельным PostgreSQL и рестартом требует disposable DB; его пропуск указывается в evidence.
- Devctl: отдельная чистая копия каждого исходного архива → plan → start без push → сравнение каждого payload-файла побайтно → чистый Git. Проверки в manifest автономны от npm/Cargo dependencies; расширенные команды ниже выполняются отдельно.

Команды расширенной проверки из соответствующего проекта:

```sh
# Android
npm ci
npm run typecheck
npm run check:contract
npm test
npm run export:android

# Web/backend
cargo test --locked --features nostr-shadow --lib -p p2p-planner-backend -p p2p-kanban-nostr-transport
npm ci --prefix backend/tests/regression
node backend/tests/regression/replica-journal.mjs
# cargo запускается из backend; команды npm выше — из корня web
```

## 4. Acceptance matrix

PASS означает только указанный проверенный слой; OPEN — необходимый непроверенный сценарий; FAIL — известный пробел реализации.

| Сценарий | Статус | Evidence / граница |
| --- | --- | --- |
| P offline, A открывает/готовит уже синхронизированную доску | PASS (deterministic) | primeBoard с сохранёнными capability/snapshot, HTTP и relay недоступны |
| P offline, A создаёт/меняет поддерживаемые данные, не ждёт P | PASS (deterministic) | journal commit, reload, отказ relay, последующий flush; HTTP mock запрещён |
| A меняет → второй peer приходит позже | PASS (модель двух Android-реплик); OPEN (нативный PC end-to-end) | Раздельное хранилище peers + общие подписанные relay-события; отдельно SQL и Rust tests |
| P публикует → выключается → A читает relay | PASS (protocol/fixture); OPEN (реальная сеть) | SQL-generated event → шифрование/подпись → Android ingestion; delta-before-baseline regression |
| Временное расхождение → одинаковый merge | PASS (deterministic, поддерживаемые поля) | Два раздельных журнала, обратный порядок доставки, Lamport step |
| Relay недоступен → локальная работа → восстановление | PASS (deterministic) | Pending переживает reload, точный signed event повторяется после восстановления |
| A на мобильном интернете вместо LAN | OPEN (устройство/оператор); PASS (отсутствие HTTP в подготовленном пути) | Реальный телефон и операторская сеть здесь не запускались |
| HTTP-session expiry не уничтожает данные | PASS (React provider tests) | 401 и 403: authenticated local state, clearSessionBoundStorage не вызывается |
| Объяснимая cancellation и восстановление | PASS (RN-style mocks); OPEN (нативный lifecycle) | Timeout, caller abort, зависший response body, следующий успешный запрос |
| Новая доска/изменение структуры на любом peer появляется у остальных | FAIL | Нет полного workspace catalog/structure replication; backend пропускает board.snapshot |
| Все данные пространства доступны для автономного multi-writer CRUD | FAIL | Board/column/catalog, comments, labels, роли не покрыты данным roaming-журналом |
| Нативный APK + несколько реальных peers/relay + restart/concurrent SQL writes | OPEN | Expo bundle и unit/PGlite-проверки не заменяют этот прогон |

## 5. Оставшиеся технические долги

1. **Workspace catalog и структурные операции**: создание/удаление досок и колонок, discovery ключей новых досок, комментарии, labels и права требуют общего реплицируемого протокола. Это реальный незакрытый участок TARGET MODEL, а не повод назначать PC постоянным сервером. Минимальное продолжение — подписанный workspace catalog с передачей новых board capabilities доверенным peer identities и отдельными стабильными операциями структуры; использовать существующий encrypted transport.
2. Backend пока игнорирует `board.snapshot`: восстановление новой PostgreSQL-реплики идёт через существующий node-link; relay-baseline используется Android. Recovery произвольной новой PC-реплики только из relay пока не обеспечен.
3. Journal пока не компактизируется; relay history/retention и размер сообщения ограничивают длительное восстановление. Baseline не разбит на чанки. Для больших досок нужен chunked baseline с manifest и безопасная compaction, без потери tombstones/версий. Существующие локальные Android seed не получают полный structural merge новых snapshots.
4. Старые версии могли публиковать разные payload под одним eventId. Первоначальное намерение нельзя восстановить из отсутствующего журнала; патч предотвращает новые случаи, но не реконструирует любую повреждённую историю. Операции со старым epoch сохраняются с диагностикой, а не молча переиздаются новым ключом.
5. Полная работа в Android background/Doze, реальные публичные relay и мобильные операторы, конкурентные SQL-записи разных backend-процессов требуют отдельного интеграционного прогона. ACK relay не гарантирует вечного хранения или немедленного получения всеми peers.
6. Новая интерпретация expiry должна быть развёрнута на всех участвующих репликах. Старые клиенты могут продолжать требовать подтверждение/отбрасывать события по истёкшему delegation. Распространение нового access epoch на долго отсутствовавшие устройства всё ещё ограничено существующим provisioning-механизмом.

## 6. Применение

Патчи рассчитаны именно на web `8fbdae9` и Android `9c4cac7`, приложенные к аудиту. Это не патчи поверх сравнительной v1. В каждом workspace положить соответствующий ZIP в `patches`, выполнить `devctl plan`, затем `devctl start`. Не применять Android payload в web-проект.

После web-патча обычный `python bootstrap.py start` запускает обновление. `--no-open` не обязателен: он лишь отключает автоматическое открытие браузера. Данные не требуют reset. Миграция 0020 добавляет таблицу/поля/триггеры; история применённых миграций не переписывается. Для Android собрать APK штатным `npm run apk` и обновить установленное приложение без очистки данных.
