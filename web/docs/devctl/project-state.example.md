# Пример краткого состояния проекта

Такой файл помогает быстро вернуть человека и ассистента в контекст без чтения
всей документации. Значения ниже являются примером формата.

## Источник истины

**Проект:** `p2pKanban`  
**Ветка:** `main`  
**Фаза:** подготовка `v1.0.0-beta.3`  
**Поток:** devctl patches + Git  
**Последний commit:** `<sha>`  
**Последний archive:** `archives/<run>/post_*.zip`

## Workspace

```text
p2p_workspace/
  patches/
  archives/
  p2pkanban/
```

## Готово

- web Kanban core;
- auth/session;
- appearance и activity/audit;
- local-first и backend sync baseline;
- export/import preview;
- zero-config container bootstrap;
- experimental transport foundation.

## Текущий фокус

1. применить release-prep patch;
2. выполнить новый full release-gates;
3. собрать tagged bootstrap ZIP;
4. проверить его на Windows и Linux;
5. опубликовать Pre-release.

## Риски

- новые bootstrap/transport изменения ещё не подтверждены повторным полным
  прогоном;
- coordinator-free режим не готов;
- import execution отсутствует;
- публичная лицензия не выбрана;
- разные машины могут иметь разные workspace IDs, поэтому patch target должен
  разрешаться через manifest, а не через случайный локальный путь.

## Правило

Перед применением:

```bash
devctl status
devctl inspect <patch.zip>
devctl plan <patch.zip>
```

Применение допускается только из чистого синхронизированного Git-состояния.

## Что не блокирует v1 автоматически

- mobile;
- coordinator-free P2P;
- AppImage;
- одинокий Windows `.exe`;
- все возможные integrations.

