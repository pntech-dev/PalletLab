"""Reusable Qt form for a single calculation direction."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
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


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """Keep numeric values stable while the parent form is being scrolled."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class DirectionInputPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, title: str, description: str, distances: str, first: str, last: str,
                 parent: QWidget | None = None):
        super().__init__(title, parent)
        self.setObjectName("directionCard")
        self.section = QComboBox()
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
        self._support_positions_override: tuple[float, ...] | None = None
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
            field.valueChanged.connect(self._position_data_changed)
        self.distances.textChanged.connect(self._position_data_changed)
        self._section_changed(self.section.currentText())

    @staticmethod
    def _spin(value: float) -> QDoubleSpinBox:
        widget = NoWheelDoubleSpinBox()
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

    def _position_data_changed(self, *_args) -> None:
        """Manual edits resume the normal distances-based calculation."""
        self._support_positions_override = None
        self.changed.emit()

    def values(self, round_pallet_size: bool = False, rounding_step: int = 5) -> DirectionInput:
        raw = self.distances.text().strip().replace(",", ".")
        try:
            distances = tuple(float(token) for token in raw.split()) if raw else ()
        except ValueError as exc:
            raise CalculationError("Расстояния между опорами должны быть числами через пробел.") from exc
        support_positions = self._support_positions_override
        # With no inter-support distances, zero values on both sides mean the
        # user intentionally removed every internal support.  Keep only the
        # two structural edge beams instead of inventing a central one.
        if support_positions is None and not distances and self.first.value() == 0 and self.last.value() == 0:
            support_positions = ()
        return DirectionInput(
            beam_height=self.height.value(), beam_width=self.width.value(), support_distances=distances,
            first_edge_to_support=self.first.value(), last_support_to_edge=self.last.value(),
            margin_start=self.margin_start.value(), margin_end=self.margin_end.value(),
            round_pallet_size=round_pallet_size,
            rounding_step=rounding_step,
            support_positions=support_positions,
        )

    def apply_position_data(self, data: DirectionInput) -> None:
        """Update only the position fields after an interactive 3D insertion."""
        fields = (self.distances, self.first, self.last, self.margin_start, self.margin_end)
        for field in fields:
            field.blockSignals(True)
        self.distances.setText(" ".join(f"{value:g}" for value in data.support_distances))
        self.first.setValue(data.first_edge_to_support)
        self.last.setValue(data.last_support_to_edge)
        self.margin_start.setValue(data.margin_start)
        self.margin_end.setValue(data.margin_end)
        for field in fields:
            field.blockSignals(False)
        self._support_positions_override = data.support_positions
        self.changed.emit()

    def reset_example(self, distances: str, first: float, last: float) -> None:
        self._support_positions_override = None
        self.section.setCurrentText("70 × 50 мм")
        self.distances.setText(distances)
        self.first.setValue(first)
        self.last.setValue(last)
        self.margin_start.setValue(100)
        self.margin_end.setValue(100)
