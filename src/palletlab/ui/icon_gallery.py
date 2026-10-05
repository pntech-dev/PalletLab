"""Standalone gallery for reviewing UI icon assets before product integration."""

from __future__ import annotations

from pathlib import Path
import sys

# Allow `python src/palletlab/ui/icon_gallery.py` during design-system work.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer, QSvgWidget
from PyQt5.QtWidgets import QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QScrollArea, QVBoxLayout, QWidget

from palletlab.ui.design_components import (DesignCheckBox, DesignComboBox, DesignInputField, DesignRadioButton,
                                            DesignSegmentedControl)

ICON_NAMES = (
    "check",
    "chevron-down",
    "chevron-up",
    "cross",
    "info",
    "inscribe",
    "maximize-2",
    "minimize-2",
    "minus",
    "mouse-left",
    "mouse-right",
    "mouse",
    "plus",
    "size",
    "size-x",
    "size-y",
    "size-z",
    "trash",
    "warning",
)


class IconPreview(QLabel):
    """An SVG preview recoloured by its owner rather than by the SVG file itself."""

    def __init__(self, icon_name: str, color: QColor, size: int = 24) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setPixmap(self._coloured_pixmap(icon_name, color, size))

    @staticmethod
    def _coloured_pixmap(icon_name: str, color: QColor, size: int) -> QPixmap:
        source = QPixmap(size, size)
        source.fill(Qt.transparent)
        asset_path = Path(__file__).parent / "assets" / "icons" / f"{icon_name}.svg"
        renderer = QSvgRenderer(str(asset_path))
        painter = QPainter(source)
        renderer.render(painter)
        painter.end()

        coloured = QPixmap(size, size)
        coloured.fill(Qt.transparent)
        painter = QPainter(coloured)
        painter.drawPixmap(0, 0, source)
        painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
        painter.fillRect(coloured.rect(), color)
        painter.end()
        return coloured


class IconGalleryWindow(QMainWindow):
    """A disposable visual test surface for the imported icon collection."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PalletLab — иконки нового интерфейса")
        self.setMinimumSize(720, 960)
        self.resize(960, 1040)

        root = QWidget()
        root.setObjectName("iconGalleryRoot")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Логотип и иконки")
        title.setObjectName("iconGalleryTitle")
        layout.addWidget(title)
        description = QLabel(
            "Тестовая поверхность для проверки брендового логотипа и SVG-иконок. "
            "Цвет иконки задаётся компонентом, а не файлом иконки."
        )
        description.setObjectName("iconGalleryDescription")
        description.setWordWrap(True)
        layout.addWidget(description)
        layout.addWidget(self._logo_card())
        layout.addWidget(self._components_card())

        strip = QWidget()
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(12)
        for name in ICON_NAMES:
            strip_layout.addWidget(self._icon_card(name))
        strip_layout.addStretch()
        scroll = QScrollArea()
        scroll.setObjectName("iconGalleryScroll")
        scroll.setWidget(strip)
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(140)
        layout.addWidget(scroll)
        layout.addStretch()
        self.setCentralWidget(root)
        self.setStyleSheet(self._stylesheet())

    @staticmethod
    def _logo_card() -> QFrame:
        card = QFrame()
        card.setObjectName("logoCard")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(20)
        logo = QSvgWidget(str(Path(__file__).parent / "assets" / "brand" / "logo.svg"))
        logo.setFixedSize(249, 48)
        layout.addWidget(logo)
        caption = QLabel("Логотип · исходный размер 166 × 32 px")
        caption.setObjectName("logoCaption")
        layout.addWidget(caption)
        layout.addStretch()
        return card

    @staticmethod
    def _components_card() -> QFrame:
        card = QFrame()
        card.setObjectName("componentsCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(24)
        top_row = QHBoxLayout()
        top_row.setSpacing(48)

        checkbox_column = QVBoxLayout()
        checkbox_column.setSpacing(12)
        checkbox_column.addWidget(IconGalleryWindow._section_title("Checkbox"))
        default_checkbox = DesignCheckBox("Размеры по длине")
        checkbox_column.addWidget(default_checkbox)
        checked_checkbox = DesignCheckBox("Размеры по ширине")
        checked_checkbox.setChecked(True)
        checkbox_column.addWidget(checked_checkbox)
        disabled_checkbox = DesignCheckBox("Недоступно")
        disabled_checkbox.setEnabled(False)
        checkbox_column.addWidget(disabled_checkbox)
        disabled_checked_checkbox = DesignCheckBox("Выбрано и недоступно")
        disabled_checked_checkbox.setChecked(True)
        disabled_checked_checkbox.setEnabled(False)
        checkbox_column.addWidget(disabled_checked_checkbox)
        top_row.addLayout(checkbox_column)

        combo_column = QVBoxLayout()
        combo_column.setSpacing(12)
        combo_column.addWidget(IconGalleryWindow._section_title("Combobox"))
        combo_column.addWidget(DesignComboBox("Размер", ("70×50 мм", "100×25 мм", "120×40 мм", "150×50 мм")))
        disabled_combo = DesignComboBox("Размер", ("70×50 мм",))
        disabled_combo.setEnabled(False)
        combo_column.addWidget(disabled_combo)
        top_row.addLayout(combo_column)
        top_row.addStretch()
        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(48)
        radio_column = QVBoxLayout()
        radio_column.setSpacing(12)
        radio_column.addWidget(IconGalleryWindow._section_title("Radio button"))
        radio_default = DesignRadioButton("Не округлять")
        radio_column.addWidget(radio_default)
        radio_selected = DesignRadioButton("До 50 мм")
        radio_selected.setChecked(True)
        radio_column.addWidget(radio_selected)
        radio_disabled = DesignRadioButton("Недоступно")
        radio_disabled.setEnabled(False)
        radio_column.addWidget(radio_disabled)
        radio_selected_disabled = DesignRadioButton("Выбрано и недоступно")
        radio_selected_disabled.setChecked(True)
        radio_selected_disabled.setEnabled(False)
        radio_column.addWidget(radio_selected_disabled)
        bottom_row.addLayout(radio_column)

        segments_column = QVBoxLayout()
        segments_column.setSpacing(12)
        segments_column.addWidget(IconGalleryWindow._section_title("Segmented control"))
        segments_column.addWidget(
            DesignSegmentedControl(("Вариант 1", "Вариант 2", "Недоступно"), disabled_indices=(2,))
        )
        bottom_row.addLayout(segments_column)
        bottom_row.addStretch()
        layout.addLayout(bottom_row)

        inputs_column = QVBoxLayout()
        inputs_column.setSpacing(12)
        inputs_column.addWidget(IconGalleryWindow._section_title("Input field"))
        inputs_grid = QGridLayout()
        inputs_grid.setHorizontalSpacing(24)
        inputs_grid.setVerticalSpacing(16)
        interactive_input = DesignInputField("Размер")
        interactive_input.setToolTip("Введите 1234, чтобы увидеть состояние Error.")
        inputs_grid.addWidget(interactive_input, 0, 0)
        disabled_empty_input = DesignInputField("Размер")
        disabled_empty_input.setEnabled(False)
        inputs_grid.addWidget(disabled_empty_input, 0, 1)
        disabled_filled_input = DesignInputField("Размер", value="70×50 мм")
        disabled_filled_input.setEnabled(False)
        inputs_grid.addWidget(disabled_filled_input, 1, 0)
        inputs_column.addLayout(inputs_grid)
        layout.addLayout(inputs_column)
        return card

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("componentsTitle")
        return label

    @staticmethod
    def _icon_card(name: str) -> QFrame:
        card = QFrame()
        card.setObjectName("iconCard")
        card.setFixedSize(116, 116)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        icon = IconPreview(name, QColor("#263238"))
        layout.addWidget(icon, alignment=Qt.AlignHCenter)
        label = QLabel(name)
        label.setObjectName("iconName")
        label.setAlignment(Qt.AlignHCenter)
        label.setWordWrap(True)
        layout.addWidget(label)
        return card

    @staticmethod
    def _stylesheet() -> str:
        return """
            QWidget#iconGalleryRoot { background: #f7f7f8; color: #1d1d20; font-family: 'Segoe UI'; font-size: 14px; }
            QLabel#iconGalleryTitle { font-size: 20px; font-weight: 700; }
            QLabel#iconGalleryDescription { color: #62636a; }
            QFrame#iconCard { background: #ffffff; border: 1px solid #dedee3; border-radius: 8px; }
            QFrame#iconCard:hover { background: #f3f4f7; border-color: #aeb1b8; }
            QLabel#iconName { color: #44464d; font-size: 14px; }
            QFrame#logoCard { background: #ffffff; border: 1px solid #dedee3; border-radius: 8px; }
            QLabel#logoCaption { color: #62636a; font-size: 14px; }
            QFrame#componentsCard { background: #ffffff; border: 1px solid #dedee3; border-radius: 8px; }
            QLabel#componentsTitle { color: #0a0a0a; font-size: 18px; font-weight: 700; }
            QScrollArea#iconGalleryScroll { border: none; background: transparent; }
            QScrollBar:horizontal { height: 8px; background: #e5e5e9; border-radius: 4px; }
            QScrollBar::handle:horizontal { min-width: 32px; background: #aeb1b8; border-radius: 4px; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        """


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("PalletLab Icon Gallery")
    window = IconGalleryWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(run())
