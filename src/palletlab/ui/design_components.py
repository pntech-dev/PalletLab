"""Reusable controls from the PalletLab design system.

Each component owns its QSS so it can be introduced into existing screens
gradually without changing the visual rules of unrelated widgets.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PyQt5.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPixmap, QTransform
from PyQt5.QtSvg import QSvgRenderer, QSvgWidget
from PyQt5.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)


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


class DesignRadioButton(QWidget):
    """20 px radio button with local styling and an exclusive-group friendly API."""

    toggled = pyqtSignal(bool)
    QSS = """
        QFrame#radioIndicator { width: 20px; height: 20px; border: 1px solid #d4d4d4; border-radius: 10px; background: #ffffff; }
        QFrame#radioIndicator[hovered="true"] { border-color: #737373; }
        QFrame#radioIndicator[checked="true"] { border-color: #2b7fff; background: #2b7fff; }
        QFrame#radioIndicator[disabled="true"] { border-color: #e5e5e5; background: #ffffff; }
        QFrame#radioIndicator[checked="true"][disabled="true"] { border-color: #dbeafe; background: #dbeafe; }
        QFrame#radioDot { background: #ffffff; border-radius: 5px; }
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
        self.indicator.setObjectName("radioIndicator")
        self.indicator.setFixedSize(20, 20)
        dot_layout = QHBoxLayout(self.indicator)
        dot_layout.setContentsMargins(4, 4, 4, 4)
        self.dot = QFrame()
        self.dot.setObjectName("radioDot")
        self.dot.setFixedSize(10, 10)
        dot_layout.addWidget(self.dot)
        self.label = QLabel(text)
        layout.addWidget(self.indicator)
        layout.addWidget(self.label)
        layout.addStretch()
        self.setStyleSheet(self.QSS)
        self._refresh_state()

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self._refresh_state()
        self.toggled.emit(checked)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
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
            self.setChecked(True)
        super().mouseReleaseEvent(event)

    def _refresh_state(self) -> None:
        disabled = not self.isEnabled()
        self.indicator.setProperty("checked", "true" if self._checked else "false")
        self.indicator.setProperty("hovered", "true" if self._hovered and not disabled else "false")
        self.indicator.setProperty("disabled", "true" if disabled else "false")
        self.indicator.style().unpolish(self.indicator)
        self.indicator.style().polish(self.indicator)
        self.label.setStyleSheet(
            f"color: {'#e5e5e5' if disabled else '#0a0a0a' if self._hovered or self._checked else '#404040'}; "
            "font-family: 'Segoe UI'; font-size: 16px;"
        )
        self.dot.setVisible(self._checked)


class _DesignLineEdit(QLineEdit):
    hovered = pyqtSignal(bool)
    focused = pyqtSignal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_Hover)

    def enterEvent(self, event) -> None:
        self.hovered.emit(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hovered.emit(False)
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        self.focused.emit(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self.focused.emit(False)
        super().focusOutEvent(event)


class DesignInputField(QFrame):
    """Captioned text input with all Figma states and a demo error rule."""

    QSS = """
        DesignInputField { background: transparent; }
        QLabel#inputCaption { color: #404040; font-family: 'Segoe UI'; font-size: 14px; }
        QFrame#inputSurface { border-radius: 8px; }
        QLineEdit#designInput {
            border: none; background: transparent; padding: 0;
            font-family: 'Segoe UI'; font-size: 16px;
        }
        QLabel#inputError { color: #fb2c36; font-family: 'Segoe UI'; font-size: 14px; }
    """

    def __init__(self, caption: str, *, placeholder: str = "70×50 мм", value: str = "", parent=None) -> None:
        super().__init__(parent)
        self._hovered = False
        self._focused = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.caption = QLabel(caption)
        self.caption.setObjectName("inputCaption")
        layout.addWidget(self.caption)
        self.surface = QFrame()
        self.surface.setObjectName("inputSurface")
        self.surface.setFixedHeight(36)
        surface_layout = QHBoxLayout(self.surface)
        surface_layout.setContentsMargins(16, 6, 16, 6)
        self.line_edit = _DesignLineEdit()
        self.line_edit.setObjectName("designInput")
        self.line_edit.setPlaceholderText(placeholder)
        self.line_edit.setText(value)
        self.line_edit.textChanged.connect(self._refresh_state)
        self.line_edit.hovered.connect(self._set_hovered)
        self.line_edit.focused.connect(self._set_focused)
        surface_layout.addWidget(self.line_edit)
        layout.addWidget(self.surface)
        self.error_label = QLabel("Используйте «×» вместо «x»")
        self.error_label.setObjectName("inputError")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)
        self.setStyleSheet(self.QSS)
        self._refresh_state()

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self.line_edit.setEnabled(enabled)
        self._refresh_state()

    def _set_hovered(self, hovered: bool) -> None:
        self._hovered = hovered
        self._refresh_state()

    def _set_focused(self, focused: bool) -> None:
        self._focused = focused
        self._refresh_state()

    def _refresh_state(self) -> None:
        disabled = not self.isEnabled()
        filled = bool(self.line_edit.text())
        error = not disabled and self.line_edit.text() == "1234"
        if disabled:
            surface_style = "background: #f5f5f5; border: none;"
            text_color = "#a1a1a1" if filled else "#d1d5dc"
            placeholder_color = "#d1d5dc"
        elif error:
            surface_style = "background: #ffffff; border: 1px solid #fb2c36;"
            text_color = "#404040"
            placeholder_color = "#d4d4d8"
        elif self._focused:
            surface_style = "background: #ffffff; border: 1px solid #2b7fff;"
            text_color = "#0a0a0a"
            placeholder_color = "#d4d4d8"
        elif self._hovered:
            surface_style = "background: #ffffff; border: 1px solid #737373;"
            text_color = "#0a0a0a"
            placeholder_color = "#d4d4d8"
        else:
            surface_style = "background: #ffffff; border: 1px solid #d4d4d4;"
            text_color = "#404040" if filled else "#d4d4d8"
            placeholder_color = "#d4d4d8"
        self.surface.setStyleSheet(f"QFrame#inputSurface {{ {surface_style} border-radius: 8px; }}")
        self.line_edit.setStyleSheet(
            "QLineEdit#designInput { border: none; background: transparent; padding: 0; "
            f"color: {text_color}; font-family: 'Segoe UI'; font-size: 16px; }} "
            f"QLineEdit#designInput::placeholder {{ color: {placeholder_color}; }}"
        )
        self.caption.setStyleSheet("color: #404040; font-family: 'Segoe UI'; font-size: 14px;")
        self.error_label.setVisible(error)


class _TextButton(QPushButton):
    """Base class for the three text button visual variants."""

    def __init__(self, text: str, qss: str, parent=None) -> None:
        super().__init__(text, parent)
        self.setFixedHeight(36)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(qss)


class PrimaryButton(_TextButton):
    QSS = """
        PrimaryButton { padding: 6px 16px; color: #ffffff; background: #2b7fff;
                        border: none; border-radius: 8px; font-family: 'Segoe UI'; font-size: 16px; }
        PrimaryButton:hover { background: #51a2ff; }
        PrimaryButton:pressed { background: #155dfc; }
        PrimaryButton:focus { border: 1px solid #2b7fff; border-radius: 8px; }
        PrimaryButton:disabled { color: #ffffff; background: #dbeafe; }
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, self.QSS, parent)
        self.setMinimumWidth(142)


class SecondaryButton(_TextButton):
    QSS = """
        SecondaryButton { padding: 6px 16px; color: #404040; background: #ffffff;
                          border: 1px solid #d4d4d4; border-radius: 8px; font-family: 'Segoe UI'; font-size: 16px; }
        SecondaryButton:hover { color: #0a0a0a; background: #f5f5f5; border-color: #737373; }
        SecondaryButton:pressed { color: #0a0a0a; background: #e5e5e5; border-color: #737373; }
        SecondaryButton:focus { border: 2px solid #2b7fff; border-radius: 8px; }
        SecondaryButton:disabled { color: #e5e5e5; background: #ffffff; border-color: #f5f5f5; }
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, self.QSS, parent)
        self.setMinimumWidth(144)


class TertiaryButton(_TextButton):
    QSS = """
        TertiaryButton { padding: 6px 16px; color: #2b7fff; background: #ffffff;
                         border: none; border-radius: 8px; font-family: 'Segoe UI'; font-size: 16px; }
        TertiaryButton:hover { background: #f5f5f5; }
        TertiaryButton:pressed { background: #e5e5e5; }
        TertiaryButton:focus { border: 1px solid #2b7fff; border-radius: 8px; }
        TertiaryButton:disabled { color: #e5e5e5; background: #ffffff; }
    """

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, self.QSS, parent)
        self.setMinimumWidth(142)


class _TintedSvgIcon(QLabel):
    """A local SVG tinted at run time, so button states do not need duplicate assets."""

    def __init__(self, asset_name: str, *, size: int = 20, parent=None) -> None:
        super().__init__(parent)
        self._path = Path(__file__).parent / "assets" / "icons" / asset_name
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)

    def set_color(self, color: str) -> None:
        source = QPixmap(self._size, self._size)
        source.fill(Qt.transparent)
        renderer = QSvgRenderer(str(self._path))
        painter = QPainter(source)
        renderer.render(painter)
        painter.end()
        result = QPixmap(self._size, self._size)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(result.rect(), QColor(color))
        painter.end()
        self.setPixmap(result)


class _BaseIconButton(QFrame):
    clicked = pyqtSignal()

    def __init__(self, icon_name: str, text: str | None, parent=None) -> None:
        super().__init__(parent)
        self._hovered = False
        self._pressed = False
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        self.icon = _TintedSvgIcon(icon_name)
        layout.addWidget(self.icon)
        self.label = None
        if text is not None:
            self.label = QLabel(text)
            layout.addWidget(self.label)
        self._refresh_state()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._refresh_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._refresh_state()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.isEnabled() and event.button() == Qt.LeftButton:
            self._pressed = True
            self._refresh_state()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self._refresh_state()
        if was_pressed and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def focusInEvent(self, event) -> None:
        self._refresh_state()
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:
        self._refresh_state()
        super().focusOutEvent(event)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        super().setEnabled(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self._refresh_state()

    def _refresh_state(self) -> None:
        background, icon_color, text_color = self._state_colors()
        focus_border = "1px solid #2b7fff" if self.hasFocus() and self.isEnabled() else "none"
        self.setStyleSheet(f"QFrame {{ background: {background}; border: {focus_border}; border-radius: 8px; }}")
        self.icon.set_color(icon_color)
        if self.label is not None:
            self.label.setStyleSheet(f"color: {text_color}; font-family: 'Segoe UI'; font-size: 16px;")

    def _state_colors(self) -> tuple[str, str, str]:
        raise NotImplementedError


class IconButton(_BaseIconButton):
    """Icon + optional text action button from the Figma icon_button component."""

    def __init__(self, text: str = "Добавить", *, icon_name: str = "plus.svg", parent=None) -> None:
        super().__init__(icon_name, text, parent)

    def _state_colors(self) -> tuple[str, str, str]:
        if not self.isEnabled():
            return "#ffffff", "#d4d4d4", "#d4d4d4"
        if self._pressed:
            return "#f5f5f5", "#0a0a0a", "#0a0a0a"
        if self._hovered:
            return "#fafafa", "#404040", "#404040"
        return "#ffffff", "#737373", "#737373"


class CloseButton(_BaseIconButton):
    """Standalone close action; its icon palette intentionally differs from IconButton."""

    def __init__(self, parent=None) -> None:
        super().__init__("cross.svg", None, parent)

    def _state_colors(self) -> tuple[str, str, str]:
        if not self.isEnabled():
            return "#ffffff", "#e5e5e5", "#e5e5e5"
        if self._pressed:
            return "#e5e5e5", "#0a0a0a", "#0a0a0a"
        if self._hovered:
            return "#f5f5f5", "#0a0a0a", "#0a0a0a"
        return "#ffffff", "#404040", "#404040"


class _MessageBox(QFrame):
    """Shared layout for information and warning callouts."""

    def __init__(self, title: str, text: str, *, icon_name: str, background: str, border: str, foreground: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("messageBox")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.icon = _TintedSvgIcon(icon_name, size=24)
        self.icon.set_color(foreground)
        layout.addWidget(self.icon, alignment=Qt.AlignTop)
        text_layout = QVBoxLayout()
        text_layout.setSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"color: {foreground}; font-family: 'Segoe UI'; font-size: 18px; font-weight: 700;")
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setStyleSheet(f"color: {foreground}; font-family: 'Segoe UI'; font-size: 16px;")
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.text_label)
        layout.addLayout(text_layout, 1)
        self.setStyleSheet(
            f"QFrame#messageBox {{ background: {background}; border: 1px solid {border}; border-radius: 16px; }}"
        )


class WarningBox(_MessageBox):
    """Orange warning callout requiring a title and explanatory text."""

    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(
            title, text,
            icon_name="warning.svg", background="#fff7ed", border="#ffb86a", foreground="#894b00", parent=parent,
        )


class InfoBox(_MessageBox):
    """Blue informational callout requiring a title and explanatory text."""

    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(
            title, text,
            icon_name="info.svg", background="#eff6ff", border="#8ec5ff", foreground="#193cb8", parent=parent,
        )


class NumberIndicator(QFrame):
    """A compact numbered marker used to annotate controls and instructions."""

    def __init__(self, number: int | str = 1, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("numberIndicator")
        self.setFixedSize(28, 28)
        self.setStyleSheet(
            "QFrame#numberIndicator { background: #2b7fff; border: none; border-radius: 14px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.number_label = QLabel(str(number))
        self.number_label.setAlignment(Qt.AlignCenter)
        self.number_label.setStyleSheet(
            "color: #ffffff; background: transparent; border: none; "
            "font-family: 'Segoe UI'; font-size: 18px; font-weight: 700;"
        )
        layout.addWidget(self.number_label)

    def set_number(self, number: int | str) -> None:
        """Change the visible marker number without recreating the component."""
        self.number_label.setText(str(number))


class InfoHint(QWidget):
    """Inline help text paired with a caller-supplied SVG icon."""

    def __init__(self, icon_name: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("infoHint")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.icon = _TintedSvgIcon(icon_name, size=20)
        self.icon.set_color("#737373")
        layout.addWidget(self.icon)
        self.text_label = QLabel(text)
        self.text_label.setStyleSheet(
            "color: #737373; font-family: 'Segoe UI'; font-size: 14px; "
            "background: transparent; border: none;"
        )
        layout.addWidget(self.text_label)


class PalletSizeProperty(QWidget):
    """A pallet dimension display whose axis selects its own icon and label."""

    _AXES = {
        "x": ("size-X.svg", "Длина"),
        "y": ("size-y.svg", "Ширина"),
        "z": ("size-Z.svg", "Высота"),
    }

    def __init__(self, axis: str, size: int | float | str, parent=None) -> None:
        super().__init__(parent)
        axis_key = axis.lower()
        if axis_key not in self._AXES:
            raise ValueError("axis must be one of: 'x', 'y', 'z'")

        icon_name, label = self._AXES[axis_key]
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setMinimumHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        icon_surface = QFrame()
        icon_surface.setObjectName("sizePropertyIconSurface")
        icon_surface.setFixedSize(40, 40)
        icon_surface.setStyleSheet(
            "QFrame#sizePropertyIconSurface { background: #f5f5f5; border: none; border-radius: 8px; }"
        )
        icon_layout = QVBoxLayout(icon_surface)
        icon_layout.setContentsMargins(8, 8, 8, 8)
        self.icon = _TintedSvgIcon(icon_name, size=24)
        self.icon.set_color("#737373")
        icon_layout.addWidget(self.icon)
        layout.addWidget(icon_surface)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        self.label = QLabel(label)
        self.label.setStyleSheet(
            "color: #404040; font-family: 'Segoe UI'; font-size: 16px; "
            "font-weight: 400; background: transparent; border: none;"
        )
        self.value = QLabel(self._format_size(size))
        self.value.setStyleSheet(
            "color: #0a0a0a; font-family: 'Segoe UI'; font-size: 16px; "
            "font-weight: 700; background: transparent; border: none;"
        )
        content.addWidget(self.label)
        content.addWidget(self.value)
        layout.addLayout(content)

    @staticmethod
    def _format_size(size: int | float | str) -> str:
        value = str(size)
        return value if value.lower().endswith("мм") else f"{value} мм"

    def set_size(self, size: int | float | str) -> None:
        """Update the displayed dimension while preserving its unit formatting."""
        self.value.setText(self._format_size(size))


class MaterialProperty(QWidget):
    """A timber material preview composed from a local beam SVG and its data."""

    BEAM_SVG_PATH = Path(__file__).parent / "assets" / "illustrations" / "material-beam.svg"

    def __init__(self, section: str, size: int | float | str, quantity: int, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.preview = QFrame()
        self.preview.setObjectName("materialPreview")
        self.preview.setFixedSize(78, 62)
        self.preview.setStyleSheet(
            "QFrame#materialPreview { background: #f5f5f5; border: none; border-radius: 16px; }"
        )
        preview_layout = QHBoxLayout(self.preview)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        self.beam = QSvgWidget(str(self.BEAM_SVG_PATH)) if self.BEAM_SVG_PATH.exists() else QSvgWidget()
        self.beam.setObjectName("materialBeam")
        self.beam.setFixedSize(46, 46)
        preview_layout.addWidget(self.beam, alignment=Qt.AlignCenter)
        layout.addWidget(self.preview, alignment=Qt.AlignTop)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(4)
        self.name_label = QLabel(f"Брус {section}x{size}")
        self.name_label.setStyleSheet(
            "color: #0a0a0a; font-family: 'Segoe UI'; font-size: 16px; "
            "font-weight: 700; background: transparent; border: none;"
        )
        self.quantity_label = QLabel(f"Кол-во: {quantity} шт.")
        self.quantity_label.setStyleSheet(
            "color: #404040; font-family: 'Segoe UI'; font-size: 16px; "
            "font-weight: 400; background: transparent; border: none;"
        )
        content.addWidget(self.name_label)
        content.addWidget(self.quantity_label)
        layout.addLayout(content)


class DesignSegmentedControl(QFrame):
    """Exclusive segmented control built from custom QSS-styled segment buttons."""

    changed = pyqtSignal(int)
    QSS = """
        DesignSegmentedControl { background: #ffffff; border: 1px solid #d4d4d4; border-radius: 8px; }
        QFrame#segmentCarriage { background: #2b7fff; border: none; border-radius: 6px; }
        QPushButton#segmentButton {
            padding: 3px 16px; border: none; border-radius: 6px;
            color: #737373; background: transparent; font-family: 'Segoe UI'; font-size: 16px;
        }
        QPushButton#segmentButton:checked { color: #ffffff; background: transparent; }
        QPushButton#segmentButton:disabled { color: #e5e5e5; background: transparent; }
    """

    def __init__(self, items: Iterable[str], *, selected_index: int = 0, disabled_indices: Iterable[int] = (), parent=None) -> None:
        super().__init__(parent)
        self._buttons: list[QPushButton] = []
        self._selected_index = -1
        disabled = set(disabled_indices)
        values = tuple(items)
        if not values:
            raise ValueError("DesignSegmentedControl requires at least one segment")
        # 1 px border + 2 px inner gap on either side of the 109 px segments.
        self.setFixedSize(6 + 109 * len(values), 36)
        self._carriage = QFrame(self)
        self._carriage.setObjectName("segmentCarriage")
        self._carriage.setFixedSize(109, 30)
        self._animation = QPropertyAnimation(self._carriage, b"geometry", self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignLeft)
        for index, text in enumerate(values):
            button = QPushButton(text)
            button.setObjectName("segmentButton")
            button.setFixedSize(109, 30)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setEnabled(index not in disabled)
            button.pressed.connect(lambda value=index: self.setCurrentIndex(value))
            layout.addWidget(button)
            self._buttons.append(button)
        self.setStyleSheet(self.QSS)
        self.setCurrentIndex(selected_index)

    def currentIndex(self) -> int:  # noqa: N802
        return self._selected_index

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < len(self._buttons) or not self._buttons[index].isEnabled():
            return
        if index == self._selected_index:
            return
        previous_index = self._selected_index
        self._selected_index = index
        for button_index, button in enumerate(self._buttons):
            button.setChecked(button_index == index)
        target = QRect(3 + 109 * index, 3, 109, 30)
        if previous_index < 0:
            self._carriage.setGeometry(target)
        else:
            self._animation.stop()
            self._animation.setStartValue(self._carriage.geometry())
            self._animation.setEndValue(target)
            self._animation.start()
        self._carriage.lower()
        self.changed.emit(index)


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
