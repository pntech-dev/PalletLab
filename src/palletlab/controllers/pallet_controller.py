"""Controller for pallet editing and rendering workflows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from math import copysign, isfinite

from PyQt5.QtCore import QTimer

from palletlab.core.calculator import (
    build_pallet,
    build_multilayer_pallet,
    calculate_direction,
    delete_beams_input,
    insert_beam_input,
    set_beam_face_distance_input,
)
from palletlab.core.models import Beam3D, BeamSection, DirectionInput, DirectionResult, InsertionSlot, LayerBeamKey, LayerDefinition, LayerDirection, LayerInput, ManualBeamInput, PalletAxis, PalletResult
from palletlab.core.persistence import ProjectPersistenceError, load_project, save_project
from palletlab.core.project_state import ProjectState, ToolMode
from palletlab.core.validation import CalculationError
from palletlab.controllers.viewport_geometry import editable_dimensions, insertion_markers, insertion_preview


@dataclass(frozen=True)
class DeletionTarget:
    """One physical beam frozen at the moment the user selected it."""

    layer_id: str
    index: int
    beam: Beam3D


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
        # A single timer is reused for form edits.  The revision makes an
        # already queued timeout harmless after a newer edit or project load.
        self._rebuild_revision = 0
        self._scheduled_revision: int | None = None
        self._rebuild_timer = timer or QTimer(parent)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(300)
        self._rebuild_timer.timeout.connect(self._run_automatic_rebuild)
        self._deletion_targets: dict[tuple[str, int], DeletionTarget] = {}

    def schedule_recalculation(self) -> None:
        """Debounce an automatic rebuild requested by a changing form field."""
        self._rebuild_revision += 1
        self._scheduled_revision = self._rebuild_revision
        self._on_stale_changed(True)
        self._rebuild_timer.start()

    def stop_scheduled_recalculation(self) -> None:
        self._rebuild_timer.stop()
        self._scheduled_revision = None

    def invalidate_scheduled_recalculation(self) -> None:
        """Cancel pending automatic work before an explicit state transition."""
        self._rebuild_revision += 1
        self.stop_scheduled_recalculation()

    def calculate(
        self,
        length_input: DirectionInput,
        width_input: DirectionInput,
        upper_layer: LayerDirection,
        *,
        show_error: bool = True,
    ) -> PalletResult | None:
        """Calculate the project, update state and hand the model to the 3D view."""
        self.invalidate_scheduled_recalculation()
        ordered = (("length", length_input), ("width", width_input)) if upper_layer == "width" else (("width", width_input), ("length", length_input))
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
        result = self._with_manual_beams(result)
        # Apply only a fully calculated candidate.  A failed calculation must
        # leave both the current scene and the editable project untouched.
        self.state.length_input = length_input
        self.state.width_input = width_input
        self.state.upper_layer = upper_layer
        self.state.rounding_step = length_input.rounding_step if length_input.round_pallet_size else 0
        self.state.multi_layer_mode = False
        self.state.layers = [LayerInput(axis, axis, direction) for axis, direction in ordered]
        self.state.layer_sections = {(axis, index): section for (axis, index), section in self.state.beam_sections.items()}
        self.state.result = result
        self._show_result(result)
        self._on_calculated(result)
        self._on_stale_changed(False)
        return result

    def calculate_layers(self, layers: list[LayerInput], *, show_error: bool = True) -> PalletResult | None:
        """Calculate a bottom-to-top layer stack without relying on the two-panel UI."""
        self.invalidate_scheduled_recalculation()
        # The first added layer switches a project from the legacy two-layer
        # representation to the generic stack.  Preserve any cross-sections
        # changed before that switch by assigning their established axis ids
        # (``length`` and ``width``) to the matching initial layers.
        candidate_sections = self.state.layer_sections.copy()
        if not self.state.multi_layer_mode and self.state.beam_sections:
            layer_ids = {layer.layer_id for layer in layers}
            candidate_sections.update({
                (axis, index): section
                for (axis, index), section in self.state.beam_sections.items()
                if axis in layer_ids
            })
        try:
            definitions = []
            for layer in layers:
                direction = calculate_direction(layer.direction)
                sections = tuple(
                    candidate_sections[(layer.layer_id, index)]
                    if (layer.layer_id, index) in candidate_sections
                    else BeamSection(direction.beam_height, direction.beam_width)
                    for index in range(len(direction.beam_centers))
                )
                definitions.append(LayerDefinition(layer.layer_id, layer.axis, direction, sections))
            result = build_multilayer_pallet(definitions)
        except CalculationError as exc:
            self._on_stale_changed(True)
            self._on_error(exc, show_error)
            return None
        self.state.set_layers(layers)
        self.state.layer_sections = candidate_sections
        # Keep representative legacy values populated until the two-panel UI
        # is replaced.  Persistence and existing exporters still read them.
        self.state.length_input = next(layer.direction for layer in layers if layer.axis == "length")
        self.state.width_input = next(layer.direction for layer in layers if layer.axis == "width")
        self.state.upper_layer = layers[-1].axis
        self.state.rounding_step = (
            self.state.length_input.rounding_step if self.state.length_input.round_pallet_size else 0
        )
        self.state.multi_layer_mode = True
        result = self._with_manual_beams(result)
        self.state.result = result
        self._show_result(result)
        self._on_calculated(result)
        self._on_stale_changed(False)
        return result

    def recalculate_from_state(self, *, show_error: bool = True) -> PalletResult | None:
        """Rebuild after an interactive edit that already updated project state."""
        if self.state.multi_layer_mode:
            return self.calculate_layers(self.state.layers, show_error=show_error)
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
            kwargs = {
                "show_length_gaps": show_length,
                "show_width_gaps": show_width,
            }
            if self.state.manual_beams:
                kwargs["dimensions"] = editable_dimensions(self.state.result, tuple(self.state.manual_beams))
            self.view.update_dimension_annotations(self.state.result, **kwargs)

    def _show_result(self, result: PalletResult) -> None:
        kwargs = {
            "show_length_gaps": self.state.show_length_dimensions,
            "show_width_gaps": self.state.show_width_dimensions,
        }
        if self.state.manual_beams:
            kwargs["dimensions"] = editable_dimensions(result, tuple(self.state.manual_beams))
        self.view.show_pallet(result, **kwargs)

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
        previous = self.state.__dict__.copy()
        self.invalidate_scheduled_recalculation()
        self.state.__dict__.update(loaded.__dict__)
        if self._on_project_loaded is not None:
            self._on_project_loaded(self.state)
        result = self.recalculate_from_state()
        if result is None:
            self.state.__dict__.update(previous)
            # The loaded controls were already applied before the geometry
            # check.  Restore them together with the state so form fields can
            # never describe a project that failed to open.
            if self._on_project_loaded is not None:
                self._on_project_loaded(self.state)
            if self.state.result is not None:
                self._show_result(self.state.result)
        return result

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

    def confirm_insertion(self, clear_gap: float) -> tuple[str, DirectionInput] | None:
        slot = self.state.pending_insertion
        result = self.state.result
        layer_id = (slot.layer_id or slot.axis) if slot else ""
        layer = self._layer_for(layer_id)
        data = layer.direction if layer is not None else (self.state.input_for(slot.axis) if slot else None)
        if slot is None or result is None or data is None:
            return None
        direction = calculate_direction(data)
        try:
            updated = insert_beam_input(data, direction, slot.after_beam_index, clear_gap)
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        self._replace_layer_input(layer_id, updated)
        self._shift_sections_after_insertion(layer_id, slot.after_beam_index)
        self._shift_manual_supports_after_insertion(layer_id, slot.after_beam_index)
        self.state.pending_insertion = None
        return layer_id, updated

    def begin_distance_edit(self, layer_id: str, beam_index: int) -> None:
        self.state.pending_distance = (layer_id, beam_index)

    def enable_distance_editing(self, callback) -> None:
        if self.state.result is not None:
            self.view.enable_distance_editing(
                tuple(dimension for dimension in editable_dimensions(self.state.result, tuple(self.state.manual_beams))
                      if dimension.editable),
                callback,
            )

    def cancel_distance_edit(self) -> None:
        self.state.pending_distance = None

    def confirm_distance_edit(self, face_distance: float) -> tuple[str, DirectionInput | None] | None:
        pending = self.state.pending_distance
        result = self.state.result
        if pending is None or result is None:
            return None
        layer_id, beam_index = pending
        manual_index = next(
            (index for index, beam in enumerate(self.state.manual_beams) if beam.beam_id == layer_id), None,
        )
        if manual_index is not None:
            if not isfinite(face_distance):
                self._on_error(CalculationError("Расстояние должно быть конечным числом."), False)
                return None
            manual = self.state.manual_beams[manual_index]
            self.state.manual_beams[manual_index] = replace(manual, distance=face_distance)
            self.state.pending_distance = None
            return layer_id, None
        if layer_id.startswith("pallet-"):
            axis: PalletAxis = "length" if layer_id == "pallet-length" else "width"
            layer = next((candidate for candidate in reversed(self.state.layers) if candidate.axis == axis), None)
            if layer is None:
                self._on_error(CalculationError("Не найден слой для изменения общего габарита."), False)
                return None
            layer_id = layer.layer_id
            beam_index = len(calculate_direction(layer.direction).beam_centers) - 1
        layer = self._layer_for(layer_id)
        data = layer.direction if layer is not None else self.state.input_for(layer_id)  # type: ignore[arg-type]
        if data is None:
            return None
        direction = calculate_direction(data)
        try:
            updated = set_beam_face_distance_input(data, direction, beam_index, face_distance)
            # ``set_beam_face_distance_input`` changes a cumulative value into
            # several support spacings.  A positive cumulative value may still
            # put two support centres at one point.  Validate the complete
            # candidate before it reaches ProjectState, otherwise every later
            # operation (including a section change) would fail on that stale
            # zero spacing.
            calculate_direction(updated)
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        try:
            self._replace_distance_layer_inputs(layer_id, updated)
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        self.state.pending_distance = None
        return layer_id, updated

    def _replace_distance_layer_inputs(self, layer_id: str, updated: DirectionInput) -> None:
        """Keep every same-axis layer on the edited pallet envelope.

        A stack may have several length (or width) layers.  Changing its final
        dimension changes the envelope, so leaving the parallel layers at the
        old size would make the next rebuild impossible.
        """
        layer = self._layer_for(layer_id)
        if layer is None or not self.state.multi_layer_mode:
            self._replace_layer_input(layer_id, updated)
            return
        target_raw_size = calculate_direction(updated).raw_pallet_size
        replacements = {layer_id: updated}
        for peer in self.state.layers:
            if peer.layer_id == layer_id or peer.axis != layer.axis:
                continue
            peer_direction = calculate_direction(peer.direction)
            synchronized = replace(
                peer.direction,
                margin_end=peer.direction.margin_end + target_raw_size - peer_direction.raw_pallet_size,
            )
            calculate_direction(synchronized)
            replacements[peer.layer_id] = synchronized
        for identifier, data in replacements.items():
            self._replace_layer_input(identifier, data)

    def clear_deletion_selection(self) -> None:
        self.state.selected_for_deletion = {"length": set(), "width": set()}
        self._deletion_targets.clear()

    def set_deletion_selection(self, layer_id: str, index: int, selected: bool) -> bool:
        """Toggle exactly one rendered beam, rejecting stale actor identities."""
        key = (layer_id, index)
        current = self._beam_for_deletion(layer_id, index)
        if selected and current is None:
            self._on_error(CalculationError("Выбранный брус больше не существует. Обновите выделение."), False)
            return False
        indices = self.state.selected_for_deletion.setdefault(layer_id, set())
        if selected:
            indices.add(index)
            self._deletion_targets[key] = DeletionTarget(layer_id, index, current)
        else:
            indices.discard(index)
            self._deletion_targets.pop(key, None)
        return True

    def _beam_for_deletion(self, layer_id: str, index: int) -> Beam3D | None:
        result = self.state.result
        if result is None:
            return None
        return next((beam for beam in result.beams_3d
                     if (beam.layer_id or beam.orientation) == layer_id and beam.layer_index == index), None)

    def confirm_deletion(self) -> dict[str, DirectionInput] | None:
        """Apply one frozen deletion selection as an all-or-nothing change."""
        result = self.state.result
        targets = tuple(self._deletion_targets.values())
        if result is None or not targets:
            return None
        # A view rebuild can replace beam indices between a click and the
        # confirmation.  Never reinterpret a target by a new index: cancel
        # instead of risking deletion of its neighbour.
        if any(self._beam_for_deletion(item.layer_id, item.index) != item.beam for item in targets):
            self._on_error(CalculationError("Модель изменилась после выделения. Выберите брусья заново."), False)
            self.clear_deletion_selection()
            return None
        updated_inputs: dict[str, DirectionInput] = {}
        original_directions: dict[str, DirectionResult] = {}
        manual_ids = {beam.beam_id for beam in self.state.manual_beams}
        selected_manual = {
            item.layer_id for item in targets
            if item.layer_id in manual_ids and item.index == 0
        }
        selected_by_layer: dict[str, set[int]] = {}
        for item in targets:
            if item.layer_id not in manual_ids:
                selected_by_layer.setdefault(item.layer_id, set()).add(item.index)
        removed_supports = {
            (layer_id, index)
            for layer_id, indices in selected_by_layer.items()
            for index in indices
        } | {(beam_id, 0) for beam_id in selected_manual}
        dependent_manual = self._manual_beams_using_supports(removed_supports, ignored_ids=selected_manual)
        if dependent_manual:
            self._on_error(
                CalculationError(
                    "Нельзя удалить опору, пока на неё опираются ручные брусья: "
                    + ", ".join(sorted(dependent_manual))
                    + ". Сначала удалите или измените эти брусья."
                ),
                False,
            )
            return None
        try:
            for layer_id, indices in selected_by_layer.items():
                layer = self._layer_for(layer_id)
                if layer is None and layer_id not in ("length", "width"):
                    raise CalculationError("Выбранный слой больше не существует.")
                data = layer.direction if layer is not None else self.state.input_for(layer_id)  # type: ignore[arg-type]
                if data is None:
                    raise CalculationError("Выбранный слой больше не существует.")
                direction = calculate_direction(data)
                updated = delete_beams_input(data, direction, indices)
                updated_inputs[layer_id] = updated
                original_directions[layer_id] = direction
        except CalculationError as exc:
            self._on_error(exc, False)
            return None
        # All selected inputs have been validated above.  Only now mutate the
        # model, so a stale selection in one layer cannot partly delete beams
        # from another one.
        if selected_manual:
            self.state.manual_beams = [
                beam for beam in self.state.manual_beams if beam.beam_id not in selected_manual
            ]
        for layer_id, updated in updated_inputs.items():
            selected = selected_by_layer[layer_id]
            self._replace_layer_input(layer_id, updated)
            direction = original_directions[layer_id]
            internal_indices = {index for index in selected if 0 < index < len(direction.beam_centers) - 1}
            self._reindex_sections_after_deletion(layer_id, internal_indices)
            self._reindex_manual_supports_after_deletion(layer_id, internal_indices)
        self.clear_deletion_selection()
        return updated_inputs

    def clear_section_selection(self) -> None:
        self.state.selected_for_section = {"length": set(), "width": set()}

    def set_section_selection(self, layer_id: str, index: int, selected: bool) -> None:
        indices = self.state.selected_for_section.setdefault(layer_id, set())
        if selected:
            indices.add(index)
        else:
            indices.discard(index)

    def apply_section_change(self, section: BeamSection) -> PalletResult | None:
        """Apply a section to selected beams, preserving the old pallet on error."""
        selected = [
            (layer_id, index)
            for layer_id, indices in self.state.selected_for_section.items()
            for index in indices
        ]
        if not selected:
            return None
        manual_ids = {beam.beam_id for beam in self.state.manual_beams}
        selected_manual = {layer_id for layer_id, index in selected if layer_id in manual_ids and index == 0}
        selected = [(layer_id, index) for layer_id, index in selected if layer_id not in manual_ids]
        previous_manual = self.state.manual_beams.copy()
        if selected_manual:
            self.state.manual_beams = [
                replace(beam, section=section) if beam.beam_id in selected_manual else beam
                for beam in self.state.manual_beams
            ]
        if not selected:
            result = self.recalculate_from_state()
            if result is None:
                self.state.manual_beams = previous_manual
            return result
        previous = self.state.layer_sections.copy() if self.state.multi_layer_mode else self.state.beam_sections.copy()
        if self.state.multi_layer_mode:
            self.state.layer_sections.update({key: section for key in selected})
        else:
            self.state.beam_sections.update({key: section for key in selected})
        result = self.recalculate_from_state()
        if result is None:
            self.state.manual_beams = previous_manual
            if self.state.multi_layer_mode:
                self.state.layer_sections = previous
            else:
                self.state.beam_sections = previous
        return result

    def _layer_for(self, layer_id: str) -> LayerInput | None:
        return next((layer for layer in self.state.layers if layer.layer_id == layer_id), None)

    def _replace_layer_input(self, layer_id: str, data: DirectionInput) -> None:
        self.state.layers = [
            LayerInput(layer.layer_id, layer.axis, data if layer.layer_id == layer_id else layer.direction)
            for layer in self.state.layers
        ]
        if layer_id in ("length", "width"):
            self.state.set_input(layer_id, data)  # type: ignore[arg-type]

    def _clear_sections_for_layer(self, layer_id: str) -> None:
        if self.state.multi_layer_mode:
            self.state.layer_sections = {
                key: section for key, section in self.state.layer_sections.items() if key[0] != layer_id
            }
        else:
            self._clear_sections_for_axis(layer_id)  # type: ignore[arg-type]

    def _shift_sections_after_insertion(self, layer_id: str, after_index: int) -> None:
        """Keep overrides on existing beams when a new beam shifts their indices."""
        sections = self.state.layer_sections if self.state.multi_layer_mode else self.state.beam_sections
        moved = {
            (key_layer, index + 1 if key_layer == layer_id and index > after_index else index): section
            for (key_layer, index), section in sections.items()
        }
        if self.state.multi_layer_mode:
            self.state.layer_sections = moved
        else:
            self.state.beam_sections = moved

    def _reindex_sections_after_deletion(self, layer_id: str, indices: set[int]) -> None:
        """Drop removed overrides and move following overrides to their new beam indices."""
        sections = self.state.layer_sections if self.state.multi_layer_mode else self.state.beam_sections
        moved = {
            (key_layer, index - sum(removed < index for removed in indices)): section
            for (key_layer, index), section in sections.items()
            if key_layer != layer_id or index not in indices
        }
        if self.state.multi_layer_mode:
            self.state.layer_sections = moved
        else:
            self.state.beam_sections = moved

    @staticmethod
    def _manual_support_keys(item: ManualBeamInput) -> tuple[LayerBeamKey, ...]:
        """Return every persisted support identity used by a manual beam."""
        supports = [item.first_support, item.second_support]
        if item.reference_support is not None:
            supports.append(item.reference_support)
        return tuple(supports)

    def _manual_beams_using_supports(
        self, supports: set[LayerBeamKey], *, ignored_ids: set[str] | None = None,
    ) -> set[str]:
        """Find manual beams that would lose a support in an edit operation."""
        ignored = ignored_ids or set()
        return {
            item.beam_id
            for item in self.state.manual_beams
            if item.beam_id not in ignored and any(key in supports for key in self._manual_support_keys(item))
        }

    def _shift_manual_supports_after_insertion(self, layer_id: str, after_index: int) -> None:
        """Keep manual-beam support identities attached to the same physical beams."""
        def shifted(key: LayerBeamKey | None) -> LayerBeamKey | None:
            if key is None or key[0] != layer_id or key[1] <= after_index:
                return key
            return key[0], key[1] + 1

        self.state.manual_beams = [
            replace(
                item,
                first_support=shifted(item.first_support),  # type: ignore[arg-type]
                second_support=shifted(item.second_support),  # type: ignore[arg-type]
                reference_support=shifted(item.reference_support),
            )
            for item in self.state.manual_beams
        ]

    def _reindex_manual_supports_after_deletion(self, layer_id: str, indices: set[int]) -> None:
        """Move surviving manual-beam support identities after an internal deletion."""
        if not indices:
            return

        def shifted(key: LayerBeamKey | None) -> LayerBeamKey | None:
            if key is None or key[0] != layer_id:
                return key
            return key[0], key[1] - sum(removed < key[1] for removed in indices)

        self.state.manual_beams = [
            replace(
                item,
                first_support=shifted(item.first_support),  # type: ignore[arg-type]
                second_support=shifted(item.second_support),  # type: ignore[arg-type]
                reference_support=shifted(item.reference_support),
            )
            for item in self.state.manual_beams
        ]

    def _clear_sections_for_axis(self, axis: PalletAxis) -> None:
        """Geometry edits renumber beam indices, so stale overrides must not move."""
        self.state.beam_sections = {
            key: section for key, section in self.state.beam_sections.items() if key[0] != axis
        }

    def add_manual_beam(
        self, first_support: LayerBeamKey, second_support: LayerBeamKey, distance: float,
        section: BeamSection, reference_support: LayerBeamKey | None = None,
        reference_face: str | None = None, first_face: str = "top", second_face: str = "top",
    ) -> PalletResult | None:
        """Store one explicitly supported beam and rebuild the pallet view."""
        current = self.state.result
        supports = {(beam.layer_id, beam.layer_index): beam for beam in current.beams_3d} if current else {}
        first, second = supports.get(first_support), supports.get(second_support)
        reference = supports.get(reference_support) if reference_support is not None else None
        valid_faces = {"top", "bottom"}
        if (first is None or second is None or first is second
                or first.orientation != second.orientation
                or first_face not in valid_faces or second_face not in valid_faces
                or first_face != second_face
                or not isfinite(distance)
                or not isfinite(section.height) or not isfinite(section.width)
                or section.height <= 0 or section.width <= 0
                or (reference_support is not None and reference is None)):
            self._on_error(CalculationError("Ручной брус должен опираться на две разные параллельные грани с корректным сечением."), False)
            return None
        if reference is not None:
            allowed_faces = {"x_min", "x_max"} if first.orientation == "length" else {"y_min", "y_max"}
            if reference_face not in allowed_faces:
                self._on_error(CalculationError("Для ручного бруса выбрана грань неподходящего направления."), False)
                return None
        number = 1
        known = {beam.beam_id for beam in self.state.manual_beams}
        while f"manual-{number}" in known:
            number += 1
        self.state.manual_beams.append(ManualBeamInput(
            f"manual-{number}", first_support, second_support, distance, section,
            reference_support=reference_support, reference_face=reference_face,
            first_face=first_face, second_face=second_face,
        ))
        result = self.recalculate_from_state()
        if result is None:
            self.state.manual_beams.pop()
        return result

    def _with_manual_beams(self, result: PalletResult) -> PalletResult:
        """Resolve persistent manual beams against the newly calculated support grid."""
        if not self.state.manual_beams:
            return result
        source = {(beam.layer_id, beam.layer_index): beam for beam in result.beams_3d}
        extras: list[Beam3D] = []
        for item in self.state.manual_beams:
            first = source.get(item.first_support)
            second = source.get(item.second_support)
            if first is None or second is None or first.orientation != second.orientation:
                continue
            reference = source.get(item.reference_support) if item.reference_support else None
            if item.reference_support is not None and reference is None:
                continue
            if item.first_face != item.second_face:
                continue
            bearing = (
                max(first.z + first.size_z / 2, second.z + second.size_z / 2)
                if item.first_face == "top"
                else min(first.z - first.size_z / 2, second.z - second.size_z / 2)
            )
            z = bearing + item.section.height / 2 if item.first_face == "top" else bearing - item.section.height / 2
            if first.orientation == "length":
                start = min(first.y - first.size_y / 2, second.y - second.size_y / 2)
                end = max(first.y + first.size_y / 2, second.y + second.size_y / 2)
                coordinate = self._offset_from_reference(
                    reference, item.reference_face, "x", item.distance, item.section.width,
                )
                added = Beam3D(
                    coordinate, (start + end) / 2, z,
                    item.section.width, end - start, item.section.height,
                    "width", item.beam_id, 0,
                )
            else:
                start = min(first.x - first.size_x / 2, second.x - second.size_x / 2)
                end = max(first.x + first.size_x / 2, second.x + second.size_x / 2)
                coordinate = self._offset_from_reference(
                    reference, item.reference_face, "y", item.distance, item.section.width,
                )
                added = Beam3D(
                    (start + end) / 2, coordinate, z,
                    end - start, item.section.width, item.section.height,
                    "length", item.beam_id, 0,
                )
            # Resolve user beams in creation order.  This lets a later beam
            # use the side face of an earlier manually added one as its
            # reference, just like it can use an original pallet beam.
            extras.append(added)
            source[(added.layer_id, added.layer_index)] = added
        if not extras:
            return result
        height = max(result.pallet_height, *(beam.z + beam.size_z / 2 for beam in extras))
        return replace(result, beams_3d=(*result.beams_3d, *extras), pallet_height=height)

    @staticmethod
    def _offset_from_reference(
        beam: Beam3D | None, face: str | None, axis: str, distance: float, new_beam_width: float,
    ) -> float:
        """Place the new beam from the selected face, along its outward normal.

        A positive value therefore continues *outward* from the selected
        face: to the right of ``x_max`` and to the left of ``x_min``.  This
        makes the side selected in the viewport unambiguous; a negative value
        intentionally places the beam on the opposite side.
        """
        half_width = new_beam_width / 2
        half_offset = copysign(half_width, distance if distance else 1.0)
        if beam is None:
            return distance + half_offset
        if axis == "x":
            if face == "x_min":
                if distance >= 0:
                    return beam.x - beam.size_x / 2 - distance - half_width
                return beam.x + beam.size_x / 2 - distance + half_width
            if face == "x_max":
                if distance >= 0:
                    return beam.x + beam.size_x / 2 + distance + half_width
                return beam.x - beam.size_x / 2 + distance - half_width
            return beam.x + distance + half_offset
        if face == "y_min":
            if distance >= 0:
                return beam.y - beam.size_y / 2 - distance - half_width
            return beam.y + beam.size_y / 2 - distance + half_width
        if face == "y_max":
            if distance >= 0:
                return beam.y + beam.size_y / 2 + distance + half_width
            return beam.y - beam.size_y / 2 + distance - half_width
        return beam.y + distance + half_offset

    def _run_automatic_rebuild(self) -> None:
        scheduled_revision = self._scheduled_revision
        self._scheduled_revision = None
        if scheduled_revision is None or scheduled_revision != self._rebuild_revision:
            return
        if self._input_provider is None:
            return
        try:
            length_input, width_input, upper_layer = self._input_provider()
        except CalculationError as exc:
            self._on_stale_changed(True)
            self._on_error(exc, False)
            return
        self.calculate(length_input, width_input, upper_layer, show_error=False)
