"""Main desktop window for calculating and visualising a wooden pallet."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QSettings, QSignalBlocker, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QDoubleSpinBox, QRadioButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from palletlab.controllers.pallet_controller import PalletController
from palletlab.core.calculator import insertion_slots
from palletlab.core.formatting import format_mm
from palletlab.core.materials import MATERIALS, get_material, pallet_mass_kg
from palletlab.core.models import InsertionSlot, PalletAxis
from palletlab.core.project_state import ProjectState
from palletlab.core.validation import CalculationError
from palletlab.exporters.kompas import KompasExportError, export_pallet as export_kompas_pallet
from palletlab.exporters.solidworks import SolidWorksExportError, SolidWorksTemplateError, export_pallet
from palletlab.ui import resources_rc  # Registers SVGs used by the application QSS.
from palletlab.ui.input_panel import DirectionInputPanel
from palletlab.ui.update_dialog import check_for_updates
from palletlab.version import __version__
from palletlab.visualization.pallet_view import PalletView


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
    def _pending_distance(self, value: tuple[PalletAxis, int] | None) -> None:
        self.state.pending_distance = value

    @property
    def _selected_for_deletion(self) -> dict[PalletAxis, set[int]]:
        return self.state.selected_for_deletion

    @_selected_for_deletion.setter
    def _selected_for_deletion(self, value: dict[PalletAxis, set[int]]) -> None:
        self.state.selected_for_deletion = value

    def __init__(self) -> None:
        super().__init__()
        self.state = ProjectState()
        self._project_path: str | None = None
        self.setWindowTitle(f"PalletLab {__version__} — расчёт поддонов")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1400, int(screen.width() * 0.92)), min(900, int(screen.height() * 0.90)))
        self.setMinimumSize(900, 650)
        self.length_panel = DirectionInputPanel("01  Длина", "Центры опор задаются по оси X. Эти координаты определяют поперечные брусья.", "1070 460 1300 499", "123", "552")
        self.width_panel = DirectionInputPanel("02  Ширина", "Центры опор задаются по оси Y. Эти координаты определяют продольные брусья.", "560 720", "277", "179")
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
        controls_layout.addWidget(self.length_panel)
        controls_layout.addWidget(self.width_panel)
        layer_card = QFrame()
        layer_card.setObjectName("layerCard")
        layer_layout = QVBoxLayout(layer_card)
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
        controls_layout.addWidget(layer_card)
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
        self.distance_editor = QFrame()
        self.distance_editor.setObjectName("distanceEditor")
        distance_layout = QHBoxLayout(self.distance_editor)
        distance_layout.setContentsMargins(8, 4, 8, 4)
        distance_layout.setSpacing(6)
        distance_layout.addWidget(QLabel("Новое расстояние:"))
        self.distance_value = InsertionGapSpinBox()
        self.distance_value.setRange(0, 1_000_000)
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
        self.length_panel.changed.connect(self._schedule_recalculation)
        self.width_panel.changed.connect(self._schedule_recalculation)
        self.layer_buttons.buttonClicked.connect(self._layer_changed)
        self.rounding_buttons.buttonClicked.connect(self._rounding_changed)
        self.show_length_gaps.toggled.connect(self._refresh_dimension_annotations)
        self.show_width_gaps.toggled.connect(self._refresh_dimension_annotations)
        self.setStyleSheet(self._stylesheet())
        self.add_beam_button.installEventFilter(self)
        self.delete_beam_button.installEventFilter(self)
        self.edit_distance_button.installEventFilter(self)
        self.view.installEventFilter(self)

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
            QFrame#insertionEditor { background: #e7f0ed; border: 1px solid #b9d4cd; border-radius: 7px; }
            QLabel#insertionHint { color: #55706a; font-size: 11px; }
            QFrame#deletionEditor { background: #fbe9e7; border: 1px solid #edb7b1; border-radius: 7px; }
            QLabel#deletionHint { color: #81332e; font-size: 11px; }
            QPushButton#confirmDeletionButton { background: #b83e37; border-color: #b83e37; color: #fff; font-weight: 650; padding: 6px 9px; }
            QPushButton#confirmDeletionButton:disabled { background: #e3b9b5; border-color: #e3b9b5; color: #fff; }
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
            try:
                output = export_pallet(result, parent, templates, self.state.material_id)
            except SolidWorksTemplateError as error:
                templates = self._select_solidworks_templates(error.missing, templates)
                if templates is None:
                    self.statusBar().showMessage("Экспорт в SolidWorks отменён: не выбран шаблон.")
                    return
                self._save_solidworks_templates(templates)
                output = export_pallet(result, parent, templates, self.state.material_id)
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

    def _select_solidworks_templates(
        self, missing: tuple[str, ...], current: tuple[str | None, str | None]
    ) -> tuple[str | None, str | None] | None:
        selected = list(current)
        answer = QMessageBox.question(self, "Нужны шаблоны SolidWorks", "Не настроены шаблоны для экспорта. Выбрать их сейчас?", QMessageBox.Cancel | QMessageBox.Open, QMessageBox.Open)
        if answer != QMessageBox.Open:
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
        self._project_path = path
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
        self.controller.schedule_recalculation()

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
            return
        if self.delete_beam_button.isChecked():
            self.delete_beam_button.setChecked(False)
        if self.edit_distance_button.isChecked():
            self.edit_distance_button.setChecked(False)
        if self._last_result is None:
            self.add_beam_button.setChecked(False)
            return
        slots = insertion_slots(self._last_result, "length") + insertion_slots(self._last_result, "width")
        if not slots:
            self.statusBar().showMessage("Нет промежутков, в которые помещается ещё один брус.")
            self.add_beam_button.setChecked(False)
            return
        self.controller.enable_insertion_mode(slots, self._start_insertion)
        self.controller.activate_tool("insertion")
        self.statusBar().showMessage("Выберите + в нужном промежутке. Esc или повторное нажатие завершает режим.")

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
        if self._last_result is None:
            self.edit_distance_button.setChecked(False)
            return
        self.controller.enable_distance_editing(self._start_distance_edit)
        self.controller.activate_tool("distance_editing")
        self.statusBar().showMessage("Наведите курсор на размерную линию и нажмите: внутренний брус или общий габарит.")

    def _start_distance_edit(self, axis: PalletAxis, beam_index: int, value: float) -> None:
        self.controller.begin_distance_edit(axis, beam_index)
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
        update = self.controller.confirm_distance_edit(self.distance_value.value())
        if update is None:
            return
        axis, updated_input = update
        panel = self.length_panel if axis == "length" else self.width_panel
        panel.apply_position_data(updated_input)
        self.distance_editor.setVisible(False)
        self.controller.recalculate_from_state()
        self.statusBar().showMessage("Расстояние обновлено. Выберите следующую размерную линию.")

    def _selection_changed(self, axis: PalletAxis, index: int, selected: bool) -> None:
        self.controller.set_deletion_selection(axis, index, selected)
        self._update_deletion_editor()

    def _update_deletion_editor(self) -> None:
        count = sum(len(indices) for indices in self._selected_for_deletion.values())
        self.deletion_hint.setText("Выделено: " + (f"{count}. Красные брусья будут удалены." if count else "0. Выберите брусья в модели."))
        self.confirm_deletion_button.setText(f"Удалить выбранные ({count})")
        self.confirm_deletion_button.setEnabled(count > 0)

    def _confirm_deletion(self) -> None:
        updated_inputs = self.controller.confirm_deletion()
        if updated_inputs is None:
            return
        deleted = sum(len(indices) for indices in self._selected_for_deletion.values())
        for axis, updated_input in updated_inputs.items():
            panel = self.length_panel if axis == "length" else self.width_panel
            panel.apply_position_data(updated_input)
        self.delete_beam_button.setChecked(False)
        self.controller.recalculate_from_state()
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
        update = self.controller.confirm_insertion(self.insertion_gap.value())
        if update is None:
            return
        axis, updated_input = update
        panel = self.length_panel if axis == "length" else self.width_panel
        panel.apply_position_data(updated_input)
        self.insertion_editor.setVisible(False)
        self.controller.recalculate_from_state()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and (self.add_beam_button.isChecked() or self.delete_beam_button.isChecked()
                                               or self.edit_distance_button.isChecked()):
            if self.add_beam_button.isChecked():
                self.add_beam_button.setChecked(False)
            elif self.delete_beam_button.isChecked():
                self.delete_beam_button.setChecked(False)
            else:
                self.edit_distance_button.setChecked(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
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
        self.state.material_id = self.material_combo.currentData()
        if self._last_result is not None:
            self._update_scene_info(self._last_result)

    def _handle_calculation_error(self, error: CalculationError, show_error: bool) -> None:
        self.statusBar().showMessage(str(error))
        if show_error:
            QMessageBox.warning(self, "Невозможная геометрия", str(error))

    def calculate(self, *, show_error: bool = True):
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
        blockers = [QSignalBlocker(widget) for widget in (
            self.length_panel, self.width_panel, self.width_upper, self.length_upper,
            self.round_to_50, self.round_to_5, self.no_rounding, self.show_length_gaps,
            self.show_width_gaps, self.camera_combo,
        )]
        material_index = self.material_combo.findData(state.material_id)
        self.material_combo.setCurrentIndex(max(0, material_index))
        self.length_panel.apply_position_data(state.length_input)
        self.width_panel.apply_position_data(state.width_input)
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
        self.length_panel.reset_example("1070 460 1300 499", 123, 552)
        self.width_panel.reset_example("560 720", 277, 179)
        self.width_upper.setChecked(True)
        self.calculate()

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
