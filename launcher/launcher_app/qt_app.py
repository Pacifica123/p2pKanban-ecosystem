"""Окно лаунчера на PySide6. Только рисует состояние ядра (state.build_state).

Импортируется лишь тогда, когда PySide6 есть; ядро, CLI и тесты без Qt его не
трогают. Весь текст из ecosystem.json и GitHub показывается как простой текст,
не как разметка.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QMenu, QPushButton, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
)

from . import entry as entries, local, paths, settings, themes, view

NAMES = {
    "web": ("Web-узел", "W"),
    "mobile": ("Android", "A"),
    "abl": ("Arch Linux", "L"),
    "devctl": ("devctl", "D"),
    "launcher": ("Лаунчер", "⌂"),
}
PLATFORM = {"windows": "Windows", "macos": "macOS", "linux": "Linux", "arch-linux": "Arch-based", "android": "Android"}
VERDICT_KIND = {"current": "ok", "outdated": "warn", "modified": "warn", "ahead": "info"}
INSTALL_KIND = {"running": "ok", "stopped": "info", "installed": "info", "broken": "bad", "absent": None}
CARD_WIDTH = 330
ICON = paths.LAUNCHER_DIR / "assets" / "icon.svg"


def short_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return value
    return moment.strftime("%d.%m %H:%M")


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def chip(text: str, kind: str | None = None, tip: str | None = None) -> QLabel:
    widget = label(text, "chip")
    if kind:
        widget.setProperty("kind", kind)
    if tip:
        widget.setToolTip(tip)
    return widget


def shadow(widget: QWidget) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(28)
    effect.setOffset(0, 6)
    effect.setColor(QColor(0, 0, 0, 46))
    widget.setGraphicsEffect(effect)


def stage_note(row: dict) -> str:
    if row.get("distribution") == "apk":
        return (row.get("apk") or {}).get("detail") or "Лента APK недоступна."
    if row.get("entryError"):
        return row["entryError"]
    return "Направление ещё не объявило launcher.json: пока — по шагам ниже."


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class Card(QFrame):
    def __init__(self, row: dict, small: bool = False, act: Callable[[dict, str], None] | None = None):
        super().__init__()
        self.setObjectName("card")
        off = row["fit"]["fit"] == "no"
        self.setProperty("off", "true" if off else "false")
        self.setMinimumWidth(280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if not off:
            shadow(self)
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        title, letter = NAMES.get(row["id"], (row["id"], row["id"][:1].upper()))
        head = QHBoxLayout()
        tile = label(letter, "tile")
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setFixedSize(42, 42)
        color = "#9aa0a6" if off else themes.TILES.get(row["id"], "#5aa9e6")
        tile.setStyleSheet(f"QLabel#tile {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
                           f"stop:0 {themes.mix(color, '#ffffff', 0.22)}, stop:0.55 {color}); }}")
        head.addWidget(tile)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label(title, "cardTitle"))
        platforms = " · ".join(PLATFORM.get(item, item) for item in row["platforms"])
        names.addWidget(label(f"{row['dir']}/ · {platforms}", "muted", wrap=True))
        head.addLayout(names, 1)
        if row.get("docsUrl"):
            docs = QPushButton("Документация ↗")
            docs.setObjectName("link")
            docs.setToolTip(row["docsUrl"])
            docs.clicked.connect(lambda _=False, url=row["docsUrl"]: open_url(url))
            head.addWidget(docs, 0, Qt.AlignmentFlag.AlignTop)
        box.addLayout(head)

        if off:
            box.addWidget(label(f"Недоступно здесь: {row['fit']['reason']}", "offReason", wrap=True))
        box.addWidget(label(row["summary"], wrap=True))

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(chip(f"исходники: {row['checkout']['label']}", VERDICT_KIND.get(row["checkout"]["id"]), row["checkout"]["detail"]))
        if row["fit"]["fit"] == "yes" and (small or not row["requires"]):
            chips.addWidget(chip("машина готова" if row["ready"] else "нет предпосылок", "ok" if row["ready"] else "bad"))
        chips.addStretch(1)
        box.addLayout(chips)
        if row.get("apk"):
            line = QHBoxLayout()
            line.addWidget(chip(view.installed_text(row), view.APK_KIND.get(row["apk"]["id"]), row["apk"]["detail"]))
            line.addStretch(1)
            box.addLayout(line)
            box.addWidget(label(row["apk"]["detail"], "muted", wrap=True))
        if row.get("status"):
            line = QHBoxLayout()
            line.addWidget(chip(view.installed_text(row), INSTALL_KIND.get(row["status"]["state"]), row["installed"]["detail"]))
            line.addStretch(1)
            box.addLayout(line)

        if not small:
            for item in row["requires"]:
                line = QHBoxLayout()
                mark = label("✓" if item["ok"] else "✗" if item["ok"] is False else "?",
                             "reqOk" if item["ok"] else "reqBad" if item["ok"] is False else "muted")
                mark.setFixedWidth(14)
                text = f"{item['label']} — {item['detail']}"
                if item["ok"] is False and item.get("hint"):
                    text += f" · {item['hint']}"
                line.addWidget(mark, 0, Qt.AlignmentFlag.AlignTop)
                line.addWidget(label(text, wrap=True), 1)
                if item["ok"] is False and item.get("link"):
                    link = QPushButton("где взять")
                    link.setObjectName("link")
                    link.clicked.connect(lambda _=False, url=item["link"]: open_url(url))
                    line.addWidget(link, 0, Qt.AlignmentFlag.AlignTop)
                box.addLayout(line)
            if row["install"]:
                self.toggle = QPushButton("▸ Как развернуть")
                self.toggle.setObjectName("link")
                steps = QFrame()
                steps.setObjectName("steps")
                steps_box = QVBoxLayout(steps)
                steps_box.setContentsMargins(12, 8, 12, 8)
                for number, step in enumerate(row["install"], 1):
                    steps_box.addWidget(label(f"{number}. {step}", wrap=True))
                steps.setVisible(False)

                def flip(_: bool = False, frame: QFrame = steps, button: QPushButton = self.toggle) -> None:
                    frame.setVisible(not frame.isVisible())
                    button.setText(("▾" if frame.isVisible() else "▸") + " Как развернуть")
                self.toggle.clicked.connect(flip)
                box.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
                box.addWidget(steps)

        box.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        plan = view.card_actions(row)
        if plan["buttons"] or plan["menu"]:
            for item in plan["buttons"]:
                button = QPushButton(item["label"])
                if item["main"]:
                    button.setObjectName("main")
                button.setEnabled(plan["blocked"] is None or item["id"] == "open")
                if plan["blocked"]:
                    button.setToolTip(plan["blocked"])
                button.clicked.connect(lambda _=False, aid=item["id"]: act and act(row, aid))
                actions.addWidget(button)
            if row.get("entry") and (row["entry"].get("settings") or row["entry"].get("profiles")):
                tune = QPushButton("Настройки")
                tune.clicked.connect(lambda _=False: act and act(row, "@settings"))
                actions.addWidget(tune)
            if plan["menu"]:
                more = QToolButton()
                more.setText("Ещё ▾")
                more.setObjectName("more")
                more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
                menu = QMenu(more)
                for item in plan["menu"]:
                    menu.addAction(item["label"], lambda aid=item["id"]: act and act(row, aid))
                more.setMenu(menu)
                actions.addWidget(more)
            actions.addStretch(1)
            box.addLayout(actions)
            if plan["blocked"]:
                box.addWidget(label(plan["blocked"], "muted", wrap=True))
            return
        disabled = []
        if row.get("distribution") == "apk":
            disabled.append(("Скачать APK", True))
        elif row["id"] == "launcher":
            disabled.append(("Обновить лаунчер", False))
        elif row.get("audience", "user") == "user":
            disabled += [("Установить", True), ("Настройки", False)]
        for text, main in disabled:
            button = QPushButton(text)
            if main:
                button.setObjectName("main")
            button.setEnabled(False)
            button.setToolTip(stage_note(row))
            actions.addWidget(button)
        actions.addStretch(1)
        box.addLayout(actions)
        if disabled and not off:
            box.addWidget(label(stage_note(row), "muted", wrap=True))


class Grid(QWidget):
    """Сетка карточек: число колонок следует за шириной окна."""

    def __init__(self):
        super().__init__()
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        self.cards: list[QWidget] = []
        self.columns = 0

    def set_cards(self, cards: list[QWidget]) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = cards
        self.columns = 0
        self.relayout()

    def relayout(self) -> None:
        columns = max(1, min(3, (self.width() + 16) // (CARD_WIDTH + 16)))
        if columns == self.columns:
            return
        self.columns = columns
        for card in self.cards:
            self.grid.removeWidget(card)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        for column in range(3):
            self.grid.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.relayout()


class Loader(QObject):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, provider: Callable[[bool], dict]):
        super().__init__()
        self.provider = provider
        self.busy = False

    def start(self, force: bool) -> bool:
        if self.busy:
            return False
        self.busy = True

        def work() -> None:
            try:
                value = self.provider(force)
            except Exception as error:  # noqa: BLE001 - показать в окне, а не уронить его
                self.busy = False
                self.failed.emit(f"{type(error).__name__}: {error}")
                return
            self.busy = False
            self.done.emit(value)
        threading.Thread(target=work, daemon=True).start()
        return True


class Window(QMainWindow):
    def __init__(self, provider: Callable[[bool], dict], settings_file: Path):
        super().__init__()
        self.settings_file = settings_file
        self.current = settings.load(settings_file)
        self.setWindowTitle("p2pKanban Launcher")
        if ICON.is_file():
            self.setWindowIcon(QIcon(str(ICON)))
        size = self.current["window"]
        self.resize(size["width"], size["height"])
        self.setMinimumSize(QSize(*settings.MIN_SIZE))

        self.dialogs: list = []
        self.last_state: dict = {"ecosystem": {"root": None}}
        self.loader = Loader(provider)
        self.loader.done.connect(self.render)
        self.loader.failed.connect(lambda message: self.show_notice(f"Состояние не собралось: {message}"))

        root = QWidget()
        root.setObjectName("page")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.build_bar())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("page")
        self.body = QVBoxLayout(page)
        self.body.setContentsMargins(24, 8, 24, 24)
        self.body.setSpacing(10)
        self.notice = label("", "notice", wrap=True)
        self.notice.setVisible(False)
        self.body.addWidget(self.notice)
        self.body.addWidget(label("ПРИЛОЖЕНИЯ", "section"))
        self.apps = Grid()
        self.body.addWidget(self.apps)
        self.body.addWidget(label("СОСТОЯНИЕ", "section"))
        self.body.addWidget(label("Исходники этого checkout рядом с последним коммитом main, менявшим каталог направления.", "lead", wrap=True))
        self.body.addWidget(self.build_table())
        self.body.addWidget(label("ДЛЯ РАЗРАБОТКИ", "section"))
        self.dev = Grid()
        self.body.addWidget(self.dev)
        self.body.addStretch(1)
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)

        foot = QFrame()
        foot.setObjectName("foot")
        foot_box = QHBoxLayout(foot)
        foot_box.setContentsMargins(24, 8, 24, 8)
        self.foot_source = label("Собираю состояние…", "foot")
        foot_box.addWidget(self.foot_source)
        foot_box.addStretch(1)
        foot_box.addWidget(label("«Актуально» — исходники как в main, а не «принято»: приёмку даёт tools/ecosystem/uts.py.", "foot"))
        outer.addWidget(foot)
        self.setCentralWidget(root)
        self.apply_theme(self.current["theme"], save=False)

    # --- части окна ---

    def build_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("bar")
        box = QHBoxLayout(bar)
        box.setContentsMargins(20, 12, 20, 12)
        box.setSpacing(14)
        if ICON.is_file():
            mark = QLabel()
            mark.setPixmap(QIcon(str(ICON)).pixmap(36, 36))
            box.addWidget(mark)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label("p2pKanban", "brandName"))
        self.brand_sub = label("Лаунчер", "brandSub")
        brand.addWidget(self.brand_sub)
        box.addLayout(brand)
        self.board_pill = label("", "pill")
        self.board_pill.setVisible(False)
        self.host_pill = label("", "pillQuiet")
        self.host_pill.setVisible(False)
        box.addSpacing(8)
        box.addWidget(self.board_pill)
        box.addWidget(self.host_pill)
        box.addStretch(1)
        self.refresh = QPushButton("Проверить")
        self.refresh.setToolTip("Спросить main заново, не дожидаясь кеша")
        self.refresh.clicked.connect(lambda: self.load(True))
        box.addWidget(self.refresh)

        swatches = QFrame()
        swatches.setObjectName("themes")
        swatch_box = QHBoxLayout(swatches)
        swatch_box.setContentsMargins(5, 4, 5, 4)
        swatch_box.setSpacing(5)
        self.swatches: dict[str, QToolButton] = {}
        for theme_id, spec in themes.THEMES.items():
            button = QToolButton()
            button.setObjectName("swatch")
            button.setCheckable(True)
            button.setToolTip(spec["label"])
            button.setAccessibleName(spec["label"])
            button.setStyleSheet(themes.swatch_qss(theme_id))
            button.setFixedSize(26, 26)
            button.clicked.connect(lambda _=False, value=theme_id: self.apply_theme(value))
            swatch_box.addWidget(button)
            self.swatches[theme_id] = button
        box.addWidget(swatches)
        return bar

    def build_table(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        shadow(panel)
        box = QVBoxLayout(panel)
        box.setContentsMargins(6, 6, 6, 6)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Направление", "main", "Этот checkout", "Сверка", "Установлено"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setWordWrap(True)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column, mode in enumerate([QHeaderView.ResizeMode.ResizeToContents, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.Stretch,
                                       QHeaderView.ResizeMode.Stretch]):
            header.setSectionResizeMode(column, mode)
        box.addWidget(self.table)
        return panel

    # --- поведение ---

    def apply_theme(self, theme_id: str, save: bool = True) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(themes.qss(theme_id))
        for key, button in self.swatches.items():
            button.setChecked(key == theme_id)
        self.current["theme"] = theme_id
        if save:
            self.save_settings()

    def save_settings(self) -> None:
        try:
            self.current = settings.save(self.settings_file, self.current)
        except OSError as error:
            self.show_notice(f"Настройки не сохранились: {error}")

    def show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.setVisible(bool(text))

    def load(self, force: bool = False) -> None:
        if self.loader.start(force):
            self.refresh.setEnabled(False)
            self.refresh.setText("Проверяю…")

    def render(self, value: dict) -> None:
        self.refresh.setEnabled(True)
        self.refresh.setText("Проверить")
        self.last_state = value
        eco, glob = value["ecosystem"], value["global"]
        self.brand_sub.setText(f"Лаунчер {value['launcher']['version']} · ступень {value['launcher']['stage']}")
        mine, theirs = eco.get("localBoard"), eco.get("remoteBoard")
        if mine or theirs:
            behind = bool(mine and theirs and (theirs.get("boardRevision") or 0) > (mine.get("boardRevision") or 0))
            text = f"патч {mine['boardRevision']} · {mine['lastPatchId']}" if mine else "патч неизвестен"
            if behind:
                text = f"патч {mine['boardRevision']}, в main уже {theirs['boardRevision']}"
            self.board_pill.setText(text)
            self.board_pill.setProperty("warn", "true" if behind else "false")
            self.board_pill.style().unpolish(self.board_pill)
            self.board_pill.style().polish(self.board_pill)
            tip = [f"у вас: патч {mine['boardRevision']} · {mine['lastPatchId']}" if mine else "у вас: неизвестно",
                   f"main: патч {theirs['boardRevision']} · {theirs['lastPatchId']}" if theirs else "main ещё не проверен"]
            self.board_pill.setToolTip("\n".join(tip))
            self.board_pill.setVisible(True)
        self.host_pill.setText(value["host"]["label"])
        self.host_pill.setVisible(True)

        notices = []
        if glob.get("error"):
            notices.append(f"Нет свежих данных о main ({glob['error']}); показан кеш." if glob.get("source") == "cache"
                           else f"Нет данных о main: {glob['error']}.")
        if not value["checkout"]["available"]:
            notices.append(f"Checkout: {value['checkout']['reason']}.")
        self.show_notice(" ".join(notices))

        order = {"yes": 0, "phone": 1, "no": 2}
        users = sorted((row for row in value["components"] if row.get("audience", "user") == "user"),
                       key=lambda row: order[row["fit"]["fit"]])
        self.apps.set_cards([Card(row, act=self.act) for row in users])
        self.dev.set_cards([Card(row, small=True, act=self.act) for row in value["components"]
                            if row.get("audience", "user") != "user"])
        self.fill_table(value["components"])

        source = {"network": "из сети", "cache": "из кеша", "none": "нет данных"}.get(glob.get("source"), glob.get("source"))
        checked = f", проверено {short_date(glob['checkedAt'])}" if glob.get("checkedAt") else ""
        self.foot_source.setText(f"main {eco.get('repository') or '?'}: {source}{checked}")

    def fill_table(self, rows: list[dict]) -> None:
        def commit_text(commit: dict | None) -> str:
            if not commit:
                return "—"
            return f"{(commit.get('sha') or '')[:7]}  {short_date(commit.get('date'))}\n{commit.get('subject') or ''}"

        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            installed = row["installed"]
            cells = [
                f"{NAMES.get(row['id'], (row['id'],))[0]}\n{row['dir']}/",
                commit_text(row.get("remote")),
                commit_text((row.get("local") or {}).get("commit")),
                f"{row['checkout']['label']}\n{row['checkout']['detail']}",
                f"{view.installed_text(row)}\n{installed['detail'] if isinstance(installed['detail'], str) else ''}",
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(index, column, item)
        self.table.resizeRowsToContents()
        height = self.table.horizontalHeader().height() + sum(self.table.rowHeight(i) for i in range(len(rows))) + 4
        self.table.setFixedHeight(height)

    # --- действия направлений (L2) ---

    def act(self, row: dict, action_id: str) -> None:
        from . import qt_dialogs

        root = Path(self.last_state["ecosystem"]["root"] or ".")
        registry = paths.registry_file()
        entry = row.get("entry") or {}
        values = entries.clean_values(entry, local.saved_values(registry, row["id"]))
        if action_id == "open":
            url = (row.get("status") or {}).get("url")
            if url:
                open_url(url)
            return
        if action_id in ("@apk", "@page", "@copy"):
            value = row.get("apk") or {}
            url = value.get("apkUrl") if action_id != "@page" else value.get("page")
            if url and action_id == "@copy":
                QApplication.clipboard().setText(url)
                self.show_notice("Ссылка на APK скопирована: откройте её на телефоне.")
            elif url:
                open_url(url)
            return
        if action_id == "@settings":
            dialog = qt_dialogs.SettingsDialog(self, entry, values, (row.get("status") or {}).get("values"))
            dialog.saved.connect(lambda chosen: self.save_values(row["id"], chosen))
            dialog.run_profile.connect(lambda pid, chosen: self.run_action(root, row, entry, next(
                p for p in entry["profiles"] if p["id"] == pid)["action"], chosen, next(
                p for p in entry["profiles"] if p["id"] == pid)["label"]))
            dialog.exec()
            return
        self.run_action(root, row, entry, action_id, values)

    def run_action(self, root: Path, row: dict, entry: dict, action_id: str, values: dict, title: str | None = None) -> None:
        from . import qt_dialogs

        dialog = qt_dialogs.RunDialog(self, root, entry, action_id, values, paths.registry_file(), title)
        dialog.ran.connect(lambda *_: self.load(False))
        if row["id"] == "launcher" and action_id == "update":
            dialog.ran.connect(lambda _aid, code: code == 0 and self.show_notice(
                "Checkout обновлён. Перезапустите лаунчер, чтобы взять его новую версию."))
        dialog.setModal(False)
        dialog.show()
        self.dialogs.append(dialog)
        dialog.finished.connect(lambda *_, d=dialog: self.dialogs.remove(d) if d in self.dialogs else None)

    def save_values(self, component: str, values: dict) -> None:
        try:
            local.save_values(paths.registry_file(), component, values)
        except OSError as error:
            self.show_notice(f"Настройки {component} не сохранились: {error}")
            return
        self.load(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.current["window"] = {"width": self.width(), "height": self.height()}
        self.save_settings()
        super().closeEvent(event)


def run(provider: Callable[[bool], dict], settings_file: Path, screenshot: Path | None = None,
        theme_id: str | None = None, size: tuple[int, int] | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("p2pKanban Launcher")
    window = Window(provider, settings_file)
    if theme_id:
        window.apply_theme(theme_id, save=False)
    if size:
        window.resize(*size)
    window.show()
    if screenshot is not None:
        def capture(_: dict) -> None:
            def grab() -> None:
                window.grab().save(str(screenshot))
                app.quit()
            QTimer.singleShot(300, grab)
        window.loader.done.connect(capture)
        window.loader.failed.connect(lambda _: app.quit())
    window.load(False)
    return app.exec()
