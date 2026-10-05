"""Controller for pallet editing and rendering workflows."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QTimer

from palletlab.core.calculator import (
    build_pallet,
    calculate_direction,
    delete_beams_input,
    insert_beam_input,
    set_beam_face_distance_input,
)
from palletlab.core.models import DirectionInput, InsertionSlot, LayerDirection, PalletAxis, PalletResult
from palletlab.core.project_state import ProjectState, ToolMode
from palletlab.core.validation import CalculationError


class PalletController:
    """Own the workflows that turn UI actions into a rendered pallet project."""

    def __init__(
        self,
        state: ProjectState,
        view,
        *,
        on_calculated: Callable[[PalletResult], None],
        on_error: Callable[[CalculationError, bool], None],
        on_stale_changed: Callable[[bool], None],
        parent=None,
        timer=None,
    ) -> None:
        self.state = state
        self.view = view
        self._on_calculated = on_calculated
        self._on_error = on_error
        self._on_stale_changed = on_stale_changed
        self._automatic_rebuild: Callable[[], None] | None = None
        self._rebuild_timer = timer or QTimer(parent)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(300)
        self._rebuild_timer.timeout.connect(self._run_automatic_rebuild)

    def schedule_recalculation(self, rebuild: Callable[[], None]) -> None:
        """Debounce an automatic rebuild requested by a changing form field."""
        self._automatic_rebuild = rebuild
        self._on_stale_changed(True)
        self._rebuild_timer.start()

    def stop_scheduled_recalculation(self) -> None:
        self._rebuild_timer.stop()

    def calculate(
        self,
        length_input: DirectionInput,
        width_input: DirectionInput,
        upper_layer: LayerDirection,
        *,
        show_error: bool = True,
    ) -> PalletResult | None:
        """Calculate the project, update state and hand the model to the 3D view."""
        self.stop_scheduled_recalculation()
        self.state.length_input = length_input
        self.state.width_input = width_input
        self.state.upper_layer = upper_layer
        self.state.rounding_step = length_input.rounding_step if length_input.round_pallet_size else 0
        try:
            result = build_pallet(
                calculate_direction(length_input),
                calculate_direction(width_input),
                upper_layer,
            )
        except CalculationError as exc:
            self._on_stale_changed(True)
            self._on_error(exc, show_error)
            return None
        self.state.result = result
        self.view.show_pallet(
            result,
            show_length_gaps=self.state.show_length_dimensions,
            show_width_gaps=self.state.show_width_dimensions,
        )
        self._on_calculated(result)
        self._on_stale_changed(False)
        return result

    def recalculate_from_state(self, *, show_error: bool = True) -> PalletResult | None:
        """Rebuild after an interactive edit that already updated project state."""
        if self.state.length_input is None or self.state.width_input is None:
            return None
        return self.calculate(
            self.state.length_input,
            self.state.width_input,
            self.state.upper_layer,
            show_error=show_error,
        )

    def refresh_dimension_annotations(self, *, show_length: bool, show_width: bool) -> None:
        self.state.show_length_dimensions = show_length
        self.state.show_width_dimensions = show_width
        if self.state.result is not None:
            self.view.update_dimension_annotations(
                self.state.result,
                show_length_gaps=show_length,
                show_width_gaps=show_width,
            )

    def activate_tool(self, tool: ToolMode) -> None:
        self.state.active_tool = tool

    def deactivate_tool(self) -> None:
        self.state.active_tool = "none"

    def begin_insertion(self, slot: InsertionSlot) -> bool:
        if self.state.result is None:
            return False
        self.state.pending_insertion = slot
        return True

    def preview_insertion(self, clear_gap: float) -> None:
        if self.state.pending_insertion is None or self.state.result is None:
            return
        try:
            self.view.show_insertion_preview(self.state.result, self.state.pending_insertion, clear_gap)
        except CalculationError:
            self.view.clear_insertion_preview()

    def cancel_insertion(self) -> None:
        self.state.pending_insertion = None
        self.view.clear_insertion_selection()
        self.view.clear_insertion_preview()

    def confirm_insertion(self, clear_gap: float) -> tuple[PalletAxis, DirectionInput] | None:
        slot = self.state.pending_insertion
        result = self.state.result
        data = self.state.input_for(slot.axis) if slot else None
        if slot is None or result is None or data is None:
            return None
        direction = result.length_result if slot.axis == "length" else result.width_result
        try:
            updated = insert_beam_input(data, direction, slot.after_beam_index, clear_gap)
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        self.state.set_input(slot.axis, updated)
        self.state.pending_insertion = None
        return slot.axis, updated

    def begin_distance_edit(self, axis: PalletAxis, beam_index: int) -> None:
        self.state.pending_distance = (axis, beam_index)

    def cancel_distance_edit(self) -> None:
        self.state.pending_distance = None

    def confirm_distance_edit(self, face_distance: float) -> tuple[PalletAxis, DirectionInput] | None:
        pending = self.state.pending_distance
        result = self.state.result
        if pending is None or result is None:
            return None
        axis, beam_index = pending
        data = self.state.input_for(axis)
        if data is None:
            return None
        direction = result.length_result if axis == "length" else result.width_result
        try:
            updated = set_beam_face_distance_input(data, direction, beam_index, face_distance)
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        self.state.set_input(axis, updated)
        self.state.pending_distance = None
        return axis, updated

    def clear_deletion_selection(self) -> None:
        self.state.selected_for_deletion = {"length": set(), "width": set()}

    def set_deletion_selection(self, axis: PalletAxis, index: int, selected: bool) -> None:
        indices = self.state.selected_for_deletion[axis]
        if selected:
            indices.add(index)
        else:
            indices.discard(index)

    def confirm_deletion(self) -> dict[PalletAxis, DirectionInput] | None:
        result = self.state.result
        if result is None:
            return None
        updated_inputs: dict[PalletAxis, DirectionInput] = {}
        try:
            for axis, indices in self.state.selected_for_deletion.items():
                if not indices:
                    continue
                data = self.state.input_for(axis)
                if data is None:
                    continue
                direction = result.length_result if axis == "length" else result.width_result
                updated = delete_beams_input(data, direction, indices)
                self.state.set_input(axis, updated)
                updated_inputs[axis] = updated
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        return updated_inputs

    def _run_automatic_rebuild(self) -> None:
        if self._automatic_rebuild is not None:
            self._automatic_rebuild()
