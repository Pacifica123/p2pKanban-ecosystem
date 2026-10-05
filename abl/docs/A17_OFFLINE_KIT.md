# A17 — AppImage и комплект для работы без сети

Основной канал установки Arch-клиента — пакет pacman из A15. AppImage — запасной
канал запуска и A16-восстановления. Он не устанавливает пакет, не обновляет pacman,
не пишет в `/usr`, не включает автозапуск и не меняет пути XDG-профиля.
Закройте другой экземпляр перед восстановлением: обе версии используют тот же flock.
AppImage не делает Android/relay-транспорт ABL реализованным: ограничения A10/A11 остаются.

## Если комплект уже получен

Для проверки нужны Python 3.12+, GPG и **доверенный экземпляр** `a17_release_kit.py`
(или `verify-kit.py`, предварительно полученный по доверенному каналу).
Отпечаток публичного ключа, минимальный номер выпуска и ожидаемую версию получите
от автора отдельно от комплекта. Ключ внутри комплекта сам по себе не создаёт доверие.
Номер выпуска должен быть не меньше последнего принятого; подпись не запрещает
повтор старого выпуска без этого отдельно сохранённого ограничения.

```bash
python3 /trusted/a17_release_kit.py verify --kit /path/offline-kit \
  --fingerprint FULL_TRUSTED_FINGERPRINT --minimum-release 17 --expected-version 0.1.0
python3 /trusted/a17_release_kit.py run --kit /path/offline-kit \
  --fingerprint FULL_TRUSTED_FINGERPRINT --minimum-release 17 --expected-version 0.1.0
```

Если отсутствует FUSE, явно выберите распаковку и запуск:

```bash
python3 /trusted/a17_release_kit.py run --kit /path/offline-kit \
  --fingerprint FULL_TRUSTED_FINGERPRINT --minimum-release 17 --expected-version 0.1.0 --extract
```

Проверка подписи, полного состава, размеров и SHA-256 выполняется до запуска.
Для исполнения создаётся приватная временная копия; исходный комплект не изменяется.
Распаковка запускает только уже проверенный AppImage. Она не требует установки FUSE.
При ошибке обычного запуска автоматической повторной попытки нет: ошибка WebView
сама по себе не означает проблему FUSE или повреждённую базу.

Для восстановления передайте команду A16 после `--`:

```bash
python3 /trusted/a17_release_kit.py run --kit /path/offline-kit \
  --fingerprint FULL_TRUSTED_FINGERPRINT --minimum-release 17 --expected-version 0.1.0 --extract -- doctor --json
```

Далее используйте `backup`, `backups`, `safe-mode`, `safe-export` или
`restore BACKUP_ID --yes`, как описано в `A16_RECOVERY.md`. Установка старого AppImage
не откатывает данные: схему проверяет A16, восстановление требует явного согласия.
Пользовательские данные и секреты не входят в установочный комплект.

## Сборка выпуска автором

Патч содержит инструменты, а не готовый проверенный бинарный выпуск. Сначала выполните
канонический UTS. A15 подготовит `a15-release-inputs` с точным Cargo.lock и исходниками.
Нужен совместимый установленный `cargo-tauri 2.x`, Rust, Node и системные build-зависимости
Tauri/WebKitGTK. Эти инструменты нужны только на машине сборки.

```bash
python3 tools/a17_build_appimage.py --release-inputs /path/a15-release-inputs \
  --output /path/new-appimage-build --allow-network
```

Сборка идёт в временном каталоге из проверенного A15-архива. Сохраняются AppImage,
лог и `build-record.json`, связывающий образ с исходниками и конфигурацией упаковки.
Без `--allow-network` npm/Cargo используют локальные кэши; вспомогательные инструменты
Tauri должны быть заранее подготовлены. Комплект обеспечивает офлайн-**запуск**, а
не обещает офлайн-сборку на пустой машине.

После реальных проверок AppImage создайте подписанный комплект. Используется уже
настроенный внешний gpg-agent; приватный ключ не копируется.

```bash
python3 tools/a17_release_kit.py stage --appimage /path/new-appimage-build/p2pkanban.AppImage \
  --build-record /path/new-appimage-build/build-record.json \
  --release-inputs /path/a15-release-inputs --signing-key FULL_SIGNING_FINGERPRINT \
  --release-sequence 17 --build-baseline 'Recorded distro, glibc, WebKitGTK and host results' \
  --output /path/new-offline-kit
```

Переносите каталог целиком. В нём: AppImage, подписанный манифест, публичный ключ,
исходный A15-архив, PKGBUILD/desktop/license, метаданные сборки, проверяющий инструмент
и инструкция восстановления. Нет БД, кэша аккаунта, приватных ключей или паролей.
Инструмент не перезаписывает существующий каталог выпуска.

## Проверки и границы поддержки

`python3 -B tools/check_a17.py` проверяет подпись с временным тестовым ключом,
повреждение каждого файла, неверный ключ, подменённый манифест, неполный комплект,
символические ссылки, неверную версию и повтор старого выпуска. Тестовые данные
не являются настоящим AppImage и не доказывают работу WebKitGTK/FUSE.

Для настоящего образа:

```bash
python3 tools/a17_host_appimage_probe.py --kit /path/offline-kit \
  --fingerprint FULL_TRUSTED_FINGERPRINT --minimum-release 17 --expected-version 0.1.0 \
  --report /path/appimage-host.json
```

Этот отдельный probe проверяет CLI doctor в FUSE и extract/run режимах на свежем
временном XDG-профиле. Оба режима должны пройти для полного A17-acceptance.
Дополнительно вручную проверьте окно, локальные изменения и reopen без сети,
A16-восстановление на копии профиля, Wayland/X11, Secret Service и отсутствие изменений pacman.

Поддержка: только x86_64 и фактически проверенные версии Arch/EndeavourOS/Manjaro.
AppImage сохраняет ограничения glibc/драйверов/WebKitGTK: сборка на более новой системе
не гарантирует запуск на старой. Не отключайте sandbox WebKitGTK для обхода ошибок.
Публичный выпуск требует завершения лицензионного решения A15. A18 — следующий этап:
измерения производительности и проверка rolling-release переходов.
