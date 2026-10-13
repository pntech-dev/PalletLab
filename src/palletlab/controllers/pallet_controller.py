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
from palletlab.core.models import BeamSection, DirectionInput, InsertionSlot, LayerDirection, PalletAxis, PalletResult
from palletlab.core.persistence import ProjectPersistenceError, load_project, save_project
from palletlab.core.project_state import ProjectState, ToolMode
from palletlab.core.validation import CalculationError
from palletlab.controllers.viewport_geometry import editable_dimensions, insertion_markers, insertion_preview


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
        input_provider: Callable[[], tuple[DirectionInput, DirectionInput, LayerDirection]] | None = None,
        on_project_loaded: Callable[[ProjectState], None] | None = None,
        parent=None,
        timer=None,
    ) -> None:
        self.state = state
        self.view = view
        self._on_calculated = on_calculated
        self._on_error = on_error
        self._on_stale_changed = on_stale_changed
        self._input_provider = input_provider
        self._on_project_loaded = on_project_loaded
        self._rebuild_timer = timer or QTimer(parent)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(300)
        self._rebuild_timer.timeout.connect(self._run_automatic_rebuild)

    def schedule_recalculation(self) -> None:
        """Debounce an automatic rebuild requested by a changing form field."""
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
                self.state.beam_sections,
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

    def set_upper_layer(self, upper_layer: LayerDirection) -> None:
        self.state.upper_layer = upper_layer

    def set_rounding_step(self, rounding_step: int) -> None:
        self.state.rounding_step = rounding_step

    def save_project(self, path: str) -> bool:
        """Persist the stable project configuration for a future Save command."""
        try:
            save_project(path, self.state)
        except (OSError, ProjectPersistenceError) as exc:
            self._on_error(CalculationError(str(exc)), False)
            return False
        return True

    def open_project(self, path: str) -> PalletResult | None:
        """Load a saved configuration, synchronise the view and rebuild it."""
        try:
            loaded = load_project(path)
        except ProjectPersistenceError as exc:
            self._on_error(CalculationError(str(exc)), False)
            return None
        self.state.__dict__.update(loaded.__dict__)
        if self._on_project_loaded is not None:
            self._on_project_loaded(self.state)
        return self.recalculate_from_state()

    def activate_tool(self, tool: ToolMode) -> None:
        self.state.active_tool = tool

    def deactivate_tool(self) -> None:
        self.state.active_tool = "none"

    def begin_insertion(self, slot: InsertionSlot) -> bool:
        if self.state.result is None:
            return False
        self.state.pending_insertion = slot
        return True

    def enable_insertion_mode(self, slots: tuple[InsertionSlot, ...], callback) -> None:
        if self.state.result is not None:
            self.view.enable_insertion_mode(insertion_markers(self.state.result, slots), callback)

    def preview_insertion(self, clear_gap: float) -> None:
        if self.state.pending_insertion is None or self.state.result is None:
            return
        try:
            self.view.show_insertion_preview(insertion_preview(self.state.result, self.state.pending_insertion, clear_gap))
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
        self._clear_sections_for_axis(slot.axis)
        self.state.pending_insertion = None
        return slot.axis, updated

    def begin_distance_edit(self, axis: PalletAxis, beam_index: int) -> None:
        self.state.pending_distance = (axis, beam_index)

    def enable_distance_editing(self, callback) -> None:
        if self.state.result is not None:
            self.view.enable_distance_editing(editable_dimensions(self.state.result), callback)

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
        self._clear_sections_for_axis(axis)
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
                self._clear_sections_for_axis(axis)
                updated_inputs[axis] = updated
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        return updated_inputs

    def clear_section_selection(self) -> None:
        self.state.selected_for_section = {"length": set(), "width": set()}

    def set_section_selection(self, axis: PalletAxis, index: int, selected: bool) -> None:
        indices = self.state.selected_for_section[axis]
        if selected:
            indices.add(index)
        else:
            indices.discard(index)

    def apply_section_change(self, section: BeamSection) -> PalletResult | None:
        """Apply a section to selected beams, preserving the old pallet on error."""
        selected = [
            (axis, index)
            for axis, indices in self.state.selected_for_section.items()
            for index in indices
        ]
        if not selected:
            return None
        previous = self.state.beam_sections.copy()
        self.state.beam_sections.update({key: section for key in selected})
        result = self.recalculate_from_state()
        if result is None:
            self.state.beam_sections = previous
        return result

    def _clear_sections_for_axis(self, axis: PalletAxis) -> None:
        """Geometry edits renumber beam indices, so stale overrides must not move."""
        self.state.beam_sections = {
            key: section for key, section in self.state.beam_sections.items() if key[0] != axis
        }

    def _run_automatic_rebuild(self) -> None:
        if self._input_provider is None:
            return
        try:
            length_input, width_input, upper_layer = self._input_provider()
        except CalculationError as exc:
            self._on_stale_changed(True)
            self._on_error(exc, False)
            return
        self.calculate(length_input, width_input, upper_layer, show_error=False)
