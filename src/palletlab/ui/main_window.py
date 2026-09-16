"""Main desktop window for calculating and visualising a wooden pallet."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.validation import CalculationError
from palletlab.ui.input_panel import DirectionInputPanel
from palletlab.ui.results_panel import ResultsPanel
from palletlab.visualization.pallet_view import PalletView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PalletLab — расчёт поддонов")
        self.resize(1400, 900)
        self.length_panel = DirectionInputPanel("01  Длина", "Центры опор задаются по оси X. Эти координаты определяют поперечные брусья.", "1070 460 1300 499", "123", "552")
        self.width_panel = DirectionInputPanel("02  Ширина", "Центры опор задаются по оси Y. Эти координаты определяют продольные брусья.", "560 720", "277.55", "179")
        self.width_upper = QPushButton("Вдоль ширины")
        self.length_upper = QPushButton("Вдоль длины")
        self.layer_buttons = QButtonGroup(self)
        for button in (self.width_upper, self.length_upper):
            button.setCheckable(True)
            self.layer_buttons.addButton(button)
        self.width_upper.setChecked(True)
        self.view = PalletView(self)
        self.results = ResultsPanel()
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
        calculate_button = QPushButton("Рассчитать и построить")
        calculate_button.setObjectName("calculateButton")
        calculate_button.clicked.connect(self.calculate)
        calculate_button.setMinimumHeight(42)
        reset_button = QPushButton("Сбросить пример")
        reset_button.clicked.connect(self.reset_example)
        controls_layout.addWidget(calculate_button)
        controls_layout.addWidget(reset_button)
        controls_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls)
        splitter.addWidget(scroll)
        viewport = QWidget()
        viewport_layout = QVBoxLayout(viewport)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setSpacing(8)
        view_heading = QHBoxLayout()
        title_block = QVBoxLayout()
        view_title = QLabel("3D-модель поддона")
        view_title.setObjectName("paneTitle")
        title_block.addWidget(view_title)
        view_hint = QLabel("Вращайте мышью; колёсиком меняйте масштаб.")
        view_hint.setObjectName("paneHint")
        title_block.addWidget(view_hint)
        view_heading.addLayout(title_block)
        view_heading.addStretch()
        view_heading.addWidget(QLabel("Размеры в мм"))
        viewport_layout.addLayout(view_heading)
        camera_layout = QHBoxLayout()
        for label, handler in (
            ("Изометрия", self.view.camera_isometric),
            ("Сверху", self.view.camera_top),
            ("Спереди", self.view.camera_front),
            ("Сбоку", self.view.camera_side),
            ("Вписать модель", self.view.reset_camera),
        ):
            button = QPushButton(label)
            button.setObjectName("cameraButton")
            button.clicked.connect(handler)
            camera_layout.addWidget(button)
        camera_layout.addStretch()
        viewport_layout.addLayout(camera_layout)
        viewport_layout.addWidget(self.view)
        splitter.addWidget(viewport)
        splitter.setSizes([420, 980])
        root_layout.addWidget(splitter, 1)
        result_frame = QFrame()
        result_frame.setObjectName("resultsFrame")
        result_layout = QVBoxLayout(result_frame)
        result_layout.setContentsMargins(16, 14, 16, 14)
        result_layout.setSpacing(8)
        result_layout.addWidget(QLabel("Результаты расчёта"))
        result_layout.addWidget(self.results)
        root_layout.addWidget(result_frame, 0)
        self.setCentralWidget(root)
        self.length_panel.changed.connect(lambda: self._set_stale(True))
        self.width_panel.changed.connect(lambda: self._set_stale(True))
        self.layer_buttons.buttonClicked.connect(self._layer_changed)
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
            QFrame#appHeader, QFrame#resultsFrame, QFrame#layerCard, QGroupBox#directionCard {
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
            QPushButton { background: #fffdf9; border: 1px solid #d8d3c8; border-radius: 7px; padding: 8px 11px; color: #33464a; }
            QPushButton:hover { background: #f0ece3; border-color: #bcb5a7; }
            QPushButton:checked { background: #dfece9; border: 2px solid #4b7a76; color: #1f5c58; font-weight: 650; }
            QPushButton#calculateButton { background: #255e64; border: 1px solid #255e64; color: #ffffff; font-weight: 650; }
            QPushButton#calculateButton:hover { background: #1e4e53; }
            QPushButton#cameraButton { padding: 6px 9px; font-size: 12px; }
            QTextBrowser#resultCard { background: #f9f7f1; border: 1px solid #ece6dc; border-radius: 9px; padding: 4px 10px; }
            QLabel#resultSummary { color: #203b40; font-size: 18px; font-weight: 650; }
            QLabel#resultNote { color: #55706a; font-size: 12px; }
            QScrollArea { border: none; background: transparent; }
            QSplitter::handle { background: #e5dfd4; width: 1px; }
        """

    def _set_stale(self, stale: bool) -> None:
        self.results.set_stale(stale)
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

    def calculate(self) -> None:
        try:
            length = calculate_direction(self.length_panel.values())
            width = calculate_direction(self.width_panel.values())
            result = build_pallet(length, width, self.upper_layer())
        except CalculationError as exc:
            self._set_stale(True)
            QMessageBox.warning(self, "Невозможная геометрия", str(exc))
            return
        self.results.show_result(result)
        self.view.show_pallet(result)
        self._set_stale(False)

    def reset_example(self) -> None:
        self.length_panel.reset_example("1070 460 1300 499", 123, 552)
        self.width_panel.reset_example("560 720", 277.55, 179)
        self.width_upper.setChecked(True)
        self.calculate()

    def upper_layer(self) -> str:
        return "length" if self.length_upper.isChecked() else "width"


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("PalletLab")
    window = MainWindow()
    window.show()
    return app.exec_()
