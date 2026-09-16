"""Main desktop window for calculating and visualising a wooden pallet."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.formatting import format_mm
from palletlab.core.validation import CalculationError
from palletlab.ui import resources_rc  # Registers SVGs used by the application QSS.
from palletlab.ui.input_panel import DirectionInputPanel
from palletlab.visualization.pallet_view import PalletView


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
        self.show_length_gaps = QCheckBox("Зазоры X")
        self.show_width_gaps = QCheckBox("Зазоры Y")
        self.show_length_gaps.setChecked(True)
        self.show_width_gaps.setChecked(True)
        self._last_result = None
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
        self.rounding_checkbox = QCheckBox("Округлять габарит поддона до 5 мм")
        self.rounding_checkbox.setChecked(True)
        self.rounding_checkbox.setToolTip("При выключении используются точные расчётные размеры.")
        action_layout.addWidget(self.rounding_checkbox)
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
        view_heading.addStretch()
        unit_label = QLabel("мм")
        unit_label.setObjectName("paneHint")
        view_heading.addWidget(unit_label)
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
        self.rounding_checkbox.toggled.connect(lambda: self._set_stale(True))
        self.show_length_gaps.toggled.connect(self._refresh_dimension_annotations)
        self.show_width_gaps.toggled.connect(self._refresh_dimension_annotations)
        self.setStyleSheet(self._stylesheet())

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
            QPushButton { background: #fffdf9; border: 1px solid #d8d3c8; border-radius: 7px; padding: 8px 11px; color: #33464a; }
            QPushButton:hover { background: #f0ece3; border-color: #bcb5a7; }
            QPushButton:checked { background: #dfece9; border: 2px solid #4b7a76; color: #1f5c58; font-weight: 650; }
            QPushButton#calculateButton { background: #255e64; border: 1px solid #255e64; color: #ffffff; font-weight: 650; }
            QPushButton#calculateButton:hover { background: #1e4e53; }
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

    def _update_scene_info(self, result) -> None:
        self.scene_info.setText(
            f"Габариты поддона: длина {format_mm(result.pallet_length)} мм · "
            f"ширина {format_mm(result.pallet_width)} мм · высота {format_mm(result.pallet_height)} мм    "
            f"|    Балки: поперечные {format_mm(result.pallet_width)} мм · "
            f"продольные {format_mm(result.pallet_length)} мм"
        )

    def calculate(self) -> None:
        try:
            length = calculate_direction(self.length_panel.values(self.rounding_checkbox.isChecked()))
            width = calculate_direction(self.width_panel.values(self.rounding_checkbox.isChecked()))
            result = build_pallet(length, width, self.upper_layer())
        except CalculationError as exc:
            self._set_stale(True)
            QMessageBox.warning(self, "Невозможная геометрия", str(exc))
            return
        self._last_result = result
        self._update_scene_info(result)
        self._refresh_dimension_annotations()
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
    window.show()
    return app.exec_()
