"""Formatted text presentation of calculations."""

from __future__ import annotations

from PyQt5.QtWidgets import QTextEdit

from palletlab.core.models import DirectionResult, PalletResult


def format_mm(value: float) -> str:
    """Show stable, human-friendly millimetres without floating point noise."""
    rounded = round(value, 2)
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


class ResultsPanel(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText("Нажмите «Рассчитать и построить», чтобы увидеть результаты.")

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
            f"Опор: <b>{result.support_count}</b>; брусьев: <b>{result.beam_count}</b>"
            f"<p>Чистые расстояния между гранями:</p><ul>{gaps}</ul>"
        )

    def show_result(self, result: PalletResult) -> None:
        self.setHtml(
            f"<h2>Поддон: {format_mm(result.pallet_length)} × {format_mm(result.pallet_width)} × "
            f"{format_mm(result.pallet_height)} мм</h2>"
            + self._direction_html("Длина", result.length_result)
            + self._direction_html("Ширина", result.width_result)
        )

