"""PyVista viewport that consumes only pre-calculated Beam3D geometry."""

from __future__ import annotations

from collections.abc import Callable

import pyvista as pv
from pyvistaqt import QtInteractor

from palletlab.core.calculator import inserted_beam_center
from palletlab.core.formatting import format_mm
from palletlab.core.models import InsertionSlot, PalletResult


class PalletView(QtInteractor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("border: 0px; margin: 0px; padding: 0px;")
        self.set_background("#f5f7fa")
        self.add_axes()
        self.show_grid(color="#b8c2cc")
        self._has_model = False
        self._insertion_slots: dict[object, InsertionSlot] = {}
        self._insertion_callback: Callable[[InsertionSlot], None] | None = None
        self._insertion_mode = False
        self._hovered_insertion_actor = None
        self.iren.add_observer("MouseMoveEvent", self._update_insertion_hover)

    def show_pallet(self, result: PalletResult, show_length_gaps: bool = True, show_width_gaps: bool = True) -> None:
        camera_position = self.camera_position if self._has_model else None
        self.clear()
        for beam in result.beams_3d:
            cube = pv.Cube(center=(beam.x, self._display_y(result, beam.y), beam.z), x_length=beam.size_x,
                           y_length=beam.size_y, z_length=beam.size_z)
            color = "#b7791f" if beam.orientation == "length" else "#8b5a2b"
            self.add_mesh(cube, color=color, show_edges=True, edge_color="#4a2c12", smooth_shading=False)
        if show_length_gaps:
            self._add_length_gap_dimensions(result)
        if show_width_gaps:
            self._add_width_gap_dimensions(result)
        self.add_axes()
        if camera_position is None:
            self.camera_top()
        else:
            self.camera_position = camera_position
            self.render()
        self._has_model = True

    def enable_insertion_mode(
        self, result: PalletResult, slots: tuple[InsertionSlot, ...], callback: Callable[[InsertionSlot], None]
    ) -> None:
        """Show pickable plus markers in every gap that can fit one more beam."""
        self.disable_insertion_mode()
        self._insertion_mode = True
        self._insertion_callback = callback
        marker_size = max(24.0, min(result.pallet_length, result.pallet_width) * 0.06)
        for slot in slots:
            direction = result.length_result if slot.axis == "length" else result.width_result
            gap_start = direction.beam_centers[slot.after_beam_index] + direction.beam_width / 2
            gap_end = direction.beam_centers[slot.after_beam_index + 1] - direction.beam_width / 2
            position = (gap_start + gap_end) / 2
            if slot.axis == "length":
                center = (position, self._display_y(result, result.pallet_width / 2), result.pallet_height + 5)
            else:
                center = (result.pallet_length / 2, self._display_y(result, position), result.pallet_height + 5)
            marker = pv.Text3D("+", height=marker_size, depth=1, center=center)
            actor = self.add_mesh(marker, color="#1f7775", opacity=0.35, pickable=True,
                                  name=f"insert-slot-{slot.axis}-{slot.after_beam_index}")
            self._insertion_slots[actor] = slot
        self.enable_mesh_picking(callback=self._select_insertion_slot, show=False, left_clicking=True,
                                 use_actor=True, show_message=False)
        self.render()

    def disable_insertion_mode(self) -> None:
        """Remove insertion affordances while preserving the currently displayed pallet."""
        self.disable_picking()
        for actor in self._insertion_slots:
            self.remove_actor(actor, render=False)
        self._insertion_slots.clear()
        self._insertion_callback = None
        self._insertion_mode = False
        self._hovered_insertion_actor = None
        self.clear_insertion_preview()
        self.render()

    def show_insertion_preview(self, result: PalletResult, slot: InsertionSlot, clear_gap: float) -> None:
        """Draw a translucent candidate beam without committing it to the model."""
        self.clear_insertion_preview()
        direction = result.length_result if slot.axis == "length" else result.width_result
        center = inserted_beam_center(direction, slot.after_beam_index, clear_gap)
        if slot.axis == "length":
            z_base = result.width_result.beam_height if result.upper_layer == "length" else 0.0
            cube = pv.Cube(center=(center, self._display_y(result, result.pallet_width / 2), z_base + direction.beam_height / 2),
                           x_length=direction.beam_width, y_length=result.pallet_width, z_length=direction.beam_height)
        else:
            z_base = result.length_result.beam_height if result.upper_layer == "width" else 0.0
            cube = pv.Cube(center=(result.pallet_length / 2, self._display_y(result, center), z_base + direction.beam_height / 2),
                           x_length=result.pallet_length, y_length=direction.beam_width, z_length=direction.beam_height)
        self.add_mesh(cube, color="#23908a", opacity=0.46, show_edges=True, edge_color="#155854",
                      name="insertion-preview")
        self.render()

    def clear_insertion_preview(self) -> None:
        self.remove_actor("insertion-preview", render=False)

    def _select_insertion_slot(self, actor) -> None:
        for marker, slot in self._insertion_slots.items():
            if marker == actor:
                if self._insertion_callback:
                    self._insertion_callback(slot)
                return

    def _update_insertion_hover(self, *_args) -> None:
        if not self._insertion_mode or not self._insertion_slots:
            return
        picker = pv._vtk.vtkPropPicker()
        x, y = self.iren.get_event_position()
        picker.Pick(x, y, 0, self.renderer)
        hovered = picker.GetActor()
        if hovered == self._hovered_insertion_actor:
            return
        self._hovered_insertion_actor = hovered
        for actor in self._insertion_slots:
            actor.GetProperty().SetOpacity(0.9 if actor == hovered else 0.35)
        self.render()

    @staticmethod
    def _display_y(result: PalletResult, y: float) -> float:
        """Mirror only the visual Y axis so calculated (0, 0) is upper-left."""
        return result.pallet_width - y

    def _add_dimension_segment(
        self, start: tuple[float, float, float], end: tuple[float, float, float], name: str
    ) -> None:
        """Draw one independent gap line; never form a continuous outer rail."""
        self.add_mesh(pv.Line(start, end), color="#3d8582", line_width=2, name=name)

    def _add_t_end(self, point: tuple[float, float, float], perpendicular: str, size: float, name: str) -> None:
        """Add a short perpendicular end mark, like a technical drawing dimension."""
        x, y, z = point
        if perpendicular == "y":
            start, end = (x, y - size, z), (x, y + size, z)
        else:
            start, end = (x - size, y, z), (x + size, y, z)
        self._add_dimension_segment(start, end, name)

    def _add_length_gap_dimensions(self, result: PalletResult) -> None:
        """Place stepped X dimensions: inner faces, then the final outer face."""
        direction = result.length_result
        offset = max(50.0, result.pallet_width * 0.055)
        tick = max(14.0, offset * 0.18)
        base = direction.beam_centers[0] - direction.beam_width / 2
        model_edge_y, z = 0.0, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for index, center in enumerate(direction.beam_centers[1:], start=1):
            is_last_beam = index == len(direction.beam_centers) - 1
            end = center + direction.beam_width / 2 if is_last_beam else center - direction.beam_width / 2
            display_y = self._display_y(result, -offset * index)
            display_model_y = self._display_y(result, model_edge_y)
            self._add_dimension_segment((base, display_y, z), (end, display_y, z), f"length-dimension-{index}")
            self._add_dimension_segment((base, display_model_y, z), (base, display_y, z), f"length-base-extension-{index}")
            self._add_dimension_segment((end, display_model_y, z), (end, display_y, z), f"length-end-extension-{index}")
            self._add_t_end((base, display_y, z), "y", tick, f"length-start-tick-{index}")
            self._add_t_end((end, display_y, z), "y", tick, f"length-end-tick-{index}")
            points.append(((base + end) / 2, display_y, z))
            labels.append(f"{format_mm(end - base)} mm")
        self.add_point_labels(points, labels, name="length-dimension-labels", point_size=0, font_size=12,
                              text_color="#173f45", shape_color="#fffdf9", shape_opacity=0.88,
                              fill_shape=True, always_visible=True)

    def _add_width_gap_dimensions(self, result: PalletResult) -> None:
        """Place stepped Y dimensions: inner faces, then the final outer face."""
        direction = result.width_result
        offset = max(50.0, result.pallet_length * 0.035)
        tick = max(14.0, offset * 0.18)
        base = direction.beam_centers[0] - direction.beam_width / 2
        model_edge_x, z = 0.0, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for index, center in enumerate(direction.beam_centers[1:], start=1):
            is_last_beam = index == len(direction.beam_centers) - 1
            end = center + direction.beam_width / 2 if is_last_beam else center - direction.beam_width / 2
            x = -offset * index
            display_start = self._display_y(result, base)
            display_end = self._display_y(result, end)
            self._add_dimension_segment((x, display_start, z), (x, display_end, z), f"width-dimension-{index}")
            self._add_dimension_segment((model_edge_x, display_start, z), (x, display_start, z),
                                        f"width-base-extension-{index}")
            self._add_dimension_segment((model_edge_x, display_end, z), (x, display_end, z),
                                        f"width-end-extension-{index}")
            self._add_t_end((x, display_start, z), "x", tick, f"width-start-tick-{index}")
            self._add_t_end((x, display_end, z), "x", tick, f"width-end-tick-{index}")
            points.append((x, self._display_y(result, (base + end) / 2), z))
            labels.append(f"{format_mm(end - base)} mm")
        self.add_point_labels(points, labels, name="width-dimension-labels", point_size=0, font_size=12,
                              text_color="#173f45", shape_color="#fffdf9", shape_opacity=0.88,
                              fill_shape=True, always_visible=True)

    def camera_isometric(self) -> None:
        self.view_isometric()
        self.reset_camera()

    def camera_top(self) -> None:
        self.view_xy()
        self.camera.SetViewUp(0, 1, 0)
        self.reset_camera(render=True)

    def camera_front(self) -> None:
        self.view_xz()
        self.reset_camera()

    def camera_side(self) -> None:
        self.view_yz()
        self.reset_camera()

    def camera_fit(self) -> None:
        """Fit the camera without forwarding Qt's clicked(bool) argument."""
        self.reset_camera(render=True)
        self.camera.zoom(1.35)
        self.render()
