"""Копия словаря p2p-kanban-ui-themes/1 (docs/ecosystem/ui-themes.json) и QSS окна.

Значения держит само направление; расхождение со словарём показывает
`python -B tools/ecosystem/check_ui_themes.py --directions`. Модуль не импортирует
Qt: QSS — обычная строка, поэтому проверяется без PySide6.
"""
from __future__ import annotations

DEFAULT = "graphite"

THEMES: dict[str, dict] = {
    "graphite": {
        "label": "Графит",
        "scheme": "dark",
        "colors": {
            "background": "#1b1e20",
            "surface": "#292c30",
            "surfaceMuted": "#202326",
            "surfaceRaised": "#31363b",
            "border": "#3a3f44",
            "borderStrong": "#4f555b",
            "text": "#fcfcfc",
            "textMuted": "#a1a9b1",
            "accent": "#3daee9",
            "accentStrong": "#2574a9",
            "accentSoft": "#1f3a4b",
            "accentText": "#3daee9",
            "onAccent": "#ffffff",
            "danger": "#da4453",
            "dangerText": "#f08b95",
            "success": "#27ae60",
            "successText": "#6fd39a",
            "warning": "#f67400",
            "warningText": "#fdbc4b",
            "overlay": "rgba(0, 0, 0, 0.6)",
        },
    },
    "lemon": {
        "label": "Лимон",
        "scheme": "light",
        "colors": {
            "background": "#fff7d6",
            "surface": "#ffffff",
            "surfaceMuted": "#fffbea",
            "surfaceRaised": "#ffffff",
            "border": "#efe3b5",
            "borderStrong": "#d9c47c",
            "text": "#333333",
            "textMuted": "#6b6250",
            "accent": "#ffd667",
            "accentStrong": "#f5c400",
            "accentSoft": "#fff0b3",
            "accentText": "#8a6500",
            "onAccent": "#2b2b2b",
            "danger": "#d13438",
            "dangerText": "#a4262c",
            "success": "#107c10",
            "successText": "#0b6a0b",
            "warning": "#c27c0e",
            "warningText": "#8a5300",
            "overlay": "rgba(51, 43, 20, 0.4)",
        },
    },
    "azure": {
        "label": "Лазурь",
        "scheme": "light",
        "colors": {
            "background": "#e9eff8",
            "surface": "#ffffff",
            "surfaceMuted": "#f4f7fc",
            "surfaceRaised": "#ffffff",
            "border": "#d6e0ee",
            "borderStrong": "#a9bcd8",
            "text": "#252423",
            "textMuted": "#605e5c",
            "accent": "#2b7cd3",
            "accentStrong": "#2b579a",
            "accentSoft": "#dce8f7",
            "accentText": "#2b579a",
            "onAccent": "#ffffff",
            "danger": "#d13438",
            "dangerText": "#a4262c",
            "success": "#107c10",
            "successText": "#0b6a0b",
            "warning": "#c27c0e",
            "warningText": "#8a5300",
            "overlay": "rgba(20, 32, 54, 0.4)",
        },
    },
    "silver": {
        "label": "Серебро",
        "scheme": "light",
        "colors": {
            "background": "#eef0f4",
            "surface": "#ffffff",
            "surfaceMuted": "#f7f8fa",
            "surfaceRaised": "#ffffff",
            "border": "#e0e3ea",
            "borderStrong": "#bdc3cf",
            "text": "#333333",
            "textMuted": "#646b77",
            "accent": "#00bcf0",
            "accentStrong": "#007ba6",
            "accentSoft": "#e0f8ff",
            "accentText": "#006f92",
            "onAccent": "#ffffff",
            "danger": "#d13438",
            "dangerText": "#a4262c",
            "success": "#107c10",
            "successText": "#0b6a0b",
            "warning": "#c27c0e",
            "warningText": "#8a5300",
            "overlay": "rgba(30, 34, 44, 0.4)",
        },
    },
}

TILES = {"web": "#4a8fe0", "mobile": "#3fae74", "abl": "#9a6fd6", "devctl": "#e08a45", "launcher": "#3aa6c9"}


def theme(theme_id: str | None) -> dict:
    return THEMES.get(theme_id or "", THEMES[DEFAULT])


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def mix(a: str, b: str, share: float) -> str:
    """Цвет a, сдвинутый к b на долю share: блики и мягкие подложки «пластика»."""
    ra, rb = _rgb(a), _rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * share):02x}" for x, y in zip(ra, rb))


def qss(theme_id: str | None) -> str:
    """Каркас «пастельный пластик»: скругления, блик сверху, мягкие подложки статусов."""
    c = theme(theme_id)["colors"]
    dark = theme(theme_id)["scheme"] == "dark"
    gloss_top = mix(c["surface"], "#ffffff", 0.05 if dark else 0.6)
    raised_top = mix(c["surfaceRaised"], "#ffffff", 0.07 if dark else 0.7)
    main_top = mix(c["accentStrong"], "#ffffff", 0.18)

    def soft(name: str) -> str:
        return mix(c["surface"], c[name], 0.16)

    return f"""
* {{ color: {c['text']}; font-size: 10pt; }}
QMainWindow, QWidget#page {{ background: {c['background']}; }}
QScrollArea {{ background: transparent; border: none; }}
QToolTip {{ background: {c['surfaceRaised']}; color: {c['text']}; border: 1px solid {c['borderStrong']}; padding: 4px 8px; }}

QFrame#bar {{ background: {c['surfaceMuted']}; border-bottom: 1px solid {c['border']}; }}
QLabel#brandName {{ font-size: 13pt; font-weight: 700; }}
QLabel#brandSub, QLabel#muted, QLabel#lead, QLabel#foot {{ color: {c['textMuted']}; }}
QLabel#section {{ color: {c['textMuted']}; font-size: 9pt; font-weight: 700; letter-spacing: 1px; padding: 14px 4px 2px 4px; }}

QLabel#pill {{ background: {c['accentSoft']}; border-radius: 12px; padding: 4px 12px; }}
QLabel#pill[warn="true"] {{ background: {soft('warning')}; color: {c['warningText']}; }}
QLabel#pillQuiet {{ background: {c['surface']}; color: {c['textMuted']}; border: 1px solid {c['border']}; border-radius: 12px; padding: 3px 12px; }}

QLabel#notice {{ background: {soft('warning')}; color: {c['warningText']}; border: 1px solid {mix(c['surface'], c['warning'], 0.4)}; border-radius: 14px; padding: 10px 14px; }}

QFrame#card, QFrame#panel {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {gloss_top}, stop:0.5 {c['surface']});
  border: 1px solid {c['border']}; border-radius: 20px;
}}
QFrame#card[off="true"] {{ background: {c['surfaceMuted']}; }}
QFrame#card[off="true"] QLabel {{ color: {c['textMuted']}; }}
QLabel#cardTitle {{ font-size: 12pt; font-weight: 700; }}
QLabel#offReason {{ font-weight: 600; }}
QLabel#tile {{ color: #ffffff; font-size: 13pt; font-weight: 800; border-radius: 13px; }}

QLabel#chip {{ background: {c['surfaceMuted']}; color: {c['textMuted']}; border: 1px solid {c['border']}; border-radius: 11px; padding: 2px 10px; font-size: 9pt; }}
QLabel#chip[kind="ok"] {{ background: {soft('success')}; color: {c['successText']}; border-color: {mix(c['surface'], c['success'], 0.4)}; }}
QLabel#chip[kind="warn"] {{ background: {soft('warning')}; color: {c['warningText']}; border-color: {mix(c['surface'], c['warning'], 0.4)}; }}
QLabel#chip[kind="bad"] {{ background: {soft('danger')}; color: {c['dangerText']}; border-color: {mix(c['surface'], c['danger'], 0.4)}; }}
QLabel#chip[kind="info"] {{ background: {c['accentSoft']}; color: {c['accentText']}; }}

QLabel#reqOk {{ color: {c['successText']}; font-weight: 700; }}
QLabel#reqBad {{ color: {c['dangerText']}; font-weight: 700; }}
QFrame#steps {{ background: {c['surfaceMuted']}; border-radius: 10px; }}

QPushButton {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {raised_top}, stop:0.55 {c['surfaceRaised']});
  border: 1px solid {c['border']}; border-radius: 16px; padding: 6px 14px; font-weight: 600; min-height: 20px;
}}
QPushButton:hover {{ border-color: {c['borderStrong']}; }}
QPushButton:pressed {{ background: {c['surfaceMuted']}; }}
QPushButton:focus {{ border: 2px solid {c['accent']}; }}
QPushButton#main {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {main_top}, stop:0.55 {c['accentStrong']});
  color: {c['onAccent']}; border: 1px solid {c['accentStrong']};
}}
QPushButton:disabled, QPushButton#main:disabled {{ color: {c['textMuted']}; background: {c['surfaceMuted']}; border-color: {c['border']}; }}
QPushButton#link {{ background: transparent; border: none; color: {c['accentText']}; padding: 2px 0; text-align: left; }}
QToolButton#swatch {{ border: 2px solid transparent; border-radius: 13px; min-width: 22px; min-height: 22px; }}
QToolButton#swatch:checked {{ border-color: {c['accent']}; }}
QFrame#themes {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 17px; }}

QTableWidget {{ background: transparent; border: none; gridline-color: {c['border']}; selection-background-color: {c['accentSoft']}; selection-color: {c['text']}; }}
QHeaderView, QTableCornerButton::section {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; color: {c['textMuted']}; border: none; border-bottom: 1px solid {c['border']}; padding: 8px 10px; font-weight: 600; }}
QTableWidget::item {{ padding: 6px 10px; border-bottom: 1px solid {c['border']}; }}

QFrame#foot {{ background: {c['surfaceMuted']}; border-top: 1px solid {c['border']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px; }}
QScrollBar::handle:vertical {{ background: {c['borderStrong']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""


def swatch_qss(theme_id: str) -> str:
    c = theme(theme_id)["colors"]
    return (f"QToolButton#swatch {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            f"stop:0 {c['surfaceRaised']}, stop:0.5 {c['surfaceRaised']}, stop:0.51 {c['accentStrong']}, stop:1 {c['accentStrong']}); }}")
