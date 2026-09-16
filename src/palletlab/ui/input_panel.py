"""Reusable Qt form for a single calculation direction."""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from palletlab.core.models import DirectionInput
from palletlab.core.validation import CalculationError

SECTIONS = {
    "70 × 50 мм": (70.0, 50.0),
    "100 × 25 мм": (100.0, 25.0),
    "100 × 100 мм": (100.0, 100.0),
    "100 × 200 мм": (100.0, 200.0),
    "Свой размер": None,
}


class StyledComboBox(QComboBox):
    """A QComboBox with a stable drawn chevron instead of platform arrows."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        arrow_width = 26
        rect = self.rect().adjusted(self.width() - arrow_width, 1, -1, -1)
        painter.fillRect(rect, QColor("#f3f0e9"))
        painter.setPen(QPen(QColor("#466168"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        center_x, center_y = rect.center().x(), rect.center().y()
        painter.drawLine(QPoint(center_x - 4, center_y - 2), QPoint(center_x, center_y + 2))
        painter.drawLine(QPoint(center_x, center_y + 2), QPoint(center_x + 4, center_y - 2))
        painter.end()


class StyledDoubleSpinBox(QDoubleSpinBox):
    """A QDoubleSpinBox whose increment controls remain crisp at every DPI."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(self.width() - 22, 1, -1, -1)
        painter.fillRect(rect, QColor("#f3f0e9") if self.isEnabled() else QColor("#ece9e2"))
        painter.setPen(QPen(QColor("#d8d3c8"), 1))
        painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom())
        middle = rect.center().y()
        painter.drawLine(rect.left(), middle, rect.right(), middle)
        painter.setPen(QPen(QColor("#466168"), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        center_x = rect.center().x()
        painter.drawLine(QPoint(center_x - 3, middle - 4), QPoint(center_x, middle - 7))
        painter.drawLine(QPoint(center_x, middle - 7), QPoint(center_x + 3, middle - 4))
        painter.drawLine(QPoint(center_x - 3, middle + 4), QPoint(center_x, middle + 7))
        painter.drawLine(QPoint(center_x, middle + 7), QPoint(center_x + 3, middle + 4))
        painter.end()


class DirectionInputPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, title: str, description: str, distances: str, first: str, last: str,
                 parent: QWidget | None = None):
        super().__init__(title, parent)
        self.setObjectName("directionCard")
        self.section = StyledComboBox()
        self.section.setObjectName("sectionCombo")
        self.section.addItems(SECTIONS)
        self.height = self._spin(70.0)
        self.width = self._spin(50.0)
        self.distances = QLineEdit(distances)
        self.distances.setPlaceholderText("Например: 1070 460 1300")
        self.first = self._spin(float(first))
        self.last = self._spin(float(last))
        self.margin_start = self._spin(100.0)
        self.margin_end = self._spin(100.0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(10)
        hint = QLabel(description)
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.addRow("Сечение · высота × ширина", self.section)
        form.addRow("Высота", self.height)
        form.addRow("Ширина", self.width)
        form.addRow("Центры соседних опор", self.distances)
        form.addRow("Габарит → первая опора", self.first)
        form.addRow("Последняя опора → габарит", self.last)
        form.addRow("Отступ в начале", self.margin_start)
        form.addRow("Отступ в конце", self.margin_end)
        layout.addLayout(form)
        self.section.currentTextChanged.connect(self._section_changed)
        for field in (self.height, self.width, self.first, self.last, self.margin_start, self.margin_end):
            field.valueChanged.connect(self.changed)
        self.distances.textChanged.connect(self.changed)
        self._section_changed(self.section.currentText())

    @staticmethod
    def _spin(value: float) -> QDoubleSpinBox:
        widget = StyledDoubleSpinBox()
        widget.setDecimals(3)
        widget.setRange(0.0, 1_000_000.0)
        widget.setValue(value)
        widget.setSingleStep(1.0)
        widget.setSuffix(" мм")
        return widget

    def _section_changed(self, name: str) -> None:
        dimensions = SECTIONS[name]
        custom = dimensions is None
        self.height.setEnabled(custom)
        self.width.setEnabled(custom)
        if dimensions:
            self.height.setValue(dimensions[0])
            self.width.setValue(dimensions[1])
        self.changed.emit()

    def values(self) -> DirectionInput:
        raw = self.distances.text().strip().replace(",", ".")
        if not raw:
            raise CalculationError("Заполните расстояния между центрами соседних опор.")
        try:
            distances = tuple(float(token) for token in raw.split())
        except ValueError as exc:
            raise CalculationError("Расстояния между опорами должны быть числами через пробел.") from exc
        return DirectionInput(
            beam_height=self.height.value(), beam_width=self.width.value(), support_distances=distances,
            first_edge_to_support=self.first.value(), last_support_to_edge=self.last.value(),
            margin_start=self.margin_start.value(), margin_end=self.margin_end.value(),
        )

    def reset_example(self, distances: str, first: float, last: float) -> None:
        self.section.setCurrentText("70 × 50 мм")
        self.distances.setText(distances)
        self.first.setValue(first)
        self.last.setValue(last)
        self.margin_start.setValue(100)
        self.margin_end.setValue(100)
