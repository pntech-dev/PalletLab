"""Formatted text presentation of calculations."""

from __future__ import annotations

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from palletlab.core.models import DirectionResult, PalletResult


def format_mm(value: float) -> str:
    """Show stable, human-friendly millimetres without floating point noise."""
    rounded = round(value, 2)
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


class ResultsPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("resultsPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.summary = QLabel("Выполните расчёт, чтобы увидеть габарит поддона")
        self.summary.setObjectName("resultSummary")
        layout.addWidget(self.summary)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.length_card = self._card()
        self.width_card = self._card()
        cards.addWidget(self.length_card, 1)
        cards.addWidget(self.width_card, 1)
        layout.addLayout(cards)
        self.note = QLabel("")
        self.note.setObjectName("resultNote")
        layout.addWidget(self.note)

    @staticmethod
    def _card() -> QTextBrowser:
        card = QTextBrowser()
        card.setObjectName("resultCard")
        card.setOpenExternalLinks(False)
        card.setFrameShape(QFrame.NoFrame)
        return card

    @staticmethod
    def _direction_html(title: str, result: DirectionResult) -> str:
        gaps = "".join(
            f"<li>Брус {index + 1} → Брус {index + 2}: <b>{format_mm(gap)} мм</b></li>"
            for index, gap in enumerate(result.gaps)
        )
        return (
            f"<h3>{title}</h3>"
            f"Габарит оборудования: <b>{format_mm(result.machine_size)} мм</b><br>"
            f"Габарит поддона: <b>{format_mm(result.pallet_size)} мм</b><br>"
            f"Опор: <b>{result.support_count}</b> · Брусьев: <b>{result.beam_count}</b>"
            f"<p>Чистые расстояния между гранями:</p><ul>{gaps}</ul>"
        )

    def show_result(self, result: PalletResult) -> None:
        self.summary.setText(
            f"Поддон  ·  {format_mm(result.pallet_length)} × {format_mm(result.pallet_width)} × "
            f"{format_mm(result.pallet_height)} мм"
        )
        self.length_card.setHtml(self._direction_html("01  Расчёт по длине", result.length_result))
        self.width_card.setHtml(self._direction_html("02  Расчёт по ширине", result.width_result))
        self.note.setText("Расчёт сходится: сумма чистых промежутков и ширин брусьев равна габариту поддона.")

    def set_stale(self, stale: bool) -> None:
        if stale:
            self.note.setText("Параметры изменены. Нажмите «Рассчитать и построить», чтобы обновить результат и 3D-модель.")
