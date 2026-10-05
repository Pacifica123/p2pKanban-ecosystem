# Повторяемый запуск на Windows и Linux

## Исправления

| Наблюдение | Решение |
|---|---|
| ReviOS11: Docker сначала был закрыт | Сначала запустить Docker Desktop; использовать Linux containers |
| ReviOS11: backend падает с `migration 1 was previously applied but has been modified` | Portable SQLx runner проверяет точные LF/CRLF-варианты истории; неизвестный checksum по-прежнему блокирует запуск |
| EndeavourOS: `npm ci` → `Exit handler never called!` | Фиксированный Node image из лога, npm 11.9.0, отдельный cache, отключённый install-time audit, видимые postinstall-логи и один повтор временного сбоя |
| При ошибке build нет контейнерных логов | Полный поток Compose сохраняется в `.dev-bootstrap/container-runs` |
| Машинный HTTP proxy мешает loopback readiness | Локальный health-check выполняется напрямую |
| Старый host-native `npm.CMD` не запускался | В текущем `devbootstrap.py` resolver уже исправлен; его использует и дополнительная frontend-build проверка |

`Exit handler never called!` — сообщение аварийного завершения npm, а не
доказательство конкретного DNS/Alpine/buildx-дефекта. Без npm debug log нельзя
назвать единственную причину. Новый install runner выводит хвост npm debug log
до завершения failed Docker layer. Если ошибка повторится, этот лог определит,
нужно ли исправлять доступ контейнера к registry, proxy/DNS или сами зависимости.
Переход на другую ОС сам по себе не является исправлением.

## Обычный запуск после патча

В корне **web/backend-проекта**:

```bash
python bootstrap.py start --no-open
python bootstrap.py status
```

На Linux, где команда называется `python3`, используйте её вместо `python`;
на Windows подходит `py -3`. Не передавайте `--no-build` при первом запуске
после патча: новый migration runner должен попасть в backend image.

Данные и секреты остаются в прежних Docker volumes. `reset --yes`,
`docker compose down -v`, удаление `_sqlx_migrations` и ручная подмена её
checksum для этого исправления не нужны.

Для первичной привязки Android:

```bash
python bootstrap.py start --listen lan
```

Укажите в Android `http://<LAN-IP-компьютера>:<порт-из-bootstrap>`.
`127.0.0.1` на физическом телефоне означает сам телефон. Docker-порты `5432`
и `18080` наружу не публикуются. Если web на компьютере доступен, а с телефона
нет, проверьте доверенную локальную сеть, изоляцию Wi-Fi-клиентов и разрешение
этого TCP-порта в firewall компьютера. Bootstrap не меняет firewall автоматически.

## Если запуск не завершился

```bash
python bootstrap.py doctor
```

Для разбора приложите:

- последний `.dev-bootstrap/container-runs/*_start.log`;
- созданный `.dev-bootstrap/diagnostics/*.json`.

Doctor только читает Docker и migration ledger. Он не стартует контейнеры,
не меняет миграции и не выгружает environment или secret volumes.
Статус `buildx-version: недоступно` сам по себе не означает причину падения:
предоставленный EndeavourOS-лог успешно собрал backend через classic builder.

В разделе migrations:

| Статус | Значение |
|---|---|
| `LF` | Checksum совпадает с каноническим SQL |
| `CRLF-compatible` | Совпадает только Windows-вариант того же SQL; runner сохраняет эту историю |
| `unknown` | SQL действительно отличается либо это иная историческая версия; нужна исходная миграция из старого релиза |
| `missing-source` | В БД есть версия, отсутствующая в запускаемом коде |
| `dirty` | Миграция помечена как незавершённая; требуется отдельное восстановление |

По предоставленным логам подтверждён **сам mismatch**, но LF/CRLF как причина
будет доказана только сравнением с checksum реальной БД. При `unknown` не
удаляйте данные: сохраните backup и найдите SQL/образ той версии, которой была
создана БД. Текущий патч намеренно не принимает неизвестные изменения SQL.

## Как сохраняется история SQLx

Все новые миграции исполняются с LF независимо от checkout. Для уже применённой
миграции выбирается только вариант текущего SQL, чей SHA-384 точно совпал с БД:
LF либо CRLF. Старые строки `_sqlx_migrations` не переписываются, SQL повторно
не исполняется. Проверки dirty/missing/checksum остаются в SQLx.

Выбор и запуск происходят под одним SQLx advisory lock на одном соединении.
Соединение отделено от pool, поэтому отмена/ошибка не возвращает заблокированную
сессию в pool. `.gitattributes` дополнительно закрепляет LF для `.sql` и `.rs`.

Старый backend без portable runner при откате к CRLF/LF-несовместимой сборке
может снова отклонить историю. Его SQLx ledger не был изменён этим патчем;
для такого отката нужен прежний совместимый image либо portable runner.

## Проверки

Без Docker:

```bash
python -B tools/test_portable_startup.py
python -B tools/check_zero_config_bootstrap.py
python -B tools/devbootstrap.py self-check
node --test deploy/bootstrap/npm-install.test.mjs
```

Последняя команда нужна только разработчику, у которого установлен Node.
Она проверяет реальные дочерние процессы npm через управляемый fake executable:
один повтор transient-сбоя, остановку permanent-сбоя и неизменность lockfile.

Полный тест SQLx/PostgreSQL с установленным Docker:

```bash
python -B tools/check_portable_migrations.py
```

Он создаёт отдельные image/container/network со случайными именами, не
публикует порты и не подключает volumes приложения. Проверяет реальное создание
CRLF-истории, последующие LF-миграции, два одновременных старта, повторный запуск,
сохранение marker-данных и отказ от неизвестного checksum/dirty migration.
Все ресурсы этого теста удаляются в конце. Первая компиляция Rust требует сети
и может занять несколько минут.

Сборка production images отдельно:

```bash
python -B tools/check_production_images.py
```

Финальный полевой критерий: на ReviOS11 и EndeavourOS доступны web и
`/api/v1/health`, работают вход и создание карточки, после `stop`/`start`
карточка остаётся; Android проходит первичную привязку по LAN-адресу. На
существующей Windows-БД это проверяется с прежним data volume.

Технические основания: [SQLx 0.8.6 Migrator](https://docs.rs/sqlx/0.8.6/sqlx/migrate/struct.Migrator.html),
[npm install configuration](https://docs.npmjs.com/cli/v11/using-npm/config/),
[Windows batch launchers in Node](https://nodejs.org/api/child_process.html#spawning-bat-and-cmd-files-on-windows).
