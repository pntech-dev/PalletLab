"""Reusable Qt form for a single calculation direction."""

from __future__ import annotations

from dataclasses import replace

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from palletlab.core.models import DirectionInput
from palletlab.core.validation import CalculationError

SECTIONS = {
    "70 × 50 мм": (70.0, 50.0),
    "25 × 100 мм": (25.0, 100.0),
    "100 × 100 мм": (100.0, 100.0),
    "100 × 200 мм": (100.0, 200.0),
    "Свой размер": None,
}


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """Keep numeric values stable while the parent form is being scrolled."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class NoWheelComboBox(QComboBox):
    """Prevent accidental section changes while scrolling the parameters pane."""

    def wheelEvent(self, event) -> None:
        event.ignore()


class DirectionInputPanel(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, title: str, description: str, distances: str, first: str, last: str,
                 parent: QWidget | None = None):
        super().__init__(title, parent)
        self.setObjectName("directionCard")
        self.section = NoWheelComboBox()
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
        self._model_input: DirectionInput | None = None
        self._model_offset_rows_removed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(10)
        hint = QLabel(description)
        hint.setObjectName("sectionHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self._form = QFormLayout()
        self._form.setSpacing(8)
        self._form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._form.addRow("Сечение · высота × ширина", self.section)
        self._form.addRow("Высота", self.height)
        self._form.addRow("Ширина", self.width)
        self._form.addRow("Центры соседних опор", self.distances)
        self._first_label = QLabel("Габарит → первая опора")
        self._last_label = QLabel("Последняя опора → габарит")
        self._form.addRow(self._first_label, self.first)
        self._form.addRow(self._last_label, self.last)
        self._form.addRow("Отступ в начале", self.margin_start)
        self._form.addRow("Отступ в конце", self.margin_end)
        layout.addLayout(self._form)
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
        """Notify the owner about an editable pallet parameter change."""
        if self._model_input is not None:
            # The host rebuilds a model-driven pallet from its detected support
            # faces.  Do not discard those support coordinates merely because a
            # user changes a beam section or an outer margin.
            self.changed.emit()
            return
        self._support_positions_override = None
        self.changed.emit()

    def values(self, round_pallet_size: bool = False, rounding_step: int = 5) -> DirectionInput:
        raw = self.distances.text().strip().replace(",", ".")
        try:
            distances = tuple(float(token) for token in raw.split()) if raw else ()
        except ValueError as exc:
            raise CalculationError("Расстояния между опорами должны быть числами через пробел.") from exc
        if self._model_input is not None:
            # The hidden distances from the pallet edge to the first/last
            # support are still obtained from the selected model faces.  The
            # visible values, however, remain editable in the layer editor.
            # Keeping ``support_positions`` here would make
            # ``calculate_direction`` ignore those edits altogether.
            return replace(
                self._model_input,
                beam_height=self.height.value(),
                beam_width=self.width.value(),
                support_distances=distances,
                margin_start=self.margin_start.value(),
                margin_end=self.margin_end.value(),
                support_positions=None,
                round_pallet_size=round_pallet_size,
                rounding_step=rounding_step,
            )
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

    def apply_position_data(self, data: DirectionInput, *, notify: bool = True) -> None:
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
        if notify:
            self.changed.emit()

    def set_model_driven_mode(self, data: DirectionInput | None, *, hide_model_offsets: bool = False) -> None:
        """Show or hide geometry-derived offsets for the STEP-model workflow."""
        self._model_input = data
        locked = data is not None or hide_model_offsets
        if locked and not self._model_offset_rows_removed:
            # Hiding child widgets leaves QFormLayout's row spacing behind.
            # Remove both rows so the adjacent controls use the regular gap.
            self._form.takeRow(self.last)
            self._form.takeRow(self.first)
            self._first_label.hide()
            self._last_label.hide()
            self.first.hide()
            self.last.hide()
            self._model_offset_rows_removed = True
        elif not locked and self._model_offset_rows_removed:
            self._form.insertRow(4, self._first_label, self.first)
            self._form.insertRow(5, self._last_label, self.last)
            self._first_label.show()
            self._last_label.show()
            self.first.show()
            self.last.show()
            self._model_offset_rows_removed = False
        if locked:
            for field in (self.first, self.last):
                field.blockSignals(True)
                field.setValue(0.0)
                field.blockSignals(False)

    def reset_example(self, distances: str, first: float, last: float) -> None:
        self._support_positions_override = None
        self.section.setCurrentText("70 × 50 мм")
        self.distances.setText(distances)
        self.first.setValue(first)
        self.last.setValue(last)
        self.margin_start.setValue(100)
        self.margin_end.setValue(100)
