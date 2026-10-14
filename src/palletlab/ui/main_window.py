"""Main desktop window for calculating and visualising a wooden pallet."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt5.QtCore import QEvent, QProcess, QProcessEnvironment, QSettings, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QDoubleSpinBox, QProgressDialog, QRadioButton, QScrollArea, QShortcut, QSplitter, QVBoxLayout, QWidget)

from palletlab.controllers.pallet_controller import PalletController
from palletlab.core.calculator import calculate_direction, insertion_slots_for_direction
from palletlab.core.formatting import format_mm
from palletlab.core.materials import MATERIALS, get_material, pallet_mass_kg
from palletlab.core.models import BeamSection, InsertionSlot, LayerInput, PalletAxis
from palletlab.core.project_state import ProjectHistory, ProjectState
from palletlab.core.validation import CalculationError
from palletlab.exporters.kompas import KompasExportError, export_pallet as export_kompas_pallet
from palletlab.exporters.solidworks import SolidWorksExportError, SolidWorksMaterialLibraryError, SolidWorksTemplateError, available_materials, export_pallet
from palletlab.ui import resources_rc  # Registers SVGs used by the application QSS.
from palletlab.ui.input_panel import DirectionInputPanel, SECTIONS
from palletlab.ui.update_dialog import check_for_updates
from palletlab.version import __version__
from palletlab.visualization.pallet_view import PalletView

if TYPE_CHECKING:
    from palletlab.importers.step_model import ImportedStepModel


class InsertionGapSpinBox(QDoubleSpinBox):
    """Numeric editor whose Enter/Escape semantics match the 3D insert workflow."""

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.confirmed.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class BeamSectionDialog(QDialog):
    """Choose one standard or custom cross-section for selected beams."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Изменить сечение брусьев")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Новое сечение применяется ко всем выделенным брусьям."))
        form = QFormLayout()
        self.section_combo = QComboBox()
        self.section_combo.addItems(SECTIONS)
        self.height = QDoubleSpinBox()
        self.width = QDoubleSpinBox()
        for field in (self.height, self.width):
            field.setRange(1.0, 1_000_000.0)
            field.setDecimals(3)
            field.setSuffix(" мм")
            field.setSingleStep(1.0)
        form.addRow("Сечение · высота × ширина", self.section_combo)
        form.addRow("Высота", self.height)
        form.addRow("Ширина", self.width)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.section_combo.currentTextChanged.connect(self._section_changed)
        self._section_changed(self.section_combo.currentText())

    def _section_changed(self, name: str) -> None:
        values = SECTIONS[name]
        custom = values is None
        self.height.setEnabled(custom)
        self.width.setEnabled(custom)
        if values is not None:
            self.height.setValue(values[0])
            self.width.setValue(values[1])

    def section(self) -> BeamSection:
        return BeamSection(self.height.value(), self.width.value())


class ManualBeamDialog(BeamSectionDialog):
    """Parameters of one beam placed between two selected supports."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Новый брус")
        self.layout().insertWidget(1, QLabel("Расстояние задаёт положение бруса вдоль выбранных опор."))
        self.reference = QComboBox()
        self.reference.addItem("От базовой точки (0)", False)
        self.reference.addItem("От выбранной грани", True)
        self.distance = QDoubleSpinBox()
        self.distance.setRange(-1_000_000, 1_000_000)
        self.distance.setDecimals(3)
        self.distance.setSuffix(" мм")
        self.pick_reference = QPushButton("Выбрать грань объекта")
        self.pick_reference.setVisible(False)
        form = QFormLayout()
        form.addRow("Точка отсчёта", self.reference)
        form.addRow("Расстояние", self.distance)
        form.addRow("", self.pick_reference)
        self.layout().insertLayout(2, form)
        self.reference.currentIndexChanged.connect(lambda: self.pick_reference.setVisible(bool(self.reference.currentData())))
        self.pick_reference.clicked.connect(lambda: self.done(2))


class MainWindow(QMainWindow):
    # Transitional aliases keep the existing event handlers stable while their
    # data is now owned by ProjectState. They will disappear with the
    # controller extraction in the next MVC steps.
    @property
    def _last_result(self):
        return self.state.result

    @_last_result.setter
    def _last_result(self, value) -> None:
        self.state.result = value

    @property
    def _last_inputs(self) -> dict[PalletAxis, object]:
        return {
            "length": self.state.length_input,
            "width": self.state.width_input,
        }

    @_last_inputs.setter
    def _last_inputs(self, values) -> None:
        self.state.length_input = values["length"]
        self.state.width_input = values["width"]

    @property
    def _pending_insertion(self) -> InsertionSlot | None:
        return self.state.pending_insertion

    @_pending_insertion.setter
    def _pending_insertion(self, value: InsertionSlot | None) -> None:
        self.state.pending_insertion = value

    @property
    def _pending_distance(self) -> tuple[PalletAxis, int] | None:
        return self.state.pending_distance

    @_pending_distance.setter
    def _pending_distance(self, value: tuple[str, int] | None) -> None:
        self.state.pending_distance = value

    @property
    def _selected_for_deletion(self) -> dict[str, set[int]]:
        return self.state.selected_for_deletion

    @_selected_for_deletion.setter
    def _selected_for_deletion(self, value: dict[str, set[int]]) -> None:
        self.state.selected_for_deletion = value

    @property
    def _selected_for_section(self) -> dict[str, set[int]]:
        return self.state.selected_for_section

    def __init__(self) -> None:
        super().__init__()
        self.state = ProjectState()
        self._history = ProjectHistory()
        self._pending_history_snapshot: ProjectState | None = None
        self._history_restoring = False
        self._project_path: str | None = None
        self._imported_step_model: ImportedStepModel | None = None
        self._step_import_process: QProcess | None = None
        self._step_import_path: str | None = None
        self._step_import_output = ""
        self._step_import_error: str | None = None
        self._step_import_progress: QProgressDialog | None = None
        self._model_supports = ()
        self._model_reference_support_index: int | None = None
        self._model_rebuild_timer = QTimer(self)
        self._model_rebuild_timer.setSingleShot(True)
        self._model_rebuild_timer.setInterval(300)
        self._model_rebuild_timer.timeout.connect(self._build_selected_model_pallet)
        self.setWindowTitle(f"PalletLab {__version__} — расчёт поддонов")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1400, int(screen.width() * 0.92)), min(900, int(screen.height() * 0.90)))
        self.setMinimumSize(900, 650)
        self.length_panel = DirectionInputPanel("01  Длина", "Центры опор задаются по оси X. Эти координаты определяют поперечные брусья.", "1070 460 1300 499", "123", "552")
        self.width_panel = DirectionInputPanel("02  Ширина", "Центры опор задаются по оси Y. Эти координаты определяют продольные брусья.", "560 720", "277", "179")
        self.top_length_panel = DirectionInputPanel("03  Длина", "Центры опор задаются по оси X. Эти координаты определяют поперечные брусья.", "1070 460 1300 499", "123", "552")
        self._layer_order = ["length", "width", "layer-1"]
        self._layer_panels: dict[str, DirectionInputPanel] = {
            "length": self.length_panel, "width": self.width_panel, "layer-1": self.top_length_panel,
        }
        self._layer_axes: dict[str, PalletAxis] = {"length": "length", "width": "width", "layer-1": "length"}
        # Reordering cards must never destroy a reusable DirectionInputPanel.
        # Keep detached wrappers alive for the window lifetime; there are only
        # a few of them and this avoids Qt deleting a child queued for reuse.
        self._retired_layer_cards: list[QFrame] = []
        self._layer_rebuild_timer = QTimer(self)
        self._layer_rebuild_timer.setSingleShot(True)
        self._layer_rebuild_timer.setInterval(300)
        self._layer_rebuild_timer.timeout.connect(self._calculate_layer_stack)
        self._layer_envelope_source: str | None = None
        self._manual_supports: list[tuple[str, int, str]] = []
        self.width_upper = QPushButton("Вдоль ширины")
        self.length_upper = QPushButton("Вдоль длины")
        self.layer_buttons = QButtonGroup(self)
        for button in (self.width_upper, self.length_upper):
            button.setCheckable(True)
            self.layer_buttons.addButton(button)
        self.width_upper.setChecked(True)
        self.view = PalletView(self)
        self.controller = PalletController(
            self.state,
            self.view,
            on_calculated=self._update_scene_info,
            on_error=self._handle_calculation_error,
            on_stale_changed=self._set_stale,
            input_provider=self._read_calculation_inputs,
            on_project_loaded=self._apply_loaded_project,
            parent=self,
        )
        self.show_length_gaps = QCheckBox("Расстояния по длине")
        self.show_width_gaps = QCheckBox("Расстояния по ширине")
        self.show_length_gaps.setChecked(True)
        self.show_width_gaps.setChecked(True)
        self.scene_info = QLabel()
        self.scene_info.setObjectName("sceneInfo")
        self.scene_info.setWordWrap(True)
        self.camera_combo = QComboBox()
        self.camera_combo.addItem("Изометрия", "isometric")
        self.camera_combo.addItem("Сверху", "top")
        self.camera_combo.addItem("Спереди", "front")
        self.camera_combo.addItem("Сбоку", "side")
        self._build_ui()
        self._undo_shortcut = QShortcut(QKeySequence.Undo, self)
        self._undo_shortcut.setContext(Qt.ApplicationShortcut)
        self._undo_shortcut.activated.connect(self.undo)
        self._redo_shortcut = QShortcut(QKeySequence("Ctrl+U"), self)
        self._redo_shortcut.setContext(Qt.ApplicationShortcut)
        self._redo_shortcut.activated.connect(self.redo)
        self._set_stale(False)
        self.calculate()
        QTimer.singleShot(1500, self._check_for_updates)

    def _check_for_updates(self) -> None:
        self._update_worker = check_for_updates(self)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(20, 16, 20, 18)
        root_layout.setSpacing(14)
        root_layout.addWidget(self._header())
        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("workspace")
        splitter.setChildrenCollapsible(False)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(4, 4, 8, 4)
        controls_layout.setSpacing(12)
        heading = QLabel("Параметры расчёта")
        heading.setObjectName("paneTitle")
        controls_layout.addWidget(heading)
        note = QLabel("Введите расстояния между центрами соседних опор. Запятая в десятичных числах поддерживается.")
        note.setObjectName("paneHint")
        note.setWordWrap(True)
        controls_layout.addWidget(note)
        self.layer_stack_card = QFrame()
        self.layer_stack_card.setObjectName("layerStackCard")
        self.layer_stack_layout = QVBoxLayout(self.layer_stack_card)
        self.layer_stack_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_stack_layout.setSpacing(10)
        controls_layout.addWidget(self.layer_stack_card)
        self.layer_card = QFrame()
        self.layer_card.setObjectName("layerCard")
        layer_layout = QVBoxLayout(self.layer_card)
        layer_layout.setContentsMargins(16, 14, 16, 14)
        layer_layout.addWidget(QLabel("Верхний слой"))
        layer_hint = QLabel("Выберите, какая группа брусьев лежит сверху.")
        layer_hint.setObjectName("sectionHint")
        layer_layout.addWidget(layer_hint)
        choices = QHBoxLayout()
        choices.setSpacing(6)
        choices.addWidget(self.width_upper)
        choices.addWidget(self.length_upper)
        layer_layout.addLayout(choices)
        controls_layout.addWidget(self.layer_card)
        controls_layout.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("parametersScroll")
        scroll.setWidgetResizable(True)
        scroll.setViewportMargins(0, 0, 8, 0)
        scroll.setWidget(controls)
        action_panel = QFrame()
        action_panel.setObjectName("actionPanel")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(14, 12, 14, 12)
        rounding_title = QLabel("Округление габарита поддона")
        rounding_title.setObjectName("roundingTitle")
        action_layout.addWidget(rounding_title)
        self.round_to_50 = QRadioButton("До 50 мм")
        self.round_to_50.setToolTip("Остаток меньше 10 мм отбрасывается, иначе размер увеличивается до следующего 50 мм.")
        self.round_to_5 = QRadioButton("До 5 мм")
        self.round_to_5.setToolTip("Сохраняет текущее правило: размер увеличивается до следующего 5 мм.")
        self.no_rounding = QRadioButton("Не округлять")
        self.no_rounding.setToolTip("Использовать точный расчётный габарит.")
        self.rounding_buttons = QButtonGroup(self)
        self.rounding_buttons.addButton(self.round_to_50, 50)
        self.rounding_buttons.addButton(self.round_to_5, 5)
        self.rounding_buttons.addButton(self.no_rounding, 0)
        self.round_to_50.setChecked(True)
        rounding_choices = QHBoxLayout()
        rounding_choices.setSpacing(12)
        for button in (self.round_to_50, self.round_to_5, self.no_rounding):
            rounding_choices.addWidget(button)
        rounding_choices.addStretch()
        action_layout.addLayout(rounding_choices)
        auto_calculate_hint = QLabel("Модель перестраивается автоматически после изменения параметров.")
        auto_calculate_hint.setObjectName("sectionHint")
        auto_calculate_hint.setWordWrap(True)
        action_layout.addWidget(auto_calculate_hint)
        material_row = QHBoxLayout()
        material_row.addWidget(QLabel("Материал брусьев"))
        self.material_combo = QComboBox()
        for material in MATERIALS.values():
            self.material_combo.addItem(material.name, material.id)
        self.material_combo.currentIndexChanged.connect(self._material_changed)
        material_row.addWidget(self.material_combo, 1)
        action_layout.addLayout(material_row)
        reset_button = QPushButton("Сбросить пример")
        reset_button.clicked.connect(self.reset_example)
        reset_button.setMinimumHeight(42)
        action_layout.addWidget(reset_button)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(10)
        sidebar_layout.addWidget(scroll, 1)
        sidebar_layout.addWidget(action_panel)
        splitter.addWidget(sidebar)
        viewport = QWidget()
        viewport_layout = QVBoxLayout(viewport)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setSpacing(6)
        view_heading = QHBoxLayout()
        title_block = QVBoxLayout()
        view_title = QLabel("3D-модель поддона")
        view_title.setObjectName("paneTitle")
        view_title.setToolTip("Вращайте модель мышью, колёсиком меняйте масштаб.")
        title_block.addWidget(view_title)
        view_heading.addLayout(title_block)
        self.rebuild_from_model_button = QPushButton("Перестроить по модели")
        self.rebuild_from_model_button.setObjectName("rebuildFromModelButton")
        self.rebuild_from_model_button.setToolTip("Удалить поддон и заново выбрать грань опоры уже загруженной модели.")
        self.rebuild_from_model_button.setEnabled(False)
        self.rebuild_from_model_button.setVisible(False)
        self.rebuild_from_model_button.clicked.connect(self.rebuild_from_model)
        view_heading.addWidget(self.rebuild_from_model_button)
        self.toggle_model_button = QPushButton("Скрыть 3D модель")
        self.toggle_model_button.setObjectName("toggleModelButton")
        self.toggle_model_button.setEnabled(False)
        self.toggle_model_button.setVisible(False)
        self.toggle_model_button.clicked.connect(self._toggle_model_visibility)
        view_heading.addWidget(self.toggle_model_button)
        self.add_beam_button = QPushButton("＋ Добавить брус")
        self.add_beam_button.setObjectName("addBeamButton")
        self.add_beam_button.setCheckable(True)
        self.add_beam_button.setToolTip("Показать места, куда можно добавить брус.")
        self.add_beam_button.toggled.connect(self._toggle_insertion_mode)
        view_heading.addWidget(self.add_beam_button)
        self.delete_beam_button = QPushButton("− Удалить брусья")
        self.delete_beam_button.setObjectName("deleteBeamButton")
        self.delete_beam_button.setCheckable(True)
        self.delete_beam_button.setToolTip("Выбрать один или несколько внутренних брусьев для удаления.")
        self.delete_beam_button.toggled.connect(self._toggle_deletion_mode)
        view_heading.addWidget(self.delete_beam_button)
        self.edit_distance_button = QPushButton("↔ Изменить расстояние")
        self.edit_distance_button.setObjectName("editDistanceButton")
        self.edit_distance_button.setCheckable(True)
        self.edit_distance_button.setToolTip("Выбрать размерную линию и изменить расстояние либо общий габарит.")
        self.edit_distance_button.toggled.connect(self._toggle_distance_editing)
        view_heading.addWidget(self.edit_distance_button)
        self.change_section_button = QPushButton("▣ Изменить сечение")
        self.change_section_button.setObjectName("changeSectionButton")
        self.change_section_button.setCheckable(True)
        self.change_section_button.setToolTip("Выбрать брусья и назначить им другое сечение.")
        self.change_section_button.toggled.connect(self._toggle_section_editing)
        view_heading.addWidget(self.change_section_button)
        self.insertion_editor = QFrame()
        self.insertion_editor.setObjectName("insertionEditor")
        insertion_layout = QHBoxLayout(self.insertion_editor)
        insertion_layout.setContentsMargins(8, 4, 8, 4)
        insertion_layout.setSpacing(6)
        insertion_layout.addWidget(QLabel("Зазор:"))
        self.insertion_gap = InsertionGapSpinBox()
        self.insertion_gap.setRange(0, 1_000_000)
        self.insertion_gap.setDecimals(2)
        self.insertion_gap.setSuffix(" мм")
        self.insertion_gap.setMinimumWidth(106)
        self.insertion_gap.valueChanged.connect(self._update_insertion_preview)
        self.insertion_gap.confirmed.connect(self._confirm_insertion)
        self.insertion_gap.cancelled.connect(self._cancel_pending_insertion)
        insertion_layout.addWidget(self.insertion_gap)
        self.insertion_hint = QLabel("Enter — добавить · Esc — отменить")
        self.insertion_hint.setObjectName("insertionHint")
        insertion_layout.addWidget(self.insertion_hint)
        self.insertion_editor.setVisible(False)
        view_heading.addWidget(self.insertion_editor)
        self.deletion_editor = QFrame()
        self.deletion_editor.setObjectName("deletionEditor")
        deletion_layout = QHBoxLayout(self.deletion_editor)
        deletion_layout.setContentsMargins(8, 4, 8, 4)
        deletion_layout.setSpacing(6)
        self.deletion_hint = QLabel()
        self.deletion_hint.setObjectName("deletionHint")
        deletion_layout.addWidget(self.deletion_hint)
        self.confirm_deletion_button = QPushButton()
        self.confirm_deletion_button.setObjectName("confirmDeletionButton")
        self.confirm_deletion_button.clicked.connect(self._confirm_deletion)
        deletion_layout.addWidget(self.confirm_deletion_button)
        self.deletion_editor.setVisible(False)
        view_heading.addWidget(self.deletion_editor)
        self.section_editor = QFrame()
        self.section_editor.setObjectName("sectionEditor")
        section_layout = QHBoxLayout(self.section_editor)
        section_layout.setContentsMargins(8, 4, 8, 4)
        section_layout.setSpacing(6)
        self.section_hint = QLabel()
        self.section_hint.setObjectName("sectionEditHint")
        section_layout.addWidget(self.section_hint)
        self.confirm_section_button = QPushButton("Изменить…")
        self.confirm_section_button.setObjectName("confirmSectionButton")
        self.confirm_section_button.clicked.connect(self._confirm_section_change)
        section_layout.addWidget(self.confirm_section_button)
        self.section_editor.setVisible(False)
        view_heading.addWidget(self.section_editor)
        self.distance_editor = QFrame()
        self.distance_editor.setObjectName("distanceEditor")
        distance_layout = QHBoxLayout(self.distance_editor)
        distance_layout.setContentsMargins(8, 4, 8, 4)
        distance_layout.setSpacing(6)
        distance_layout.addWidget(QLabel("Новое расстояние:"))
        self.distance_value = InsertionGapSpinBox()
        self.distance_value.setRange(-1_000_000, 1_000_000)
        self.distance_value.setDecimals(2)
        self.distance_value.setSuffix(" мм")
        self.distance_value.setMinimumWidth(120)
        self.distance_value.confirmed.connect(self._confirm_distance_edit)
        self.distance_value.cancelled.connect(self._cancel_pending_distance_edit)
        distance_layout.addWidget(self.distance_value)
        self.distance_hint = QLabel("Enter — применить · Esc — отменить")
        self.distance_hint.setObjectName("distanceHint")
        distance_layout.addWidget(self.distance_hint)
        self.distance_editor.setVisible(False)
        view_heading.addWidget(self.distance_editor)
        view_heading.addStretch()
        view_heading.addWidget(self.show_length_gaps)
        view_heading.addWidget(self.show_width_gaps)
        self.camera_combo.setObjectName("cameraCombo")
        self.camera_combo.currentIndexChanged.connect(self._set_camera)
        view_heading.addWidget(self.camera_combo)
        fit_button = QPushButton("Вписать")
        fit_button.setObjectName("cameraButton")
        fit_button.clicked.connect(self.view.camera_fit)
        view_heading.addWidget(fit_button)
        viewport_layout.addLayout(view_heading)
        viewport_layout.addWidget(self.view)
        viewport_layout.addWidget(self.scene_info)
        splitter.addWidget(viewport)
        splitter.setSizes([420, 980])
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self._rebuild_layer_cards()
        self.length_panel.changed.connect(self._schedule_recalculation)
        self.width_panel.changed.connect(self._schedule_recalculation)
        self.top_length_panel.changed.connect(self._schedule_recalculation)
        self.layer_buttons.buttonClicked.connect(self._layer_changed)
        self.rounding_buttons.buttonClicked.connect(self._rounding_changed)
        self.show_length_gaps.toggled.connect(self._refresh_dimension_annotations)
        self.show_width_gaps.toggled.connect(self._refresh_dimension_annotations)
        self.setStyleSheet(self._stylesheet())
        self.add_beam_button.installEventFilter(self)
        self.delete_beam_button.installEventFilter(self)
        self.edit_distance_button.installEventFilter(self)
        self.change_section_button.installEventFilter(self)
        self.view.installEventFilter(self)
        # The editor of QDoubleSpinBox is a child QLineEdit and receives key
        # events before the spin box itself on some Qt styles.  Watch both so
        # Enter always commits a chosen insertion slot.
        self.insertion_gap.installEventFilter(self)
        self.insertion_gap.lineEdit().installEventFilter(self)

    def _header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("appHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)
        brand = QVBoxLayout()
        eyebrow = QLabel(f"PALLETLAB / ВЕРСИЯ {__version__}")
        eyebrow.setObjectName("eyebrow")
        brand.addWidget(eyebrow)
        title = QLabel("Расчёт и 3D-визуализация поддона")
        title.setObjectName("appTitle")
        brand.addWidget(title)
        layout.addLayout(brand)
        layout.addStretch()
        self.open_project_button = QPushButton("Открыть")
        self.open_project_button.setObjectName("openProjectButton")
        self.open_project_button.clicked.connect(self.open_project)
        layout.addWidget(self.open_project_button)
        self.save_project_button = QPushButton("Сохранить")
        self.save_project_button.setObjectName("saveProjectButton")
        self.save_project_button.clicked.connect(self.save_project)
        layout.addWidget(self.save_project_button)
        self.build_from_model_button = QPushButton("Построить по модели")
        self.build_from_model_button.setObjectName("buildFromModelButton")
        self.build_from_model_button.setToolTip("Загрузить STEP-модель и выбрать нижнюю грань одной опоры.")
        self.build_from_model_button.clicked.connect(self.build_from_model)
        layout.addWidget(self.build_from_model_button)
        self.export_kompas_button = QPushButton("Экспорт в КОМПАС")
        self.export_kompas_button.setObjectName("exportKompasButton")
        self.export_kompas_button.clicked.connect(self.export_to_kompas)
        layout.addWidget(self.export_kompas_button)
        self.export_solidworks_button = QPushButton("Экспорт в SolidWorks")
        self.export_solidworks_button.setObjectName("exportSolidWorksButton")
        self.export_solidworks_button.clicked.connect(self.export_to_solidworks)
        layout.addWidget(self.export_solidworks_button)
        return header

    @staticmethod
    def _stylesheet() -> str:
        return """
            QWidget#appRoot { background: #f6f3ed; color: #263238; font-family: 'Segoe UI'; font-size: 13px; }
            QFrame#appHeader, QFrame#resultsFrame, QFrame#layerCard, QFrame#actionPanel, QGroupBox#directionCard {
                background: #fffdf9; border: 1px solid #e5dfd4; border-radius: 12px;
            }
            QLabel#eyebrow { color: #9a6840; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
            QLabel#appTitle { color: #203b40; font-size: 22px; font-weight: 650; }
            QPushButton#exportSolidWorksButton { background: #255e64; border-color: #255e64; color: #fff; font-weight: 650; padding: 8px 13px; }
            QPushButton#exportSolidWorksButton:hover { background: #1f4f54; border-color: #1f4f54; }
            QPushButton#exportKompasButton { background: #795548; border-color: #795548; color: #fff; font-weight: 650; padding: 8px 13px; }
            QPushButton#exportKompasButton:hover { background: #5d4037; border-color: #5d4037; }
            QPushButton#openProjectButton, QPushButton#saveProjectButton { background: #fffdf9; border-color: #bcb5a7; padding: 8px 11px; }
            QPushButton#openProjectButton:hover, QPushButton#saveProjectButton:hover { background: #f0ece3; }
            QLabel#paneTitle { color: #203b40; font-size: 17px; font-weight: 650; }
            QLabel#paneHint, QLabel#sectionHint { color: #6b706c; font-size: 12px; }
            QGroupBox#directionCard { margin-top: 12px; padding-top: 12px; font-weight: 700; color: #203b40; }
            QGroupBox#directionCard::title { subcontrol-origin: margin; left: 14px; padding: 0 5px; }
            QLabel { color: #384047; }
            QLineEdit, QDoubleSpinBox, QComboBox {
                background: #ffffff; border: 1px solid #d8d3c8; border-radius: 7px; min-height: 30px; padding: 0 8px;
            }
            QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 2px solid #4b7a76; }
            QDoubleSpinBox:disabled { background: #f1eee8; color: #81837e; }
            QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right; width: 28px; background: #f3f0e9; border-left: 1px solid #d8d3c8; border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
            QComboBox::drop-down:hover { background: #e9e5dc; }
            QComboBox::down-arrow { image: url(:/icons/chevron-down.svg); width: 12px; height: 12px; }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 22px; background: #f3f0e9; border-left: 1px solid #d8d3c8; }
            QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; border-top-right-radius: 6px; border-bottom: 1px solid #d8d3c8; }
            QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; border-bottom-right-radius: 6px; }
            QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: #e9e5dc; }
            QDoubleSpinBox::up-arrow { image: url(:/icons/chevron-up.svg); width: 12px; height: 12px; }
            QDoubleSpinBox::down-arrow { image: url(:/icons/chevron-down.svg); width: 12px; height: 12px; }
            QCheckBox { spacing: 8px; color: #33464a; }
            QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #bdb7ac; border-radius: 5px; background: #fff; }
            QCheckBox::indicator:hover { border-color: #4b7a76; }
            QCheckBox::indicator:checked { background: #255e64; border-color: #255e64; image: url(:/icons/check.svg); }
            QLabel#roundingTitle { color: #203b40; font-weight: 650; }
            QRadioButton { spacing: 8px; color: #33464a; }
            QRadioButton::indicator { width: 18px; height: 18px; border: none; image: none; }
            QRadioButton::indicator:hover { border-color: #4b7a76; }
            QRadioButton::indicator:unchecked { image: url(:/icons/radio-unchecked.svg); }
            QRadioButton::indicator:checked { image: url(:/icons/radio-checked.svg); }
            QPushButton { background: #fffdf9; border: 1px solid #d8d3c8; border-radius: 7px; padding: 8px 11px; color: #33464a; }
            QPushButton:hover { background: #f0ece3; border-color: #bcb5a7; }
            QPushButton:checked { background: #dfece9; border: 2px solid #4b7a76; color: #1f5c58; font-weight: 650; }
            QPushButton#addBeamButton { border-color: #4b7a76; color: #1f5c58; font-weight: 650; }
            QPushButton#addBeamButton:hover { background: #e7f0ed; }
            QPushButton#addBeamButton:checked { background: #255e64; border-color: #255e64; color: #fff; }
            QPushButton#deleteBeamButton { border-color: #b84a43; color: #9a322c; font-weight: 650; }
            QPushButton#deleteBeamButton:hover { background: #f9e5e2; }
            QPushButton#deleteBeamButton:checked { background: #a53b35; border-color: #a53b35; color: #fff; }
            QPushButton#editDistanceButton { border-color: #b47a22; color: #8a5b14; font-weight: 650; }
            QPushButton#editDistanceButton:hover { background: #fbf0da; }
            QPushButton#editDistanceButton:checked { background: #9a681b; border-color: #9a681b; color: #fff; }
            QPushButton#changeSectionButton { border-color: #287b9f; color: #1e617d; font-weight: 650; }
            QPushButton#changeSectionButton:hover { background: #e2f1f6; }
            QPushButton#changeSectionButton:checked { background: #246f91; border-color: #246f91; color: #fff; }
            QPushButton#buildFromModelButton { background: #255e64; border-color: #255e64; color: #fff; font-weight: 650; }
            QPushButton#buildFromModelButton:hover { background: #1f4f54; border-color: #1f4f54; }
            QPushButton#rebuildFromModelButton { border-color: #8aa7a3; color: #285e59; font-weight: 650; }
            QPushButton#rebuildFromModelButton:hover { background: #e7f0ed; }
            QPushButton#toggleModelButton { border-color: #4b7a76; color: #1f5c58; font-weight: 650; }
            QFrame#insertionEditor { background: #e7f0ed; border: 1px solid #b9d4cd; border-radius: 7px; }
            QLabel#insertionHint { color: #55706a; font-size: 11px; }
            QFrame#deletionEditor { background: #fbe9e7; border: 1px solid #edb7b1; border-radius: 7px; }
            QLabel#deletionHint { color: #81332e; font-size: 11px; }
            QPushButton#confirmDeletionButton { background: #b83e37; border-color: #b83e37; color: #fff; font-weight: 650; padding: 6px 9px; }
            QPushButton#confirmDeletionButton:disabled { background: #e3b9b5; border-color: #e3b9b5; color: #fff; }
            QFrame#sectionEditor { background: #e2f1f6; border: 1px solid #afd3df; border-radius: 7px; }
            QLabel#sectionEditHint { color: #215b72; font-size: 11px; }
            QPushButton#confirmSectionButton { background: #287b9f; border-color: #287b9f; color: #fff; font-weight: 650; padding: 6px 9px; }
            QPushButton#confirmSectionButton:disabled { background: #a8ccd9; border-color: #a8ccd9; color: #fff; }
            QFrame#distanceEditor { background: #fbf0da; border: 1px solid #e7c782; border-radius: 7px; }
            QLabel#distanceHint { color: #7d5a20; font-size: 11px; }
            QComboBox#cameraCombo { min-width: 115px; }
            QPushButton#cameraButton { padding: 6px 12px; font-size: 12px; }
            QTextBrowser#resultCard { background: #f9f7f1; border: 1px solid #ece6dc; border-radius: 9px; padding: 4px 10px; }
            QLabel#resultSummary { color: #203b40; font-size: 18px; font-weight: 650; }
            QLabel#resultNote { color: #55706a; font-size: 12px; }
            QLabel#sceneInfo { background: #fffdf9; border: 1px solid #e5dfd4; border-radius: 8px; color: #21474d; font-size: 12px; font-weight: 600; padding: 8px 12px; }
            QScrollArea#parametersScroll { border: none; background: transparent; }
            QScrollBar:vertical { background: #efede7; width: 8px; margin: 8px 3px 8px 2px; border-radius: 4px; }
            QScrollBar::handle:vertical { background: #a8a59c; border-radius: 4px; min-height: 32px; }
            QScrollBar::handle:vertical:hover { background: #777a73; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
            QSplitter::handle { background: #e5dfd4; width: 1px; }
        """

    def _set_stale(self, stale: bool) -> None:
        if stale:
            self.statusBar().showMessage("Параметры изменены — модель требует пересчёта.")
        else:
            self.statusBar().showMessage("Расчёт актуален.")

    @staticmethod
    def _layer_description(axis: PalletAxis) -> str:
        return (
            "Центры брусьев задаются по оси X. Брусья слоя идут поперёк ширины."
            if axis == "length" else
            "Центры брусьев задаются по оси Y. Брусья слоя идут вдоль длины."
        )

    def _rebuild_layer_cards(self) -> None:
        """Render the ordered layer stack while retaining each panel's values."""
        while self.layer_stack_layout.count():
            item = self.layer_stack_layout.takeAt(0)
            card = item.widget()
            if card is not None:
                # The input panel is reused in the freshly ordered card.  Qt
                # destroys child widgets with their old parent unless it is
                # explicitly detached first.
                panel = card.findChild(DirectionInputPanel)
                if panel is not None:
                    panel.setParent(None)
                card.hide()
                card.setParent(None)
                self._retired_layer_cards.append(card)
        for position, layer_id in enumerate(self._layer_order):
            axis = self._layer_axes[layer_id]
            panel = self._layer_panels[layer_id]
            panel.setTitle(f"{position + 1:02d}  Слой · {'длина' if axis == 'length' else 'ширина'}")
            card = QFrame()
            card.setObjectName("layerCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(8, 6, 8, 8)
            header = QHBoxLayout()
            direction = "по длине" if axis == "length" else "по ширине"
            header.addWidget(QLabel(f"Слой {position + 1} · {direction}"), 1)
            up = QPushButton("↑")
            up.setToolTip("Поднять слой")
            up.setEnabled(position > 0)
            up.clicked.connect(lambda _checked=False, identifier=layer_id: self._move_layer(identifier, -1))
            header.addWidget(up)
            down = QPushButton("↓")
            down.setToolTip("Опустить слой")
            down.setEnabled(position < len(self._layer_order) - 1)
            down.clicked.connect(lambda _checked=False, identifier=layer_id: self._move_layer(identifier, 1))
            header.addWidget(down)
            remove = QPushButton("×")
            remove.setToolTip("Удалить слой")
            remove.setEnabled(len(self._layer_order) > 2)
            remove.clicked.connect(lambda _checked=False, identifier=layer_id: self._remove_layer(identifier))
            header.addWidget(remove)
            layout.addLayout(header)
            layout.addWidget(panel)
            self.layer_stack_layout.addWidget(card)
        add = QPushButton("＋ Добавить слой")
        add.setObjectName("addLayerButton")
        add.clicked.connect(self._add_layer)
        self.layer_stack_layout.addWidget(add)
        self._sync_layer_mode()

    def _add_layer(self) -> None:
        MainWindow._begin_history_transaction(self)
        self._layer_rebuild_timer.stop()
        axis: PalletAxis = "length" if self._layer_axes[self._layer_order[-1]] == "width" else "width"
        number = 1
        while f"layer-{number}" in self._layer_panels:
            number += 1
        layer_id = f"layer-{number}"
        source_id = next((identifier for identifier in self._layer_order if self._layer_axes[identifier] == axis), self._layer_order[-1])
        source = self._layer_panels[source_id]
        panel = DirectionInputPanel("", self._layer_description(axis), "", "100", "100")
        try:
            panel.apply_position_data(source.values(self.rounding_buttons.checkedId() != 0, self.rounding_buttons.checkedId() or 5), notify=False)
            panel.section.setCurrentText(source.section.currentText())
        except CalculationError:
            pass
        panel.changed.connect(self._schedule_recalculation)
        self._layer_order.append(layer_id)
        self._layer_axes[layer_id] = axis
        self._layer_panels[layer_id] = panel
        self._rebuild_layer_cards()
        self._calculate_layer_stack()

    def _remove_layer(self, layer_id: str) -> None:
        if len(self._layer_order) <= 2:
            return
        MainWindow._begin_history_transaction(self)
        self._layer_rebuild_timer.stop()
        remaining = [identifier for identifier in self._layer_order if identifier != layer_id]
        if not any(self._layer_axes[identifier] == "length" for identifier in remaining) or not any(
            self._layer_axes[identifier] == "width" for identifier in remaining
        ):
            MainWindow._discard_history_transaction(self)
            self.statusBar().showMessage("В поддоне должен остаться хотя бы один слой по каждой оси.")
            return
        panel = self._layer_panels.pop(layer_id)
        panel.setParent(None)
        panel.hide()
        self._layer_axes.pop(layer_id)
        self._layer_order = remaining
        self.state.layer_sections = {
            key: section for key, section in self.state.layer_sections.items() if key[0] != layer_id
        }
        self._rebuild_layer_cards()
        self._calculate_layer_stack()

    def _move_layer(self, layer_id: str, shift: int) -> None:
        current = self._layer_order.index(layer_id)
        target = current + shift
        if not 0 <= target < len(self._layer_order):
            return
        MainWindow._begin_history_transaction(self)
        self._layer_rebuild_timer.stop()
        self._layer_order[current], self._layer_order[target] = self._layer_order[target], self._layer_order[current]
        self._rebuild_layer_cards()
        self._calculate_layer_stack()

    def _read_layer_inputs(self) -> list[LayerInput]:
        rounding_step = self.rounding_buttons.checkedId()
        return [
            LayerInput(layer_id, self._layer_axes[layer_id], self._layer_panels[layer_id].values(
                rounding_step != 0, rounding_step or 5,
            ))
            for layer_id in self._layer_order
        ]

    @staticmethod
    def _panel_for_layer(owner, layer_id: str) -> DirectionInputPanel:
        """Resolve a layer editor and retain compatibility with the two-panel UI."""
        panel = getattr(owner, "_layer_panels", {}).get(layer_id)
        if panel is not None:
            return panel
        return owner.length_panel if layer_id == "length" else owner.width_panel

    @staticmethod
    def _apply_interactive_position_update(owner, panel: DirectionInputPanel, data) -> None:
        """Synchronise form fields without queuing a second pallet rebuild."""
        timer = getattr(owner, "_layer_rebuild_timer", None)
        if timer is not None:
            timer.stop()
        try:
            panel.apply_position_data(data, notify=False)
        except TypeError:
            # Lightweight non-Qt test doubles intentionally expose the old
            # single-argument API.
            panel.apply_position_data(data)

    def _calculate_layer_stack(self, *, show_error: bool = False):
        self._layer_rebuild_timer.stop()
        try:
            layers = self._read_layer_inputs()
            layers = self._synchronize_layer_envelopes(layers)
        except CalculationError as exc:
            self._set_stale(True)
            self._handle_calculation_error(exc, show_error)
            return None
        finally:
            # A later recalculation caused by reordering, loading or a tool
            # action must not reuse an old field-edit source.
            self._layer_envelope_source = None
        result = self.controller.calculate_layers(layers, show_error=show_error)
        if result is not None:
            MainWindow._commit_history_transaction(self)
            self._restore_active_tool_after_rebuild()
        return result

    def _synchronize_layer_envelopes(self, layers: list[LayerInput]) -> list[LayerInput]:
        """Keep same-axis layers on the envelope changed in the editor.

        Beam grids in parallel layers may differ, but their common pallet
        dimension may not.  When a user edits one grid, retain every other
        grid and adjust only its dependent end margin by the envelope delta.
        """
        source_id = self._layer_envelope_source
        source = next((layer for layer in layers if layer.layer_id == source_id), None)
        if source is None:
            return layers
        target_size = calculate_direction(source.direction).raw_pallet_size
        synchronized: list[LayerInput] = []
        for layer in layers:
            if layer.axis != source.axis or layer.layer_id == source.layer_id:
                synchronized.append(layer)
                continue
            current_size = calculate_direction(layer.direction).raw_pallet_size
            direction = replace(layer.direction, margin_end=layer.direction.margin_end + target_size - current_size)
            # Validate before applying it to the visible form; otherwise a
            # failed edit could leave the UI and project state out of sync.
            calculate_direction(direction)
            panel = self._layer_panels.get(layer.layer_id)
            if panel is not None:
                MainWindow._apply_interactive_position_update(self, panel, direction)
            synchronized.append(LayerInput(layer.layer_id, layer.axis, direction))
        return synchronized

    def _restore_active_tool_after_rebuild(self) -> None:
        """Re-register viewport affordances cleared with the old pallet actors."""
        if self.add_beam_button.isChecked():
            self._toggle_insertion_mode(True)
        elif self.delete_beam_button.isChecked():
            self._toggle_deletion_mode(True)
        elif self.edit_distance_button.isChecked():
            self._toggle_distance_editing(True)
        elif self.change_section_button.isChecked():
            self._toggle_section_editing(True)

    @staticmethod
    def _begin_history_transaction(owner) -> None:
        """Remember the state before one user-confirmed edit."""
        if not hasattr(owner, "_history") or getattr(owner, "_history_restoring", False):
            return
        if getattr(owner, "_pending_history_snapshot", None) is not None:
            return
        owner._pending_history_snapshot = owner._history.snapshot(owner.state)

    @staticmethod
    def _commit_history_transaction(owner) -> None:
        if not hasattr(owner, "_history") or getattr(owner, "_history_restoring", False):
            return
        snapshot = getattr(owner, "_pending_history_snapshot", None)
        if snapshot is None:
            return
        owner._history.record(snapshot)
        owner._pending_history_snapshot = None

    @staticmethod
    def _discard_history_transaction(owner) -> None:
        if hasattr(owner, "_pending_history_snapshot"):
            owner._pending_history_snapshot = None

    def undo(self) -> None:
        self._restore_history(self._history.undo, "Отменено последнее изменение.")

    def redo(self) -> None:
        self._restore_history(self._history.redo, "Повторено отменённое изменение.")

    def _restore_history(self, operation, message: str) -> None:
        """Restore an edit snapshot and rebuild the palette from its data."""
        self._layer_rebuild_timer.stop()
        self._model_rebuild_timer.stop()
        MainWindow._discard_history_transaction(self)
        if not operation(self.state):
            self.statusBar().showMessage("Нет изменений для отмены." if message.startswith("Отмен") else "Нет изменений для повтора.")
            return
        self._history_restoring = True
        try:
            for button in (self.add_beam_button, self.delete_beam_button, self.edit_distance_button, self.change_section_button):
                button.setChecked(False)
            self.controller.deactivate_tool()
            self.controller.cancel_insertion()
            self.controller.cancel_distance_edit()
            self._clear_model_supports()
            self._set_model_controls_visible(False)
            self.length_panel.set_model_driven_mode(None)
            self.width_panel.set_model_driven_mode(None)
            self._apply_loaded_project(self.state)
            result = self.controller.recalculate_from_state(show_error=False)
        finally:
            self._history_restoring = False
        if result is None:
            self.statusBar().showMessage("Не удалось восстановить состояние поддона.")
            return
        self.statusBar().showMessage(message)

    def _sync_layer_mode(self) -> None:
        multilayer = len(self._layer_order) > 2
        self.layer_card.setVisible(not multilayer)

    def build_from_model(self) -> None:
        """Start the STEP-driven workflow and ask for one horizontal support face."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите 3D-модель установки", "", "STEP-модели (*.step *.stp)"
        )
        if not path:
            return
        self.add_beam_button.setChecked(False)
        self.delete_beam_button.setChecked(False)
        self.edit_distance_button.setChecked(False)
        self.change_section_button.setChecked(False)
        self._model_rebuild_timer.stop()
        self.length_panel.set_model_driven_mode(None)
        self.width_panel.set_model_driven_mode(None)
        self._clear_model_supports()
        self._imported_step_model = None
        self._set_model_controls_visible(False)
        self.state.beam_sections.clear()
        self.state.result = None
        self.view.clear_workspace()
        self.scene_info.setText("Загрузка 3D-модели…")
        self.toggle_model_button.setEnabled(False)
        self.build_from_model_button.setEnabled(False)
        self.rebuild_from_model_button.setEnabled(False)
        self.centralWidget().setEnabled(False)
        self._step_import_progress = QProgressDialog("Подготовка загрузки…", None, 0, 100, self)
        self._step_import_progress.setWindowTitle("Загрузка 3D-модели")
        self._step_import_progress.setWindowModality(Qt.ApplicationModal)
        self._step_import_progress.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self._step_import_progress.setCancelButton(None)
        self._step_import_progress.setAutoClose(False)
        self._step_import_progress.setMinimumDuration(0)
        self._step_import_progress.show()
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_step_import_output)
        process.finished.connect(self._step_import_process_finished)
        environment = QProcessEnvironment.systemEnvironment()
        if not getattr(sys, "frozen", False):
            source_root = str(Path(__file__).resolve().parents[2])
            environment.insert("PYTHONPATH", source_root + os.pathsep + environment.value("PYTHONPATH"))
        process.setProcessEnvironment(environment)
        self._step_import_process = process
        self._step_import_path = path
        self._step_import_output = ""
        self._step_import_error = None
        self.statusBar().showMessage("Загрузка STEP-модели…")
        arguments = ["--step-import", path] if getattr(sys, "frozen", False) else ["-m", "palletlab.importers.step_import_worker", path]
        process.start(sys.executable, arguments)

    def _update_step_import_progress(self, value: int, label: str) -> None:
        if self._step_import_progress is not None:
            self._step_import_progress.setValue(value)
            self._step_import_progress.setLabelText(label)

    def _step_import_loaded(self, model: ImportedStepModel) -> None:
        self._imported_step_model = model
        # A STEP import always uses support coordinates derived from the model;
        # hide the manual gabarit-to-support fields before the user selects the
        # first support face, not only after the pallet has been built.
        self.length_panel.set_model_driven_mode(None, hide_model_offsets=True)
        self.width_panel.set_model_driven_mode(None, hide_model_offsets=True)
        self._set_model_controls_visible(True)
        self.rebuild_from_model_button.setEnabled(True)
        self.toggle_model_button.setEnabled(True)
        self.toggle_model_button.setText("Скрыть 3D модель")
        self.view.show_step_model(model.mesh, model.edges, model.faces, self._support_face_selected)
        self.statusBar().showMessage("Выберите левой кнопкой плоскую нижнюю грань любой опоры установки.")

    def _show_support_selection_prompt(self) -> None:
        """Give the user a clear next action after a STEP model becomes selectable."""
        QMessageBox.information(
            self,
            "Выберите опору",
            "Нажмите левой кнопкой мыши на плоскую нижнюю грань любой опоры установки.\n\n"
            "PalletLab найдёт остальные опоры в той же плоскости и построит поддон.",
        )

    def rebuild_from_model(self) -> None:
        """Discard only the pallet and repeat support selection for the loaded STEP model."""
        model = self._imported_step_model
        if model is None:
            return
        self.add_beam_button.setChecked(False)
        self.delete_beam_button.setChecked(False)
        self.edit_distance_button.setChecked(False)
        self.change_section_button.setChecked(False)
        self._model_rebuild_timer.stop()
        self.controller.deactivate_tool()
        self.state.result = None
        self.state.beam_sections.clear()
        self._clear_model_supports()
        self.view.prepare_step_model_rebuild(self._support_face_selected)
        self.toggle_model_button.setEnabled(True)
        self.toggle_model_button.setText("Скрыть 3D модель")
        self.scene_info.setText("Выберите нижнюю грань опоры, чтобы перестроить поддон.")
        self.statusBar().showMessage("Выберите левой кнопкой плоскую нижнюю грань любой опоры установки.")
        self._show_support_selection_prompt()

    def _step_import_failed(self, message: str) -> None:
        self.length_panel.set_model_driven_mode(None)
        self.width_panel.set_model_driven_mode(None)
        self._set_model_controls_visible(False)
        QMessageBox.warning(self, "Загрузка 3D-модели", message)
        self.scene_info.setText("3D-модель не загружена.")
        self.statusBar().showMessage("Не удалось загрузить 3D-модель.")

    def _read_step_import_output(self) -> None:
        process = self._step_import_process
        if process is None:
            return
        self._step_import_output += bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        lines = self._step_import_output.split("\n")
        self._step_import_output = lines.pop()
        for line in lines:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("kind") == "progress":
                self._update_step_import_progress(int(message["value"]), str(message["label"]))
            elif message.get("kind") == "error":
                self._step_import_error = str(message.get("message", "Неизвестная ошибка импорта."))

    def _step_import_process_finished(self, exit_code: int, exit_status) -> None:
        process = self._step_import_process
        show_selection_prompt = False
        if process is not None:
            self._read_step_import_output()
        if exit_code == 0 and self._step_import_error is None and self._step_import_path is not None:
            try:
                from palletlab.importers.step_model import load_cached_step_model
                model = load_cached_step_model(self._step_import_path)
                if model is None:
                    raise RuntimeError("Кэш модели не был создан.")
                self._step_import_loaded(model)
                show_selection_prompt = True
            except Exception as exc:
                self._step_import_failed(str(exc))
        else:
            detail = self._step_import_error
            if not detail and process is not None:
                detail = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            self._step_import_failed(detail or "Процесс загрузки STEP-модели завершился с ошибкой.")
        self._step_import_finished()
        if show_selection_prompt:
            self._show_support_selection_prompt()

    def _step_import_finished(self) -> None:
        if self._step_import_progress is not None:
            self._step_import_progress.close()
            self._step_import_progress.deleteLater()
            self._step_import_progress = None
        self.build_from_model_button.setEnabled(True)
        self.centralWidget().setEnabled(True)
        if self._step_import_process is not None:
            self._step_import_process.deleteLater()
        self._step_import_process = None
        self._step_import_path = None

    def _support_face_selected(self, face_index: int) -> None:
        model = self._imported_step_model
        if model is None:
            return
        try:
            from palletlab.importers.step_model import coplanar_supports
            supports = coplanar_supports(model, face_index)
        except ValueError as exc:
            QMessageBox.information(self, "Выбор опоры", str(exc))
            self.statusBar().showMessage("Выберите плоскую горизонтальную нижнюю грань опоры.")
            return
        self._clear_model_supports()
        self._model_supports = supports
        self._model_reference_support_index = face_index
        self._build_selected_model_pallet()

    def _build_selected_model_pallet(self) -> None:
        """Recalculate a STEP-driven pallet from the detected support faces."""
        model = self._imported_step_model
        if model is None or not self._model_supports or self._model_reference_support_index is None:
            return
        try:
            from palletlab.importers.step_model import pallet_inputs_from_supports
            rounding_step = self.rounding_buttons.checkedId()
            length_input, width_input, placed_mesh, placed_edges = pallet_inputs_from_supports(
                model,
                self._model_supports,
                length_beam_height=self.length_panel.height.value(),
                length_beam_width=self.length_panel.width.value(),
                width_beam_height=self.width_panel.height.value(),
                width_beam_width=self.width_panel.width.value(),
                length_margin_start=self.length_panel.margin_start.value(),
                length_margin_end=self.length_panel.margin_end.value(),
                width_margin_start=self.width_panel.margin_start.value(),
                width_margin_end=self.width_panel.margin_end.value(),
                round_pallet_size=rounding_step != 0,
                rounding_step=rounding_step or 5,
                reference_support_index=self._model_reference_support_index,
            )
        except ValueError as exc:
            QMessageBox.information(self, "Построение по модели", str(exc))
            self.statusBar().showMessage("Выберите корректные грани габарита и опоры.")
            return
        self.view.stage_step_model(placed_mesh, placed_edges)
        result = self.controller.calculate(length_input, width_input, self.upper_layer())
        if result is None:
            # Keep the staged STEP actor and its picking callback alive: a
            # non-support face can legitimately produce overlapping beams.
            self.view.show_staged_step_model()
            self.statusBar().showMessage("Поддон не построен. Выберите другую нижнюю грань опоры.")
            return
        # These values describe the just-detected supports.  Updating the
        # display must not briefly schedule a manual rebuild or unhide the
        # model-only form rows.
        self.length_panel.apply_position_data(length_input, notify=False)
        self.width_panel.apply_position_data(width_input, notify=False)
        self.length_panel.set_model_driven_mode(length_input)
        self.width_panel.set_model_driven_mode(width_input)
        # ``apply_position_data`` intentionally notifies regular manual
        # edits.  This calculation is already current, so prevent it from
        # scheduling a second heavy VTK rebuild a moment later.
        self.controller.stop_scheduled_recalculation()
        self.view.commit_step_support_selection(
            {face.index for face in self._model_supports}, self._model_reference_support_index
        )
        self._update_scene_info(result)
        self.statusBar().showMessage(
            f"Найдено опорных граней: {len(self._model_supports)}. Поддон построен под установкой."
        )

    def _clear_model_supports(self) -> None:
        self._model_supports = ()
        self._model_reference_support_index = None

    def _toggle_model_visibility(self) -> None:
        visible = self.view.toggle_step_model_visibility()
        self.toggle_model_button.setText("Скрыть 3D модель" if visible else "Показать 3D модель")

    def _set_model_controls_visible(self, visible: bool) -> None:
        """Keep model-only controls out of the manual pallet workflow."""
        self.rebuild_from_model_button.setVisible(visible)
        self.toggle_model_button.setVisible(visible)
        if not visible:
            self.rebuild_from_model_button.setEnabled(False)
            self.toggle_model_button.setEnabled(False)
            self.toggle_model_button.setText("Скрыть 3D модель")

    def export_to_solidworks(self) -> None:
        """Rebuild the visible pallet and export its exact current geometry."""
        result = self.calculate(show_error=True)
        if result is None:
            return
        parent = QFileDialog.getExistingDirectory(self, "Выберите папку для экспорта SolidWorks")
        if not parent:
            return
        self.export_solidworks_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            templates = self._solidworks_templates()
            material_library, material_name = self._solidworks_material()
            if not material_library or not material_name:
                selected_material = self._select_solidworks_material()
                if selected_material is None:
                    self.statusBar().showMessage("Экспорт в SolidWorks отменён: не выбрана библиотека материалов.")
                    return
                material_library, material_name = selected_material
                self._save_solidworks_material(material_library, material_name)
            try:
                output = export_pallet(result, parent, templates, self.state.material_id, material_library, material_name)
            except SolidWorksTemplateError as error:
                templates = self._select_solidworks_templates(error.missing, templates)
                if templates is None:
                    self.statusBar().showMessage("Экспорт в SolidWorks отменён: не выбран шаблон.")
                    return
                self._save_solidworks_templates(templates)
                output = export_pallet(result, parent, templates, self.state.material_id, material_library, material_name)
        except SolidWorksExportError as exc:
            QMessageBox.critical(self, "Экспорт в SolidWorks", str(exc))
            self.statusBar().showMessage("Экспорт в SolidWorks не выполнен.")
        else:
            QApplication.restoreOverrideCursor()
            QMessageBox.information(self, "Экспорт в SolidWorks", f"Детали и сборка сохранены в папке:\n{output}")
            self.statusBar().showMessage(f"Экспорт в SolidWorks завершён: {output}")
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            self.export_solidworks_button.setEnabled(True)

    @staticmethod
    def _solidworks_templates() -> tuple[str | None, str | None]:
        settings = QSettings("PalletLab", "PalletLab")
        part = settings.value("solidworks/part_template", "", type=str) or None
        assembly = settings.value("solidworks/assembly_template", "", type=str) or None
        return part, assembly

    @staticmethod
    def _save_solidworks_templates(templates: tuple[str | None, str | None]) -> None:
        settings = QSettings("PalletLab", "PalletLab")
        settings.setValue("solidworks/part_template", templates[0] or "")
        settings.setValue("solidworks/assembly_template", templates[1] or "")

    def _solidworks_material(self) -> tuple[str | None, str | None]:
        settings = QSettings("PalletLab", "PalletLab")
        library = settings.value("solidworks/material_library", "", type=str) or None
        material = settings.value(f"solidworks/materials/{self.state.material_id}", "", type=str) or None
        return library, material

    def _save_solidworks_material(self, library: str, material: str) -> None:
        settings = QSettings("PalletLab", "PalletLab")
        settings.setValue("solidworks/material_library", library)
        settings.setValue(f"solidworks/materials/{self.state.material_id}", material)

    def _select_solidworks_material(self) -> tuple[str, str] | None:
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Warning)
        prompt.setWindowTitle("Нужна библиотека материалов SolidWorks")
        prompt.setText("Выберите библиотеку материалов SolidWorks (.sldmat).")
        prompt.setInformativeText(
            "PalletLab не изменяет настройки SolidWorks. Папка библиотеки должна быть уже добавлена в «Базы данных материалов».\n\n"
            "Стандартный путь: C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\lang\\english\\sldmaterials\n"
            "Для русской локали: C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\lang\\russian\\sldmaterials"
        )
        choose_button = prompt.addButton("Выбрать библиотеку", QMessageBox.AcceptRole)
        prompt.addButton("Отмена", QMessageBox.RejectRole)
        prompt.exec_()
        if prompt.clickedButton() is not choose_button:
            return None
        library, _ = QFileDialog.getOpenFileName(self, "Выберите библиотеку материалов SolidWorks", "", "Библиотеки материалов SolidWorks (*.sldmat)")
        if not library:
            return None
        try:
            names = available_materials(library)
        except SolidWorksMaterialLibraryError as exc:
            QMessageBox.critical(self, "Библиотека материалов SolidWorks", str(exc))
            return None
        current = get_material(self.state.material_id)
        initial = names.index(current.solidworks_name) if current.solidworks_name in names else 0
        material, accepted = QInputDialog.getItem(self, "Материал SolidWorks", f"Материал для «{current.name}»:", names, initial, False)
        return (library, material) if accepted and material else None

    def _select_solidworks_templates(
        self, missing: tuple[str, ...], current: tuple[str | None, str | None]
    ) -> tuple[str | None, str | None] | None:
        selected = list(current)
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Warning)
        prompt.setWindowTitle("Нужны шаблоны SolidWorks")
        prompt.setText("Не настроены шаблоны для экспорта в SolidWorks.")
        prompt.setInformativeText("Выберите шаблоны детали и сборки сейчас или отмените экспорт.")
        choose_button = prompt.addButton("Выбрать шаблоны", QMessageBox.AcceptRole)
        prompt.addButton("Отмена", QMessageBox.RejectRole)
        prompt.exec_()
        if prompt.clickedButton() is not choose_button:
            return None
        choices = {
            "part": (0, "Выберите шаблон детали SolidWorks", "Шаблоны деталей SolidWorks (*.prtdot)"),
            "assembly": (1, "Выберите шаблон сборки SolidWorks", "Шаблоны сборок SolidWorks (*.asmdot)"),
        }
        for kind in missing:
            index, title, file_filter = choices[kind]
            path, _ = QFileDialog.getOpenFileName(self, title, "", file_filter)
            if not path:
                return None
            selected[index] = path
        return selected[0], selected[1]

    def save_project(self) -> None:
        """Save the current editable pallet state; no automatic save is used."""
        if self.calculate(show_error=True) is None:
            return
        path = self._project_path
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Сохранить проект PalletLab",
                "pallet.palletlab.json",
                "Проекты PalletLab (*.palletlab.json);;JSON (*.json)",
            )
            if not path:
                return
            if not path.lower().endswith((".palletlab.json", ".json")):
                path += ".palletlab.json"
        if not self.controller.save_project(path):
            QMessageBox.warning(self, "Сохранение проекта", "Не удалось сохранить файл проекта.")
            return
        self._project_path = path
        self.statusBar().showMessage(f"Проект сохранён: {path}")

    def open_project(self) -> None:
        """Open a manually selected project file and rebuild the viewport."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть проект PalletLab",
            "",
            "Проекты PalletLab (*.palletlab.json *.json);;Все файлы (*)",
        )
        if not path:
            return
        if self.controller.open_project(path) is None:
            QMessageBox.warning(self, "Открытие проекта", "Не удалось открыть файл проекта.")
            return
        self._imported_step_model = None
        self._clear_model_supports()
        self.view.clear_step_model()
        self._set_model_controls_visible(False)
        self._project_path = path
        self._history.clear()
        MainWindow._discard_history_transaction(self)
        self.statusBar().showMessage(f"Проект открыт: {path}")

    def export_to_kompas(self) -> None:
        """Rebuild the visible pallet and export its exact current geometry."""
        result = self.calculate(show_error=True)
        if result is None:
            return
        parent = QFileDialog.getExistingDirectory(self, "Выберите папку для экспорта КОМПАС-3D")
        if not parent:
            return
        self.export_kompas_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            output = export_kompas_pallet(result, parent, self.state.material_id)
        except KompasExportError as exc:
            QMessageBox.critical(self, "Экспорт в КОМПАС-3D", str(exc))
            self.statusBar().showMessage("Экспорт в КОМПАС-3D не выполнен.")
        else:
            QApplication.restoreOverrideCursor()
            QMessageBox.information(self, "Экспорт в КОМПАС-3D", f"Детали и сборка сохранены в папке:\n{output}")
            self.statusBar().showMessage(f"Экспорт в КОМПАС-3D завершён: {output}")
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            self.export_kompas_button.setEnabled(True)

    def _schedule_recalculation(self, *_args) -> None:
        """Queue one rebuild after the user pauses editing a parameter."""
        MainWindow._begin_history_transaction(self)
        sender_method = getattr(self, "sender", None)
        sender = sender_method() if callable(sender_method) else None
        for layer_id, panel in getattr(self, "_layer_panels", {}).items():
            if sender is panel:
                self._layer_envelope_source = layer_id
                break
        if len(getattr(self, "_layer_order", ())) > 2:
            self._set_stale(True)
            self._layer_rebuild_timer.start()
            return
        if getattr(self, "_imported_step_model", None) is not None and getattr(self, "_model_supports", ()):
            self.controller.stop_scheduled_recalculation()
            self._set_stale(True)
            self._model_rebuild_timer.start()
            return
        self.controller.schedule_recalculation()

    def _switch_model_pallet_to_manual_editing(self) -> None:
        """Keep an imported model visible while manual beam edits take over."""
        if not getattr(self, "_model_supports", ()):
            return
        self._model_rebuild_timer.stop()
        self._clear_model_supports()
        self._set_model_controls_visible(False)
        self.length_panel.set_model_driven_mode(None)
        self.width_panel.set_model_driven_mode(None)

    def _layer_changed(self, *_args) -> None:
        self.controller.set_upper_layer(self.upper_layer())
        self._schedule_recalculation()

    def _rounding_changed(self, *_args) -> None:
        self.controller.set_rounding_step(self.rounding_buttons.checkedId())
        self._schedule_recalculation()

    def _set_camera(self, index: int) -> None:
        handlers = {
            "isometric": self.view.camera_isometric,
            "top": self.view.camera_top,
            "front": self.view.camera_front,
            "side": self.view.camera_side,
        }
        camera = self.camera_combo.itemData(index)
        self.state.camera = camera
        handlers[camera]()

    def _refresh_dimension_annotations(self) -> None:
        self.controller.refresh_dimension_annotations(
            show_length=self.show_length_gaps.isChecked(),
            show_width=self.show_width_gaps.isChecked(),
        )

    def _toggle_insertion_mode(self, enabled: bool) -> None:
        if not enabled:
            self.controller.deactivate_tool()
            self._cancel_pending_insertion()
            self.view.disable_insertion_mode()
            self.view.disable_support_face_selection()
            return
        if self.delete_beam_button.isChecked():
            self.delete_beam_button.setChecked(False)
        if self.edit_distance_button.isChecked():
            self.edit_distance_button.setChecked(False)
        if self.change_section_button.isChecked():
            self.change_section_button.setChecked(False)
        if self._last_result is None:
            self.add_beam_button.setChecked(False)
            return
        self._manual_supports.clear()
        self.view.enable_support_face_selection(self._manual_support_selected)
        self.controller.activate_tool("insertion")
        self.statusBar().showMessage("Выберите верхние или нижние грани двух параллельных брусьев.")

    def _manual_support_selected(self, layer_id: str, index: int, face: str) -> None:
        key = (layer_id, index, face)
        if key in self._manual_supports:
            return
        self._manual_supports.append(key)
        if len(self._manual_supports) == 1:
            self.statusBar().showMessage("Выберите такую же (верхнюю или нижнюю) грань второй параллельной опоры.")
            return
        first, second = self._manual_supports
        beams = {(beam.layer_id, beam.layer_index): beam for beam in self._last_result.beams_3d}
        first_key, second_key = first[:2], second[:2]
        if (first_key not in beams or second_key not in beams or first[2] != second[2]
                or beams[first_key].orientation != beams[second_key].orientation):
            self._manual_supports.clear()
            self.statusBar().showMessage("Выберите одинаковые верхние или нижние грани двух параллельных брусьев.")
            return
        self.view.disable_support_face_selection()
        self._open_manual_beam_dialog(first, second)

    def _open_manual_beam_dialog(
        self, first: tuple[str, int, str], second: tuple[str, int, str],
        reference: tuple[str, int, str] | None = None, dialog: ManualBeamDialog | None = None,
    ) -> None:
        dialog = dialog or ManualBeamDialog(self)
        if reference is not None:
            dialog.pick_reference.setText(f"Грань выбрана: {reference[0]} · брус {reference[1] + 1}")
        answer = dialog.exec_()
        if answer == 2:
            self.statusBar().showMessage("Выберите грань объекта для точки отсчёта.")
            self.view.enable_beam_face_selection(
                lambda layer_id, index, face: self._manual_reference_selected(first, second, (layer_id, index, face), dialog)
            )
            return
        if answer == QDialog.Accepted:
            selected_reference = reference[:2] if reference is not None and dialog.reference.currentData() else None
            MainWindow._begin_history_transaction(self)
            result = self.controller.add_manual_beam(
                first[:2], second[:2], dialog.distance.value(), dialog.section(),
                reference_support=selected_reference,
                reference_face=reference[2] if selected_reference is not None else None,
                first_face=first[2], second_face=second[2],
            )
            if result is not None:
                MainWindow._commit_history_transaction(self)
                self.statusBar().showMessage("Брус добавлен. Выберите две следующие опоры.")
            else:
                MainWindow._discard_history_transaction(self)
        self._manual_supports.clear()
        if self.add_beam_button.isChecked():
            self.view.enable_support_face_selection(self._manual_support_selected)

    def _manual_reference_selected(
        self, first: tuple[str, int, str], second: tuple[str, int, str], reference: tuple[str, int, str], dialog: ManualBeamDialog,
    ) -> None:
        beams = {(beam.layer_id, beam.layer_index): beam for beam in self._last_result.beams_3d}
        support = beams.get(first[:2])
        if support is None:
            self._manual_supports.clear()
            return
        required_faces = ("x_min", "x_max") if support.orientation == "length" else ("y_min", "y_max")
        if reference[2] not in required_faces:
            axis = "X" if support.orientation == "length" else "Y"
            self.statusBar().showMessage(f"Выберите боковую грань, перпендикулярную оси {axis}.")
            self.view.enable_beam_face_selection(
                lambda layer_id, index, face: self._manual_reference_selected(first, second, (layer_id, index, face), dialog)
            )
            return
        self.view.disable_support_face_selection()
        self._open_manual_beam_dialog(first, second, reference, dialog)

    def _toggle_deletion_mode(self, enabled: bool) -> None:
        if not enabled:
            self.controller.deactivate_tool()
            self.controller.clear_deletion_selection()
            self.deletion_editor.setVisible(False)
            self.view.disable_deletion_mode()
            return
        if self.add_beam_button.isChecked():
            self.add_beam_button.setChecked(False)
        if self.edit_distance_button.isChecked():
            self.edit_distance_button.setChecked(False)
        if self.change_section_button.isChecked():
            self.change_section_button.setChecked(False)
        if self._last_result is None:
            self.delete_beam_button.setChecked(False)
            return
        self.controller.clear_deletion_selection()
        self.deletion_editor.setVisible(True)
        self._update_deletion_editor()
        self.view.enable_deletion_mode(self._selection_changed)
        self.controller.activate_tool("deletion")
        self.statusBar().showMessage("Нажмите на внутренние брусья для выбора. Крайние брусья удалить нельзя.")

    def _toggle_distance_editing(self, enabled: bool) -> None:
        if not enabled:
            self.controller.deactivate_tool()
            self._cancel_pending_distance_edit()
            self.view.disable_distance_editing()
            return
        if self.add_beam_button.isChecked():
            self.add_beam_button.setChecked(False)
        if self.delete_beam_button.isChecked():
            self.delete_beam_button.setChecked(False)
        if self.change_section_button.isChecked():
            self.change_section_button.setChecked(False)
        if self._last_result is None:
            self.edit_distance_button.setChecked(False)
            return
        self.controller.enable_distance_editing(self._start_distance_edit)
        self.controller.activate_tool("distance_editing")
        self.statusBar().showMessage("Наведите курсор на размерную линию и нажмите: внутренний брус или общий габарит.")

    def _toggle_section_editing(self, enabled: bool) -> None:
        if not enabled:
            self.controller.deactivate_tool()
            self.controller.clear_section_selection()
            self.section_editor.setVisible(False)
            self.view.disable_section_editing()
            return
        for button in (self.add_beam_button, self.delete_beam_button, self.edit_distance_button):
            if button.isChecked():
                button.setChecked(False)
        if self._last_result is None:
            self.change_section_button.setChecked(False)
            return
        self.controller.clear_section_selection()
        self.section_editor.setVisible(True)
        self._update_section_editor()
        self.view.enable_section_editing(self._section_selection_changed)
        self.controller.activate_tool("section_editing")
        self.statusBar().showMessage("Выберите один или несколько брусьев, затем нажмите «Изменить…».")

    def _start_distance_edit(self, layer_id: str, beam_index: int, value: float) -> None:
        self.controller.begin_distance_edit(layer_id, beam_index)
        self.distance_value.blockSignals(True)
        self.distance_value.setValue(value)
        self.distance_value.blockSignals(False)
        self.distance_editor.setVisible(True)
        self.distance_value.setFocus()
        self.distance_value.selectAll()

    def _cancel_pending_distance_edit(self) -> None:
        self.controller.cancel_distance_edit()
        self.distance_editor.setVisible(False)
        if self.edit_distance_button.isChecked():
            self.statusBar().showMessage("Наведите курсор на размерную линию и нажмите: внутренний брус или общий габарит.")
        self.edit_distance_button.setFocus()

    def _confirm_distance_edit(self) -> None:
        MainWindow._begin_history_transaction(self)
        update = self.controller.confirm_distance_edit(self.distance_value.value())
        if update is None:
            MainWindow._discard_history_transaction(self)
            return
        layer_id, updated_input = update
        if updated_input is not None:
            panel = MainWindow._panel_for_layer(self, layer_id)
            MainWindow._switch_model_pallet_to_manual_editing(self)
            MainWindow._apply_interactive_position_update(self, panel, updated_input)
        self.distance_editor.setVisible(False)
        result = self.controller.recalculate_from_state()
        if result is not None:
            MainWindow._commit_history_transaction(self)
        else:
            MainWindow._discard_history_transaction(self)
        # Rebuilding the viewport removes the old pickable dimension actors.
        # Keep the checked tool immediately usable by registering the new ones.
        if result is not None and self.edit_distance_button.isChecked():
            self._toggle_distance_editing(True)
        self.statusBar().showMessage("Расстояние обновлено. Выберите следующую размерную линию.")

    def _selection_changed(self, layer_id: str, index: int, selected: bool) -> None:
        self.controller.set_deletion_selection(layer_id, index, selected)
        self._update_deletion_editor()

    def _section_selection_changed(self, layer_id: str, index: int, selected: bool) -> None:
        self.controller.set_section_selection(layer_id, index, selected)
        self._update_section_editor()

    def _update_section_editor(self) -> None:
        count = sum(len(indices) for indices in self._selected_for_section.values())
        self.section_hint.setText(
            "Выделено: " + (f"{count}. Сечение будет заменено." if count else "0. Выберите брусья в модели.")
        )
        self.confirm_section_button.setEnabled(count > 0)

    def _confirm_section_change(self) -> None:
        if not any(self._selected_for_section.values()):
            return
        dialog = BeamSectionDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return
        changed = sum(len(indices) for indices in self._selected_for_section.values())
        MainWindow._begin_history_transaction(self)
        MainWindow._switch_model_pallet_to_manual_editing(self)
        result = self.controller.apply_section_change(dialog.section())
        if result is not None:
            MainWindow._commit_history_transaction(self)
        else:
            MainWindow._discard_history_transaction(self)
        if result is not None and self.change_section_button.isChecked():
            self._toggle_section_editing(True)
            self.statusBar().showMessage(f"Сечение изменено у брусьев: {changed}.")

    def _update_deletion_editor(self) -> None:
        count = sum(len(indices) for indices in self._selected_for_deletion.values())
        self.deletion_hint.setText("Выделено: " + (f"{count}. Красные брусья будут удалены." if count else "0. Выберите брусья в модели."))
        self.confirm_deletion_button.setText(f"Удалить выбранные ({count})")
        self.confirm_deletion_button.setEnabled(count > 0)

    def _confirm_deletion(self) -> None:
        MainWindow._begin_history_transaction(self)
        updated_inputs = self.controller.confirm_deletion()
        if updated_inputs is None:
            MainWindow._discard_history_transaction(self)
            return
        deleted = sum(len(indices) for indices in self._selected_for_deletion.values())
        MainWindow._switch_model_pallet_to_manual_editing(self)
        timer = getattr(self, "_layer_rebuild_timer", None)
        if timer is not None:
            timer.stop()
        for layer_id, updated_input in updated_inputs.items():
            panel = MainWindow._panel_for_layer(self, layer_id)
            MainWindow._apply_interactive_position_update(self, panel, updated_input)
        result = self.controller.recalculate_from_state()
        if result is not None:
            MainWindow._commit_history_transaction(self)
        else:
            MainWindow._discard_history_transaction(self)
        # ``show_pallet`` recreates all beam actors, so restore deletion
        # picking without forcing the user to toggle the tool off and on.
        if result is not None and self.delete_beam_button.isChecked():
            self._toggle_deletion_mode(True)
        self.statusBar().showMessage(f"Удалено брусьев: {deleted}.")

    def _start_insertion(self, slot: InsertionSlot) -> None:
        if not self.controller.begin_insertion(slot):
            return
        self.insertion_gap.blockSignals(True)
        self.insertion_gap.setRange(0, slot.maximum_clear_gap)
        self.insertion_gap.setValue(slot.suggested_clear_gap)
        self.insertion_gap.blockSignals(False)
        self.insertion_editor.setVisible(True)
        self._update_insertion_preview()
        self.insertion_gap.setFocus()
        self.insertion_gap.selectAll()

    def _update_insertion_preview(self) -> None:
        self.controller.preview_insertion(self.insertion_gap.value())

    def _cancel_pending_insertion(self) -> None:
        self.controller.cancel_insertion()
        self.insertion_editor.setVisible(False)
        if self.add_beam_button.isChecked():
            self.statusBar().showMessage("Выберите + в нужном промежутке. Esc или повторное нажатие завершает режим.")
        self.add_beam_button.setFocus()

    def _confirm_insertion(self) -> None:
        MainWindow._begin_history_transaction(self)
        update = self.controller.confirm_insertion(self.insertion_gap.value())
        if update is None:
            MainWindow._discard_history_transaction(self)
            return
        layer_id, updated_input = update
        panel = MainWindow._panel_for_layer(self, layer_id)
        MainWindow._switch_model_pallet_to_manual_editing(self)
        MainWindow._apply_interactive_position_update(self, panel, updated_input)
        self.insertion_editor.setVisible(False)
        result = self.controller.recalculate_from_state()
        if result is not None:
            MainWindow._commit_history_transaction(self)
        else:
            MainWindow._discard_history_transaction(self)
        # The viewport rebuild removes insertion markers together with the old
        # beams. Re-register the markers while the tool remains checked.
        if result is not None and self.add_beam_button.isChecked():
            self._toggle_insertion_mode(True)

    def keyPressEvent(self, event) -> None:
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.delete_beam_button.isChecked()
                and any(self._selected_for_deletion.values())):
            self._confirm_deletion()
            event.accept()
            return
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.change_section_button.isChecked()
                and any(self._selected_for_section.values())):
            self._confirm_section_change()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and (self.add_beam_button.isChecked() or self.delete_beam_button.isChecked()
                                               or self.edit_distance_button.isChecked() or self.change_section_button.isChecked()):
            if self.add_beam_button.isChecked():
                self.add_beam_button.setChecked(False)
            elif self.delete_beam_button.isChecked():
                self.delete_beam_button.setChecked(False)
            elif self.edit_distance_button.isChecked():
                self.edit_distance_button.setChecked(False)
            else:
                self.change_section_button.setChecked(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if (event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and self._pending_insertion is not None
                and watched in (self.insertion_gap, self.insertion_gap.lineEdit())):
            self._confirm_insertion()
            return True
        if (event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and self.delete_beam_button.isChecked() and any(self._selected_for_deletion.values())):
            self._confirm_deletion()
            return True
        if (event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and self.change_section_button.isChecked() and any(self._selected_for_section.values())):
            self._confirm_section_change()
            return True
        if (event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape
                and self.add_beam_button.isChecked() and self._pending_insertion is None):
            self.add_beam_button.setChecked(False)
            return True
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape and self.delete_beam_button.isChecked():
            self.delete_beam_button.setChecked(False)
            return True
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape and self.edit_distance_button.isChecked():
            self.edit_distance_button.setChecked(False)
            return True
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape and self.change_section_button.isChecked():
            self.change_section_button.setChecked(False)
            return True
        return super().eventFilter(watched, event)

    def _update_scene_info(self, result) -> None:
        material = get_material(self.state.material_id)
        self.scene_info.setText(
            f"Габариты поддона: длина {format_mm(result.pallet_length)} мм · "
            f"ширина {format_mm(result.pallet_width)} мм · высота {format_mm(result.pallet_height)} мм    "
            f"|    Балки: поперечные {format_mm(result.pallet_width)} мм · "
            f"продольные {format_mm(result.pallet_length)} мм    "
            f"|    Материал: {material.name} · масса {pallet_mass_kg(result.beams_3d, material.id):.1f} кг"
        )

    def _material_changed(self, _index: int) -> None:
        material_id = self.material_combo.currentData()
        if material_id == self.state.material_id:
            return
        MainWindow._begin_history_transaction(self)
        self.state.material_id = material_id
        MainWindow._commit_history_transaction(self)
        if self._last_result is not None:
            self._update_scene_info(self._last_result)

    def _handle_calculation_error(self, error: CalculationError, show_error: bool) -> None:
        self.statusBar().showMessage(str(error))
        if show_error:
            QMessageBox.warning(self, "Невозможная геометрия", str(error))

    def calculate(self, *, show_error: bool = True):
        if len(getattr(self, "_layer_order", ())) > 2:
            return self._calculate_layer_stack(show_error=show_error)
        try:
            length_input, width_input, upper_layer = self._read_calculation_inputs()
        except CalculationError as exc:
            self._set_stale(True)
            self._handle_calculation_error(exc, show_error)
            return None
        result = self.controller.calculate(
            length_input,
            width_input,
            upper_layer,
            show_error=show_error,
        )
        if result is None:
            return None
        if self.add_beam_button.isChecked():
            self._toggle_insertion_mode(True)
        elif self.delete_beam_button.isChecked():
            self._toggle_deletion_mode(True)
        elif self.edit_distance_button.isChecked():
            self._toggle_distance_editing(True)
        elif self.change_section_button.isChecked():
            self._toggle_section_editing(True)
        return result

    def _read_calculation_inputs(self):
        rounding_step = self.rounding_buttons.checkedId()
        self.controller.set_rounding_step(rounding_step)
        self.controller.set_upper_layer(self.upper_layer())
        return (
            self.length_panel.values(rounding_step != 0, rounding_step or 5),
            self.width_panel.values(rounding_step != 0, rounding_step or 5),
            self.state.upper_layer,
        )

    def _apply_loaded_project(self, state: ProjectState) -> None:
        """Reflect an opened configuration in form controls without queuing rebuilds."""
        if state.length_input is None or state.width_input is None:
            return
        if state.multi_layer_mode and len(state.layers) > 2:
            self._restore_layer_stack(state.layers)
        self.length_panel.set_model_driven_mode(None)
        self.width_panel.set_model_driven_mode(None)
        blockers = [QSignalBlocker(widget) for widget in (
            self.length_panel, self.width_panel, self.width_upper, self.length_upper,
            self.round_to_50, self.round_to_5, self.no_rounding, self.show_length_gaps,
            self.show_width_gaps, self.camera_combo, self.material_combo,
        )]
        material_index = self.material_combo.findData(state.material_id)
        self.material_combo.setCurrentIndex(max(0, material_index))
        self.length_panel.apply_direction_data(state.length_input, notify=False)
        self.width_panel.apply_direction_data(state.width_input, notify=False)
        self.length_upper.setChecked(state.upper_layer == "length")
        self.width_upper.setChecked(state.upper_layer == "width")
        {50: self.round_to_50, 5: self.round_to_5, 0: self.no_rounding}[state.rounding_step].setChecked(True)
        self.show_length_gaps.setChecked(state.show_length_dimensions)
        self.show_width_gaps.setChecked(state.show_width_dimensions)
        camera_index = self.camera_combo.findData(state.camera)
        self.camera_combo.setCurrentIndex(camera_index)
        del blockers
        self._set_camera(camera_index)

    def reset_example(self) -> None:
        MainWindow._begin_history_transaction(self)
        for button in (self.add_beam_button, self.delete_beam_button, self.edit_distance_button, self.change_section_button):
            button.setChecked(False)
        self.controller.deactivate_tool()
        self.controller.cancel_insertion()
        self.controller.cancel_distance_edit()
        self.length_panel.set_model_driven_mode(None)
        self.width_panel.set_model_driven_mode(None)
        self._imported_step_model = None
        self.state.beam_sections.clear()
        self.state.layer_sections.clear()
        self.state.manual_beams.clear()
        self.controller.clear_deletion_selection()
        self.controller.clear_section_selection()
        self.view.clear_step_model()
        self._set_model_controls_visible(False)
        self._restore_layer_stack([
            LayerInput("length", "length", self.length_panel.values()),
            LayerInput("width", "width", self.width_panel.values()),
            LayerInput("layer-1", "length", self.top_length_panel.values()),
        ])
        self.length_panel.reset_example("1070 460 1300 499", 123, 552)
        self.width_panel.reset_example("560 720", 277, 179)
        self.top_length_panel.reset_example("1070 460 1300 499", 123, 552)
        self.width_upper.setChecked(True)
        self.calculate()

    def _restore_layer_stack(self, layers: list[LayerInput]) -> None:
        """Replace dynamic layer cards from a saved multilayer project."""
        expected_layer_ids = {layer.layer_id for layer in layers}
        for layer_id in list(self._layer_panels):
            if layer_id not in ("length", "width") and layer_id not in expected_layer_ids:
                # A layer card can still own this widget while a layout update
                # is pending.  Do not queue it for deletion: Qt may then delete
                # the panel after it has been added to a newly rebuilt card.
                panel = self._layer_panels.pop(layer_id)
                panel.setParent(None)
                panel.hide()
        self._layer_order = []
        self._layer_axes = {}
        for position, layer in enumerate(layers):
            panel = self._layer_panels.get(layer.layer_id)
            if panel is None:
                panel = DirectionInputPanel("", self._layer_description(layer.axis), "", "100", "100")
                panel.changed.connect(self._schedule_recalculation)
                self._layer_panels[layer.layer_id] = panel
            panel.apply_direction_data(layer.direction, notify=False)
            self._layer_order.append(layer.layer_id)
            self._layer_axes[layer.layer_id] = layer.axis
            if layer.layer_id == "layer-1":
                self.top_length_panel = panel
        self._rebuild_layer_cards()

    def upper_layer(self) -> str:
        return "length" if self.length_upper.isChecked() else "width"


def run() -> int:
    # These must be set before QApplication exists so Qt uses logical pixels on
    # Windows 125%, 150% and mixed-DPI monitor configurations.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("PalletLab")
    window = MainWindow()
    window.showMaximized()
    return app.exec_()
