"""Reusable controls from the PalletLab design system.

Each component owns its QSS so it can be introduced into existing screens
gradually without changing the visual rules of unrelated widgets.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap, QTransform
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)


class _CheckIcon(QLabel):
    SVG_PATH = Path(__file__).parent / "assets" / "icons" / "check.svg"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(16, 16)

    def set_visible(self, visible: bool) -> None:
        self.setVisible(visible)
        if not visible:
            return
        source = QPixmap(16, 16)
        source.fill(Qt.transparent)
        renderer = QSvgRenderer(str(self.SVG_PATH))
        painter = QPainter(source)
        renderer.render(painter)
        painter.end()
        result = QPixmap(16, 16)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(result.rect(), QColor("#ffffff"))
        painter.end()
        self.setPixmap(result)


class DesignCheckBox(QWidget):
    """Self-contained checkbox without a dependency on a compiled Qt resource file."""

    toggled = pyqtSignal(bool)

    QSS = """
        QFrame#checkboxIndicator {
            width: 20px;
            height: 20px;
            border: 1px solid #737373;
            border-radius: 4px;
            background: #ffffff;
        }
        QFrame#checkboxIndicator[hovered="true"] { border-color: #0a0a0a; }
        QFrame#checkboxIndicator[checked="true"] {
            border-color: #2b7fff;
            background: #2b7fff;
        }
        QFrame#checkboxIndicator[disabled="true"] { border-color: #e5e5e5; background: #ffffff; }
        QFrame#checkboxIndicator[checked="true"][disabled="true"] {
            border-color: #dbeafe;
            background: #dbeafe;
        }
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._checked = False
        self._hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.indicator = QFrame()
        self.indicator.setObjectName("checkboxIndicator")
        self.indicator.setFixedSize(20, 20)
        icon_layout = QHBoxLayout(self.indicator)
        icon_layout.setContentsMargins(1, 1, 1, 1)
        self.check_icon = _CheckIcon()
        icon_layout.addWidget(self.check_icon)
        self.label = QLabel(text)
        self.label.setStyleSheet("color: #404040; font-family: 'Segoe UI'; font-size: 16px;")
        layout.addWidget(self.indicator)
        layout.addWidget(self.label)
        layout.addStretch()
        self.setStyleSheet(self.QSS)
        self._refresh_state()

    def isChecked(self) -> bool:  # noqa: N802 - Qt API spelling.
        return self._checked

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API spelling.
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self._refresh_state()
        self.toggled.emit(checked)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt API spelling.
        super().setEnabled(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self._refresh_state()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._refresh_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._refresh_state()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self.isEnabled() and event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)
        super().mouseReleaseEvent(event)

    def _refresh_state(self) -> None:
        disabled = not self.isEnabled()
        self.indicator.setProperty("checked", "true" if self._checked else "false")
        self.indicator.setProperty("hovered", "true" if self._hovered and not disabled else "false")
        self.indicator.setProperty("disabled", "true" if disabled else "false")
        self.indicator.style().unpolish(self.indicator)
        self.indicator.style().polish(self.indicator)
        self.label.setStyleSheet(
            f"color: {'#e5e5e5' if disabled else '#0a0a0a' if self._hovered else '#404040'}; "
            "font-family: 'Segoe UI'; font-size: 16px;"
        )
        self.check_icon.set_visible(self._checked)


class _ChevronIcon(QLabel):
    """One SVG arrow recoloured and rotated by the owning component state."""

    SVG_PATH = Path(__file__).parent / "assets" / "icons" / "chevron-down.svg"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignCenter)

    def set_appearance(self, color: str, *, open_: bool) -> None:
        source = QPixmap(16, 16)
        source.fill(Qt.transparent)
        renderer = QSvgRenderer(str(self.SVG_PATH))
        painter = QPainter(source)
        renderer.render(painter)
        painter.end()

        result = QPixmap(16, 16)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(result.rect(), QColor(color))
        painter.end()
        if open_:
            result = result.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
        self.setPixmap(result)


class _ComboTrigger(QFrame):
    clicked = pyqtSignal()
    hovered = pyqtSignal(bool)
    focused = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.StrongFocus)

    def enterEvent(self, event) -> None:
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hovered.emit(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.setFocus()
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def focusInEvent(self, event) -> None:
        self.focused.emit(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.focused.emit(False)
        super().focusOutEvent(event)


class _ComboMenu(QWidget):
    """Custom popup so menu geometry and states never fall back to native Qt."""

    QSS = """
        QFrame#comboMenuSurface { background: #ffffff; border: none; border-radius: 16px; }
        QPushButton#comboMenuItem {
            min-height: 36px; padding: 6px 8px; border: none; border-radius: 8px;
            color: #404040; background: #ffffff; font-family: 'Segoe UI'; font-size: 16px; text-align: left;
        }
        QPushButton#comboMenuItem:hover { color: #0a0a0a; background: #f5f5f5; }
        QPushButton#comboMenuItem:pressed { color: #ffffff; background: #2b7fff; }
        QPushButton#comboMenuItem[active="true"] { color: #ffffff; background: #2b7fff; }
    """

    selected = pyqtSignal(str)
    closed = pyqtSignal()

    def __init__(self, items: tuple[str, ...], parent=None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("comboMenu")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setStyleSheet(self.QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 28)
        self.surface = QFrame()
        self.surface.setObjectName("comboMenuSurface")
        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(8, 8, 8, 8)
        surface_layout.setSpacing(0)
        self._item_buttons: dict[str, QPushButton] = {}
        for item in items:
            button = QPushButton(item)
            button.setObjectName("comboMenuItem")
            # Select on press, rather than release: the previous active row is
            # cleared before the new row is painted, so two rows never appear active.
            button.pressed.connect(lambda value=item: self.selected.emit(value))
            surface_layout.addWidget(button)
            self._item_buttons[item] = button
        layout.addWidget(self.surface)
        shadow = QGraphicsDropShadowEffect(self.surface)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 20))
        self.surface.setGraphicsEffect(shadow)

    def set_current_value(self, value: str) -> None:
        for item, button in self._item_buttons.items():
            button.setProperty("active", "true" if item == value else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    def hideEvent(self, event) -> None:
        self.closed.emit()
        super().hideEvent(event)


class DesignComboBox(QFrame):
    """Captioned custom combo box matching the Figma trigger and popup menu."""

    QSS = """
        DesignComboBox { background: transparent; }
        QLabel#comboCaption { color: #404040; font-family: 'Segoe UI'; font-size: 14px; }
        QLabel#comboValue { color: #404040; font-family: 'Segoe UI'; font-size: 16px; }
        _ComboTrigger { min-height: 36px; background: #ffffff; border: 1px solid #d4d4d4; border-radius: 8px; }
        _ComboTrigger[hovered="true"] { border-color: #737373; }
        _ComboTrigger[open="true"], _ComboTrigger[focused="true"] { border-color: #2b7fff; }
        _ComboTrigger:disabled { border-color: #f5f5f5; }
        _ComboTrigger:disabled QLabel#comboValue, DesignComboBox:disabled QLabel#comboCaption { color: #e5e5e5; }
    """

    def __init__(self, caption: str, items: Iterable[str], parent=None) -> None:
        super().__init__(parent)
        self._items = tuple(items)
        if not self._items:
            raise ValueError("DesignComboBox requires at least one item")
        self._open = False
        self._hovered = False
        self._focused = False
        self.setFixedWidth(216)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.caption = QLabel(caption)
        self.caption.setObjectName("comboCaption")
        layout.addWidget(self.caption)

        self.trigger = _ComboTrigger()
        trigger_layout = QHBoxLayout(self.trigger)
        trigger_layout.setContentsMargins(16, 6, 16, 6)
        self.value_label = QLabel(self._items[0])
        self.value_label.setObjectName("comboValue")
        self.chevron = _ChevronIcon()
        trigger_layout.addWidget(self.value_label)
        trigger_layout.addStretch()
        trigger_layout.addWidget(self.chevron)
        self.trigger.clicked.connect(self.toggle_menu)
        self.trigger.hovered.connect(self._set_hovered)
        self.trigger.focused.connect(self._set_focused)
        layout.addWidget(self.trigger)
        self.menu = _ComboMenu(self._items)
        self.menu.selected.connect(self._select)
        self.menu.closed.connect(lambda: self._set_open(False))
        self.menu.set_current_value(self._items[0])
        self.setStyleSheet(self.QSS)
        self._refresh_state()

    def toggle_menu(self) -> None:
        if not self.isEnabled():
            return
        if self._open:
            self.menu.hide()
            self._set_open(False)
            return
        self.menu.setFixedWidth(self.width() + 48)
        self.menu.adjustSize()
        self.menu.move(self.trigger.mapToGlobal(QPoint(-24, self.trigger.height() - 16)))
        self._set_open(True)
        self.menu.show()

    def hideEvent(self, event) -> None:
        self.menu.hide()
        self._set_open(False)
        super().hideEvent(event)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt API spelling.
        super().setEnabled(enabled)
        self.trigger.setEnabled(enabled)
        if not enabled:
            self.menu.hide()
            self._open = False
        self._refresh_state()

    def _select(self, value: str) -> None:
        self.value_label.setText(value)
        self.menu.set_current_value(value)
        self.menu.hide()
        self._set_open(False)

    def _set_hovered(self, hovered: bool) -> None:
        self._hovered = hovered
        self._refresh_state()

    def _set_open(self, open_: bool) -> None:
        self._open = open_
        self._refresh_state()

    def _set_focused(self, focused: bool) -> None:
        self._focused = focused
        self._refresh_state()

    def _refresh_state(self) -> None:
        self.trigger.setProperty("hovered", "true" if self._hovered and not self._open else "false")
        self.trigger.setProperty("open", "true" if self._open else "false")
        self.trigger.setProperty("focused", "true" if self._focused else "false")
        self.trigger.style().unpolish(self.trigger)
        self.trigger.style().polish(self.trigger)
        disabled = not self.isEnabled()
        self.caption.setStyleSheet(
            f"color: {'#e5e5e5' if disabled else '#404040'}; font-family: 'Segoe UI'; font-size: 14px;"
        )
        self.value_label.setStyleSheet(
            f"color: {'#e5e5e5' if disabled else '#0a0a0a' if self._open or self._hovered else '#404040'}; "
            "font-family: 'Segoe UI'; font-size: 16px;"
        )
        color = "#e5e5e5" if disabled else "#0a0a0a" if self._open or self._hovered else "#737373"
        self.chevron.set_appearance(color, open_=self._open)
