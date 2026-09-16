"""Main desktop window for calculating and visualising a wooden pallet."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from palletlab.core.calculator import build_pallet, calculate_direction
from palletlab.core.validation import CalculationError
from palletlab.ui.input_panel import DirectionInputPanel
from palletlab.ui.results_panel import ResultsPanel
from palletlab.visualization.pallet_view import PalletView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PalletLab — калькулятор-визуализатор поддона")
        self.resize(1400, 900)
        self.length_panel = DirectionInputPanel("Длина — координаты брусьев по длине (X)", "1070 460 1300 499", "123", "552")
        self.width_panel = DirectionInputPanel("Ширина — координаты брусьев по ширине (Y)", "560 720", "277.55", "179")
        self.layer_combo = QComboBox()
        self.layer_combo.addItem("Вдоль ширины", "width")
        self.layer_combo.addItem("Вдоль длины", "length")
        self.view = PalletView(self)
        self.results = ResultsPanel()
        self._build_ui()
        self._set_stale(False)
        self.calculate()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        splitter = QSplitter(Qt.Horizontal)
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.addWidget(QLabel("<h2>Параметры</h2>"))
        controls_layout.addWidget(self.length_panel)
        controls_layout.addWidget(self.width_panel)
        controls_layout.addWidget(QLabel("Верхний слой"))
        controls_layout.addWidget(self.layer_combo)
        calculate_button = QPushButton("Рассчитать и построить")
        calculate_button.setObjectName("calculateButton")
        calculate_button.clicked.connect(self.calculate)
        reset_button = QPushButton("Сбросить пример")
        reset_button.clicked.connect(self.reset_example)
        controls_layout.addWidget(calculate_button)
        controls_layout.addWidget(reset_button)
        controls_layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(controls)
        splitter.addWidget(scroll)
        splitter.addWidget(self.view)
        splitter.setSizes([420, 980])
        root_layout.addWidget(splitter, 1)
        result_frame = QFrame()
        result_layout = QVBoxLayout(result_frame)
        result_layout.addWidget(QLabel("<h2>Результаты расчёта</h2>"))
        result_layout.addWidget(self.results)
        root_layout.addWidget(result_frame, 0)
        self.setCentralWidget(root)
        self.length_panel.changed.connect(lambda: self._set_stale(True))
        self.width_panel.changed.connect(lambda: self._set_stale(True))
        self.layer_combo.currentIndexChanged.connect(self._layer_changed)
        self.setStyleSheet("QGroupBox { font-weight: bold; margin-top: 10px; padding-top: 12px; }"
                           "QPushButton#calculateButton { background: #1d4ed8; color: white; font-weight: bold; padding: 8px; }")

    def _set_stale(self, stale: bool) -> None:
        self.results.setProperty("stale", stale)
        if stale:
            self.statusBar().showMessage("Параметры изменены — модель требует пересчёта.")
        else:
            self.statusBar().showMessage("Расчёт актуален.")

    def _layer_changed(self) -> None:
        # Layer change is an input change; rebuild only after a successful calculation.
        self._set_stale(True)

    def calculate(self) -> None:
        try:
            length = calculate_direction(self.length_panel.values())
            width = calculate_direction(self.width_panel.values())
            result = build_pallet(length, width, self.layer_combo.currentData())
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
        self.layer_combo.setCurrentIndex(0)
        self.calculate()


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("PalletLab")
    window = MainWindow()
    window.show()
    return app.exec_()
