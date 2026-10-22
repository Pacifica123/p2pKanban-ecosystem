"""Какие кнопки показать на карточке: чистая логика без Qt, её проверяют тесты."""
from __future__ import annotations

SKIP_IN_MENU = {"status"}
# Короткие подписи кнопок карточки; полное название действия — в окне запуска.
SHORT = {"install": "Установить", "start": "Запустить", "stop": "Остановить", "update": "Обновить",
         "launch": "Открыть", "doctor": "Диагностика", "remove": "Удалить"}


def _has(entry: dict, action_id: str) -> bool:
    return any(action["id"] == action_id for action in entry.get("actions", []))


def _label(entry: dict, action_id: str) -> str:
    return next(a["label"] for a in entry["actions"] if a["id"] == action_id)


def card_actions(row: dict) -> dict:
    """{buttons: [{id, label, main}], menu: [{id, label}], blocked: str|None, settings: bool}.

    `open` — не действие направления, а «открыть url из status».
    """
    apk_value = row.get("apk")
    if apk_value is not None:
        if apk_value.get("apkUrl"):
            menu = [{"id": "@copy", "label": "Копировать ссылку на APK"}]
            if apk_value.get("page"):
                menu.append({"id": "@page", "label": "Страница сборки на expo.dev"})
            return {"buttons": [{"id": "@apk", "label": "Скачать APK", "main": True}], "menu": menu, "blocked": None}
        if apk_value.get("page"):
            return {"buttons": [{"id": "@page", "label": "Сборки на expo.dev ↗", "main": False}], "menu": [], "blocked": None}
        return {"buttons": [], "menu": [], "blocked": None}
    if row.get("canGet"):
        return {"buttons": [{"id": "@get", "label": "Скачать с GitHub", "main": True}], "menu": [], "blocked": None}
    entry = row.get("entry")
    if not entry or row["fit"]["fit"] != "yes":
        return {"buttons": [], "menu": [], "blocked": None}
    status = row.get("status") or {}
    state = status.get("state")
    buttons: list[str] = []
    if row.get("freshness", {}).get("id") == "outdated" and _has(entry, "update"):
        buttons.append("update")
    if state == "running":
        if status.get("url"):
            buttons.append("open")
        buttons += [a for a in ("launch", "stop") if _has(entry, a)]
    elif state == "stopped":
        buttons += [a for a in ("start", "launch") if _has(entry, a)]
    elif state == "installed":
        buttons += [a for a in ("launch", "start", "stop") if _has(entry, a)]
    elif state == "broken":
        buttons += [a for a in ("doctor", "install") if _has(entry, a)]
    else:  # absent или status не спрашивали
        buttons += [a for a in ("install",) if _has(entry, a)]
    buttons = list(dict.fromkeys(buttons))[:2]  # третья кнопка не влезает в карточку — она в «Ещё»
    shown = set(buttons)
    menu = [{"id": a["id"], "label": a["label"]} for a in entry["actions"]
            if a["id"] not in shown and a["id"] not in SKIP_IN_MENU]
    # «Настройки» — отдельной кнопкой, пока она влезает рядом; при двух кнопках — первой в «Ещё».
    tunable = bool(entry.get("settings") or entry.get("profiles"))
    settings_button = tunable and len(buttons) < 2
    if tunable and not settings_button:
        menu.insert(0, {"id": "@settings", "label": "Настройки…"})
    result = [{"id": "open", "label": "Открыть", "main": index == 0} if action_id == "open"
              else {"id": action_id, "label": SHORT.get(action_id) or _label(entry, action_id), "main": index == 0}
              for index, action_id in enumerate(buttons)]
    blocked = None
    if not row.get("ready", True):
        missing = [item["label"] for item in row.get("requires", []) if item["ok"] is False]
        blocked = "Сначала нужно: " + ", ".join(missing) if missing else "Машина не готова"
    return {"buttons": result, "menu": menu, "blocked": blocked, "settings": settings_button}


APK_KIND = {"current": "ok", "awaiting": "warn", "building": "info", "expired": "warn", "none": None, "unknown": None}


def installed_text(row: dict) -> str:
    """Строка «Установлено» для таблицы и карточки."""
    installed = row["installed"]
    apk_value = row.get("apk")
    if apk_value is not None:
        return " · ".join(part for part in (apk_value["label"], apk_value.get("version")) if part)
    parts = [installed["label"]]
    url = (row.get("status") or {}).get("url")
    if url and installed["id"] == "running":
        parts.append(url)
    if row.get("freshness", {}).get("label"):
        parts.append(row["freshness"]["label"])
    return " · ".join(parts)
