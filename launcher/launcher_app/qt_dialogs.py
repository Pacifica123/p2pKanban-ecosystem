"""Окна действия и настроек направления (ступень L2).

Команда собирается ядром (entry.command → runner.resolve) и показывается
человеку до запуска; запуск — QProcess без оболочки, вывод — построчно.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from . import entry as entries, runner

MAX_OUTPUT_LINES = 5000


def _label(text: str, name: str | None = None, wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def _mono(read_only: bool = True, height: int | None = None) -> QPlainTextEdit:
    box = QPlainTextEdit()
    box.setReadOnly(read_only)
    box.setObjectName("mono")
    box.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    box.setMaximumBlockCount(MAX_OUTPUT_LINES)
    if height:
        box.setFixedHeight(height)
    return box


class RunDialog(QDialog):
    """Предпросмотр команды, пробный прогон, запуск и вывод одного действия."""

    ran = Signal(str, int)  # id действия, код выхода

    def __init__(self, parent: QWidget | None, root: Path, entry: dict, action_id: str, values: dict,
                 registry_file: Path, title: str | None = None):
        super().__init__(parent)
        self.root, self.entry, self.action_id = root, entry, action_id
        self.values, self.registry_file = values, registry_file
        self.action = entries.find_action(entry, action_id)
        self.process: QProcess | None = None
        self.current: dict | None = None
        self.pending = ""
        self.setWindowTitle(title or f"{self.action['label']} · {entry['component']}")
        self.resize(760, 560)
        box = QVBoxLayout(self)
        box.setSpacing(10)
        box.addWidget(_label(title or self.action["label"], "dialogTitle"))
        if self.action.get("help"):
            box.addWidget(_label(self.action["help"], "muted"))
        if self.action.get("privileged"):
            box.addWidget(_label("Команда сама попросит пароль администратора (pkexec или sudo).", "warnLine"))
        if self.action.get("confirm"):
            box.addWidget(_label(self.action["confirm"], "warnLine"))
        box.addWidget(_label("Команда (выполняется без оболочки, в каталоге направления):", "muted"))
        self.preview = _mono(height=70)
        box.addWidget(self.preview)
        self.output = _mono()
        self.output.setPlaceholderText("Здесь будет вывод команды.")
        box.addWidget(self.output, 1)
        self.state = _label("", "muted")
        box.addWidget(self.state)

        buttons = QHBoxLayout()
        self.dry = QPushButton("Пробный прогон")
        self.dry.setVisible(bool(self.action.get("dryRun")))
        self.dry.clicked.connect(lambda: self.start(True))
        self.go = QPushButton("Выполнить")
        self.go.setObjectName("main")
        self.go.clicked.connect(lambda: self.start(False))
        self.cancel = QPushButton("Прервать")
        self.cancel.setEnabled(False)
        self.cancel.clicked.connect(self.abort)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        buttons.addWidget(self.dry)
        buttons.addWidget(self.go)
        buttons.addWidget(self.cancel)
        buttons.addStretch(1)
        buttons.addWidget(close)
        box.addLayout(buttons)
        self.show_command(False)

    def command(self, dry_run: bool) -> dict:
        return runner.resolve(self.root, entries.command(self.entry, self.action_id, self.values, dry_run))

    def show_command(self, dry_run: bool) -> None:
        try:
            command = self.command(dry_run)
        except entries.Rejected as error:
            self.preview.setPlainText(f"Команда не собирается: {error}")
            self.go.setEnabled(False)
            self.dry.setEnabled(False)
            return
        self.preview.setPlainText(f"{runner.display(command['argv'])}\n# в {command['cwd']}")

    def start(self, dry_run: bool) -> None:
        if self.process is not None:
            return
        if not dry_run and self.action.get("confirm"):
            answer = QMessageBox.question(self, "Подтвердите", self.action["confirm"],
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            command = self.command(dry_run)
        except entries.Rejected as error:
            self.state.setText(f"Не запущено: {error}")
            return
        self.show_command(dry_run)
        self.current = {**command, "dryRun": dry_run}
        self.output.appendPlainText(f"$ {runner.display(command['argv'])}{'   # пробный прогон' if dry_run else ''}")
        program, arguments = command["argv"][0], command["argv"][1:]
        if command["detached"] and not dry_run:
            ok, _pid = QProcess.startDetached(program, arguments, command["cwd"])
            code = 0 if ok else 127
            self.output.appendPlainText("запущено отдельно от лаунчера" if ok else "не запустилось")
            self.finish(code, dry_run)
            return
        process = QProcess(self)
        environment = QProcessEnvironment()
        for key, value in runner.child_env().items():
            environment.insert(key, value)
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(command["cwd"])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self.read)
        process.finished.connect(lambda code, _status: self.finish(code, dry_run))
        process.errorOccurred.connect(self.failed)
        self.process = process
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expire)
        self.timer.start(command["timeoutSeconds"] * 1000)
        self.busy(True)
        self.state.setText("Пробный прогон…" if dry_run else "Выполняется…")
        process.start(program, arguments)

    def busy(self, value: bool) -> None:
        self.go.setEnabled(not value)
        self.dry.setEnabled(not value)
        self.cancel.setEnabled(value)

    def read(self) -> None:
        if self.process is None:
            return
        self.pending += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace").replace("\r\n", "\n")
        *lines, self.pending = self.pending.split("\n")
        for line in lines:
            self.output.appendPlainText(line)

    def flush(self) -> None:
        if self.pending:
            self.output.appendPlainText(self.pending)
            self.pending = ""

    def failed(self, error) -> None:  # noqa: ANN001 - QProcess.ProcessError
        if error == QProcess.ProcessError.FailedToStart:
            self.output.appendPlainText(f"не запустилось: {self.process.errorString() if self.process else ''}")
            self.finish(127, bool(self.current and self.current.get("dryRun")))

    def expire(self) -> None:
        if self.process is not None:
            self.output.appendPlainText(f"остановлено: дольше {self.current['timeoutSeconds']} с")
            self.process.kill()

    def abort(self) -> None:
        if self.process is not None:
            self.output.appendPlainText("прервано пользователем")
            self.process.kill()

    def finish(self, code: int, dry_run: bool) -> None:
        if self.current is None:
            return
        command, self.current = self.current, None
        if self.process is not None:
            self.read()
            self.flush()
            self.timer.stop()
            self.process.deleteLater()
            self.process = None
        self.busy(False)
        runner.record(self.registry_file, command, code, dry_run, self.values)
        verdict = "готово" if code == 0 else f"код выхода {code}"
        self.state.setText(f"Пробный прогон: {verdict}. Теперь можно выполнить по-настоящему." if dry_run and code == 0
                           else f"Пробный прогон: {verdict}" if dry_run else f"Завершено: {verdict}")
        self.output.appendPlainText(f"— {verdict}\n")
        if not dry_run:
            self.ran.emit(self.action_id, code)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.process is not None:
            answer = QMessageBox.question(self, "Команда ещё выполняется",
                                          "Прервать команду и закрыть окно?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.process.kill()
            self.process.waitForFinished(3000)
        super().closeEvent(event)


class SettingsDialog(QDialog):
    """Настройки направления из его launcher.json и варианты установки."""

    saved = Signal(dict)
    run_profile = Signal(str, dict)  # id варианта, значения

    AUTO = "авто"

    def __init__(self, parent: QWidget | None, entry: dict, values: dict, current: dict | None = None):
        super().__init__(parent)
        self.entry = entry
        self.setWindowTitle(f"Настройки · {entry['component']}")
        self.setMinimumWidth(600)
        box = QVBoxLayout(self)
        box.setSpacing(10)
        box.addWidget(_label("Настройки", "dialogTitle"))
        box.addWidget(_label("Значения подставляются в команды направления при следующем запуске. "
                             "Пусто или «авто» — решает само направление.", "muted"))
        form = QFormLayout()
        self.fields: dict[str, QWidget] = {}
        for setting in entry.get("settings", []):
            value = values.get(setting["id"], setting.get("default"))
            widget = self.field(setting, value)
            self.fields[setting["id"]] = widget
            hint = setting.get("help") or ""
            if current and setting["id"] in current:
                hint = (hint + " " if hint else "") + f"Сейчас: {current[setting['id']]}."
            holder = QVBoxLayout()
            holder.setContentsMargins(0, 0, 0, 4)
            holder.setSpacing(2)
            holder.addWidget(widget)
            if hint:
                holder.addWidget(_label(hint, "muted"))
            frame = QWidget()
            frame.setLayout(holder)
            form.addRow(setting["label"], frame)
        box.addLayout(form)
        self.problem = _label("", "warnLine")
        self.problem.setVisible(False)
        box.addWidget(self.problem)

        profiles = entry.get("profiles", [])
        if profiles:
            box.addWidget(_label("ВАРИАНТЫ УСТАНОВКИ", "section"))
            for profile in profiles:
                line = QFrame()
                line.setObjectName("steps")
                line_box = QHBoxLayout(line)
                text = QVBoxLayout()
                text.addWidget(_label(profile["label"], "cardTitle" if profile["supported"] else "offReason"))
                if profile.get("description"):
                    text.addWidget(_label(profile["description"], "muted"))
                if not profile["supported"]:
                    text.addWidget(_label(f"Пока нельзя: {profile['reason']}", "muted"))
                line_box.addLayout(text, 1)
                button = QPushButton("Запустить")
                button.setEnabled(profile["supported"])
                button.clicked.connect(lambda _=False, pid=profile["id"]: self.start_profile(pid))
                line_box.addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
                box.addWidget(line)
        box.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить")
        save.setObjectName("main")
        save.clicked.connect(self.save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        box.addLayout(buttons)
        hint = self.sizeHint()
        self.resize(max(600, hint.width()), max(420, hint.height()))

    def field(self, setting: dict, value) -> QWidget:  # noqa: ANN001
        kind = setting["type"]
        if kind == "port":
            spin = QSpinBox()
            low = setting.get("min", 1024)
            spin.setRange(low - 1, setting.get("max", 65535))
            spin.setSpecialValueText(self.AUTO)  # минимум означает «авто»
            spin.setValue(value if isinstance(value, int) else low - 1)
            return spin
        if kind == "choice":
            combo = QComboBox()
            if setting.get("default") is None:
                combo.addItem("как было", None)
            for choice in setting["choices"]:
                combo.addItem(choice["label"], choice["value"])
            index = combo.findData(value)
            combo.setCurrentIndex(max(0, index))
            return combo
        check = QCheckBox()
        check.setChecked(bool(value))
        return check

    def collect(self) -> dict:
        out: dict = {}
        for setting in self.entry.get("settings", []):
            widget = self.fields[setting["id"]]
            if isinstance(widget, QSpinBox):
                out[setting["id"]] = None if widget.value() == widget.minimum() else widget.value()
            elif isinstance(widget, QComboBox):
                out[setting["id"]] = widget.currentData()
            else:
                out[setting["id"]] = widget.isChecked()
        return out

    def validated(self) -> dict | None:
        values = self.collect()
        try:
            entries.values(self.entry, values)
        except entries.Rejected as error:
            self.problem.setText(f"Не подходит: {error}")
            self.problem.setVisible(True)
            return None
        return values

    def save(self) -> None:
        values = self.validated()
        if values is not None:
            self.saved.emit(values)
            self.accept()

    def start_profile(self, profile_id: str) -> None:
        values = self.validated()
        if values is None:
            return
        profile = next(p for p in self.entry["profiles"] if p["id"] == profile_id)
        values.update(profile.get("values") or {})
        missing = [sid for sid in profile.get("ask", []) if values.get(sid) is None]
        if missing:
            labels = {s["id"]: s["label"] for s in self.entry.get("settings", [])}
            self.problem.setText("Для варианта задайте: " + ", ".join(labels.get(sid, sid) for sid in missing))
            self.problem.setVisible(True)
            return
        self.saved.emit(values)
        self.run_profile.emit(profile_id, values)
        self.accept()
