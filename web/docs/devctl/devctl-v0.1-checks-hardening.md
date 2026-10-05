# devctl v0.1 — усиление проверок

- Статус: историческая заметка проектного `tools/devctl.py`

Версия v0.1 сохранила команды:

```bash
python tools/devctl.py status
python tools/devctl.py start
```

## Что изменилось

- `status` показывает версию;
- при одновременных изменениях `tools/` и `docs/devctl/` выводится подсказка об
  обновлении bootstrap;
- ошибка `requiredCommands` называет конкретный check;
- непустые `setup` и `services` отклоняются, а не игнорируются;
- commit trailer содержит `Devctl-Version`.

## Что не входило

- установка dependencies;
- запуск backend/frontend;
- автоматический rollback;
- merge/rebase/pull расходящихся веток.

## Минимальная проверка

```bash
python -m py_compile tools/devctl.py
python tools/devctl.py status
```

Успешный поток: pre-archive → apply → checks → post-archive → commit → push →
state/report.

Актуальный универсальный внешний devctl уже новее этого встроенного
исторического прототипа.

