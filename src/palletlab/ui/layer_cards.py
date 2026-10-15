"""Lifetime-safe renderer for the editable stack of pallet layers."""

from __future__ import annotations

from functools import partial
from typing import Callable, Mapping, Sequence

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from palletlab.core.models import PalletAxis
from palletlab.ui.input_panel import DirectionInputPanel


class LayerCardManager:
    """Own transient card widgets while the actual input panels are retained.

    A panel represents model input and survives a reorder.  A card only
    represents its current place in the list and is therefore always disposed
    through ``deleteLater``.  Keeping those lifetimes separate avoids a queued
    Qt signal operating on a card left over from an earlier rebuild.
    """

    def __init__(
        self,
        layout: QVBoxLayout,
        *,
        description: Callable[[PalletAxis], str],
        on_move: Callable[[str, int], None],
        on_remove: Callable[[str], None],
        on_add: Callable[[], None],
    ) -> None:
        self._layout = layout
        self._description = description
        self._on_move = on_move
        self._on_remove = on_remove
        self._on_add = on_add
        self._cards: list[tuple[QFrame, DirectionInputPanel]] = []

    def rebuild(
        self,
        order: Sequence[str],
        axes: Mapping[str, PalletAxis],
        panels: Mapping[str, DirectionInputPanel],
    ) -> None:
        self._dispose_cards()
        for position, layer_id in enumerate(order):
            axis = axes[layer_id]
            panel = panels[layer_id]
            panel.setTitle(f"{position + 1:02d}  Слой · {'длина' if axis == 'length' else 'ширина'}")
            card = QFrame()
            card.setObjectName("layerCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 6, 8, 8)
            header = QHBoxLayout()
            direction = "по длине" if axis == "length" else "по ширине"
            header.addWidget(QLabel(f"Слой {position + 1} · {direction}"), 1)
            up = QPushButton("↑")
            up.setToolTip("Поднять слой")
            up.setEnabled(position > 0)
            up.clicked.connect(partial(self._on_move, layer_id, -1))
            header.addWidget(up)
            down = QPushButton("↓")
            down.setToolTip("Опустить слой")
            down.setEnabled(position < len(order) - 1)
            down.clicked.connect(partial(self._on_move, layer_id, 1))
            header.addWidget(down)
            remove = QPushButton("×")
            remove.setToolTip("Удалить слой")
            remove.setEnabled(len(order) > 2)
            remove.clicked.connect(partial(self._on_remove, layer_id))
            header.addWidget(remove)
            card_layout.addLayout(header)
            card_layout.addWidget(panel)
            self._layout.addWidget(card)
            self._cards.append((card, panel))
        add = QPushButton("＋ Добавить слой")
        add.setObjectName("addLayerButton")
        add.clicked.connect(self._on_add)
        self._layout.addWidget(add)

    def detach_panel(self, panel: QWidget) -> None:
        """Detach an editor before its current card is deleted."""
        panel.setParent(None)
        panel.hide()

    def _dispose_cards(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget not in (card for card, _panel in self._cards):
                widget.deleteLater()
        for card, panel in self._cards:
            panel.setParent(None)
            card.hide()
            card.deleteLater()
        self._cards.clear()
