"""Main desktop window for calculating and visualising a wooden pallet."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QDoubleSpinBox, QRadioButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from palletlab.core.calculator import (build_pallet, calculate_direction, delete_beams_input, insert_beam_input,
                                       insertion_slots, set_beam_face_distance_input)
from palletlab.core.formatting import format_mm
from palletlab.core.models import InsertionSlot, PalletAxis
from palletlab.core.validation import CalculationError
from palletlab.ui import resources_rc  # Registers SVGs used by the application QSS.
from palletlab.ui.input_panel import DirectionInputPanel
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
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PalletLab — расчёт поддонов")
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
        self.show_length_gaps = QCheckBox("Расстояния по длине")
        self.show_width_gaps = QCheckBox("Расстояния по ширине")
        self.show_length_gaps.setChecked(True)
        self.show_width_gaps.setChecked(True)
        self._last_result = None
        self._last_inputs = {}
        self._pending_insertion: InsertionSlot | None = None
        self._pending_distance: tuple[PalletAxis, int] | None = None
        self._selected_for_deletion: dict[PalletAxis, set[int]] = {"length": set(), "width": set()}
        self.scene_info = QLabel()
        self.scene_info.setObjectName("sceneInfo")
        self.scene_info.setWordWrap(True)
        self.camera_combo = QComboBox()
        self.camera_combo.addItem("Сверху", "top")
        self.camera_combo.addItem("Спереди", "front")
        self.camera_combo.addItem("Сбоку", "side")
        self.camera_combo.addItem("Изометрия", "isometric")
        self._build_ui()
        self._set_stale(False)
        self.calculate()

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
        buttons = QHBoxLayout()
        calculate_button = QPushButton("Рассчитать и построить")
        calculate_button.setObjectName("calculateButton")
        calculate_button.clicked.connect(self.calculate)
        calculate_button.setMinimumHeight(42)
        reset_button = QPushButton("Сбросить пример")
        reset_button.clicked.connect(self.reset_example)
        reset_button.setMinimumHeight(42)
        buttons.addWidget(calculate_button, 1)
        buttons.addWidget(reset_button)
        action_layout.addLayout(buttons)
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
        self.length_panel.changed.connect(lambda: self._set_stale(True))
        self.width_panel.changed.connect(lambda: self._set_stale(True))
        self.layer_buttons.buttonClicked.connect(self._layer_changed)
        self.rounding_buttons.buttonClicked.connect(lambda: self._set_stale(True))
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
        eyebrow = QLabel("PALLETLAB / VERSION 1")
        eyebrow.setObjectName("eyebrow")
        brand.addWidget(eyebrow)
        title = QLabel("Расчёт и 3D-визуализация поддона")
        title.setObjectName("appTitle")
        brand.addWidget(title)
        layout.addLayout(brand)
        layout.addStretch()
        self.status_badge = QLabel("Расчёт актуален")
        self.status_badge.setObjectName("statusBadge")
        layout.addWidget(self.status_badge)
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
            QLabel#statusBadge { background: #e5f0ea; color: #2f6b4f; border-radius: 10px; padding: 6px 10px; font-weight: 600; }
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
            QPushButton#calculateButton { background: #255e64; border: 1px solid #255e64; color: #ffffff; font-weight: 650; }
            QPushButton#calculateButton:hover { background: #1e4e53; }
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
            self.status_badge.setText("Требуется пересчёт")
            self.status_badge.setStyleSheet("background: #f8ead9; color: #8a5525;")
            self.statusBar().showMessage("Параметры изменены — модель требует пересчёта.")
        else:
            self.status_badge.setText("Расчёт актуален")
            self.status_badge.setStyleSheet("")
            self.statusBar().showMessage("Расчёт актуален.")

    def _layer_changed(self, *_args) -> None:
        # Layer change is an input change; rebuild only after a successful calculation.
        self._set_stale(True)

    def _set_camera(self, index: int) -> None:
        handlers = {
            "isometric": self.view.camera_isometric,
            "top": self.view.camera_top,
            "front": self.view.camera_front,
            "side": self.view.camera_side,
        }
        handlers[self.camera_combo.itemData(index)]()

    def _refresh_dimension_annotations(self) -> None:
        if self._last_result is not None:
            self.view.show_pallet(
                self._last_result,
                show_length_gaps=self.show_length_gaps.isChecked(),
                show_width_gaps=self.show_width_gaps.isChecked(),
            )

    def _toggle_insertion_mode(self, enabled: bool) -> None:
        if not enabled:
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
        self.view.enable_insertion_mode(self._last_result, slots, self._start_insertion)
        self.statusBar().showMessage("Выберите + в нужном промежутке. Esc или повторное нажатие завершает режим.")

    def _toggle_deletion_mode(self, enabled: bool) -> None:
        if not enabled:
            self._selected_for_deletion = {"length": set(), "width": set()}
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
        self._selected_for_deletion = {"length": set(), "width": set()}
        self.deletion_editor.setVisible(True)
        self._update_deletion_editor()
        self.view.enable_deletion_mode(self._selection_changed)
        self.statusBar().showMessage("Нажмите на внутренние брусья для выбора. Крайние брусья удалить нельзя.")

    def _toggle_distance_editing(self, enabled: bool) -> None:
        if not enabled:
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
        self.view.enable_distance_editing(self._last_result, self._start_distance_edit)
        self.statusBar().showMessage("Наведите курсор на размерную линию и нажмите: внутренний брус или общий габарит.")

    def _start_distance_edit(self, axis: PalletAxis, beam_index: int, value: float) -> None:
        self._pending_distance = (axis, beam_index)
        self.distance_value.blockSignals(True)
        self.distance_value.setValue(value)
        self.distance_value.blockSignals(False)
        self.distance_editor.setVisible(True)
        self.distance_value.setFocus()
        self.distance_value.selectAll()

    def _cancel_pending_distance_edit(self) -> None:
        self._pending_distance = None
        self.distance_editor.setVisible(False)
        if self.edit_distance_button.isChecked():
            self.statusBar().showMessage("Наведите курсор на размерную линию и нажмите: внутренний брус или общий габарит.")
        self.edit_distance_button.setFocus()

    def _confirm_distance_edit(self) -> None:
        if self._pending_distance is None or self._last_result is None:
            return
        axis, beam_index = self._pending_distance
        data = self._last_inputs[axis]
        direction = self._last_result.length_result if axis == "length" else self._last_result.width_result
        try:
            updated_input = set_beam_face_distance_input(data, direction, beam_index, self.distance_value.value())
        except CalculationError as exc:
            self.statusBar().showMessage(str(exc))
            return
        panel = self.length_panel if axis == "length" else self.width_panel
        panel.apply_position_data(updated_input)
        self._pending_distance = None
        self.distance_editor.setVisible(False)
        self.calculate()
        self.statusBar().showMessage("Расстояние обновлено. Выберите следующую размерную линию.")

    def _selection_changed(self, axis: PalletAxis, index: int, selected: bool) -> None:
        selected_indices = self._selected_for_deletion[axis]
        if selected:
            selected_indices.add(index)
        else:
            selected_indices.discard(index)
        self._update_deletion_editor()

    def _update_deletion_editor(self) -> None:
        count = sum(len(indices) for indices in self._selected_for_deletion.values())
        self.deletion_hint.setText("Выделено: " + (f"{count}. Красные брусья будут удалены." if count else "0. Выберите брусья в модели."))
        self.confirm_deletion_button.setText(f"Удалить выбранные ({count})")
        self.confirm_deletion_button.setEnabled(count > 0)

    def _confirm_deletion(self) -> None:
        if self._last_result is None:
            return
        try:
            for axis, indices in self._selected_for_deletion.items():
                if not indices:
                    continue
                direction = self._last_result.length_result if axis == "length" else self._last_result.width_result
                updated_input = delete_beams_input(self._last_inputs[axis], direction, indices)
                panel = self.length_panel if axis == "length" else self.width_panel
                panel.apply_position_data(updated_input)
        except CalculationError as exc:
            self.statusBar().showMessage(str(exc))
            return
        deleted = sum(len(indices) for indices in self._selected_for_deletion.values())
        self.delete_beam_button.setChecked(False)
        self.calculate()
        self.statusBar().showMessage(f"Удалено брусьев: {deleted}.")

    def _start_insertion(self, slot: InsertionSlot) -> None:
        if self._last_result is None:
            return
        self._pending_insertion = slot
        self.insertion_gap.blockSignals(True)
        self.insertion_gap.setRange(0, slot.maximum_clear_gap)
        self.insertion_gap.setValue(slot.suggested_clear_gap)
        self.insertion_gap.blockSignals(False)
        self.insertion_editor.setVisible(True)
        self._update_insertion_preview()
        self.insertion_gap.setFocus()
        self.insertion_gap.selectAll()

    def _update_insertion_preview(self) -> None:
        if self._pending_insertion is None or self._last_result is None:
            return
        try:
            self.view.show_insertion_preview(self._last_result, self._pending_insertion, self.insertion_gap.value())
        except CalculationError:
            self.view.clear_insertion_preview()

    def _cancel_pending_insertion(self) -> None:
        self._pending_insertion = None
        self.insertion_editor.setVisible(False)
        self.view.clear_insertion_selection()
        self.view.clear_insertion_preview()
        if self.add_beam_button.isChecked():
            self.statusBar().showMessage("Выберите + в нужном промежутке. Esc или повторное нажатие завершает режим.")
        self.add_beam_button.setFocus()

    def _confirm_insertion(self) -> None:
        if self._pending_insertion is None or self._last_result is None:
            return
        slot = self._pending_insertion
        data = self._last_inputs[slot.axis]
        direction = self._last_result.length_result if slot.axis == "length" else self._last_result.width_result
        try:
            updated_input = insert_beam_input(data, direction, slot.after_beam_index, self.insertion_gap.value())
        except CalculationError as exc:
            self.statusBar().showMessage(str(exc))
            return
        panel = self.length_panel if slot.axis == "length" else self.width_panel
        panel.apply_position_data(updated_input)
        self._pending_insertion = None
        self.insertion_editor.setVisible(False)
        self.calculate()

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
        self.scene_info.setText(
            f"Габариты поддона: длина {format_mm(result.pallet_length)} мм · "
            f"ширина {format_mm(result.pallet_width)} мм · высота {format_mm(result.pallet_height)} мм    "
            f"|    Балки: поперечные {format_mm(result.pallet_width)} мм · "
            f"продольные {format_mm(result.pallet_length)} мм"
        )

    def calculate(self) -> None:
        try:
            rounding_step = self.rounding_buttons.checkedId()
            length_input = self.length_panel.values(rounding_step != 0, rounding_step or 5)
            width_input = self.width_panel.values(rounding_step != 0, rounding_step or 5)
            length = calculate_direction(length_input)
            width = calculate_direction(width_input)
            result = build_pallet(length, width, self.upper_layer())
        except CalculationError as exc:
            self._set_stale(True)
            QMessageBox.warning(self, "Невозможная геометрия", str(exc))
            return
        self._last_result = result
        self._last_inputs = {"length": length_input, "width": width_input}
        self._update_scene_info(result)
        self._refresh_dimension_annotations()
        if self.add_beam_button.isChecked():
            self._toggle_insertion_mode(True)
        elif self.delete_beam_button.isChecked():
            self._toggle_deletion_mode(True)
        elif self.edit_distance_button.isChecked():
            self._toggle_distance_editing(True)
        self._set_stale(False)

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
