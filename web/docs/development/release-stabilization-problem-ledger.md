# Реестр семейств проблем релиза

Стабильные ID не дают проекту каждый раз заново открывать одну и ту же проблему
под другим stacktrace.

## Семейства

| ID | Область | Смысл |
|---|---|---|
| `REL-ENV` | Среда | ОС, shell, tool, path, permissions |
| `REL-DB` | PostgreSQL | Сеть, auth, права, миграции, disposable DB |
| `REL-PROC` | Runtime | PID, порт, readiness, cleanup |
| `REL-BE` | Backend | Rust/backend product или test failure |
| `REL-FE` | Frontend | Dependencies, build, unit/integration |
| `REL-BROWSER` | Legacy browser | Playwright/cache/install prerequisites |
| `REL-UIUX` | UI evidence | Runner, scenario, runtime или assertion |
| `REL-SMOKE` | Smoke | Идемпотентность и write safety |
| `REL-DOC` | Документация | README, version, release contract |
| `REL-DEVCTL` | Patch flow | Patch, archive, check, push |
| `REL-SEC` | Безопасность | Secret leak, redaction, unsafe artifact |
| `REL-UNMAPPED` | Неизвестно | Временное состояние до классификации |

## Актуальные заметки

- Playwright failures остаются legacy infrastructure signals.
- Обязательный UI-сигнал перенесён в custom UIX runner.
- `.dev-bootstrap` не должен попадать в source snapshots.
- Release ZIP проходит отдельную проверку секретов.
- Нерусифицированная или устаревшая активная документация относится к
  `REL-DOC`.

## Правила

- повторяющийся сбой получает ID до случайной правки продукта;
- `REL-UNMAPPED` не является окончательным решением;
- blocker имеет owner layer, evidence path и next probe;
- accepted gap объясняет, почему он не блокирует и когда пересматривается;
- per-run ledgers находятся в evidence bundle, а не коммитятся.

