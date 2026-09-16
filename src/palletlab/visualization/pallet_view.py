"""PyVista viewport that consumes only pre-calculated Beam3D geometry."""

from __future__ import annotations

import pyvista as pv
from pyvistaqt import QtInteractor

from palletlab.core.formatting import format_mm
from palletlab.core.models import PalletResult


class PalletView(QtInteractor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("border: 0px; margin: 0px; padding: 0px;")
        self.set_background("#f5f7fa")
        self.add_axes()
        self.show_grid(color="#b8c2cc")
        self._has_model = False

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

    @staticmethod
    def _display_y(result: PalletResult, y: float) -> float:
        """Mirror only the visual Y axis so calculated (0, 0) is upper-left."""
        return result.pallet_width - y

    def _add_dimension_segment(
        self, start: tuple[float, float, float], end: tuple[float, float, float], name: str
    ) -> None:
        """Draw one independent gap line; never form a continuous outer rail."""
        self.add_mesh(pv.Line(start, end), color="#3d8582", line_width=2, name=name)

    def _add_length_gap_dimensions(self, result: PalletResult) -> None:
        """Place clear-gap labels along X without visual rails outside the model."""
        direction = result.length_result
        offset = max(50.0, result.pallet_width * 0.055)
        y, z = -offset, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for index, gap in enumerate(direction.gaps):
            start = direction.beam_centers[index] + direction.beam_width / 2
            end = direction.beam_centers[index + 1] - direction.beam_width / 2
            display_y = self._display_y(result, y)
            self._add_dimension_segment((start, display_y, z), (end, display_y, z), f"length-gap-{index}")
            points.append(((start + end) / 2, display_y, z))
            labels.append(f"{format_mm(gap)} mm")
        self.add_point_labels(points, labels, name="length-gap-labels", point_size=0, font_size=12,
                              text_color="#173f45", shape_color="#fffdf9", shape_opacity=0.88,
                              fill_shape=True, always_visible=True)

    def _add_width_gap_dimensions(self, result: PalletResult) -> None:
        """Place clear-gap labels along Y without visual rails outside the model."""
        direction = result.width_result
        offset = max(50.0, result.pallet_length * 0.035)
        x, z = -offset, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for index, gap in enumerate(direction.gaps):
            start = direction.beam_centers[index] + direction.beam_width / 2
            end = direction.beam_centers[index + 1] - direction.beam_width / 2
            display_start = self._display_y(result, start)
            display_end = self._display_y(result, end)
            self._add_dimension_segment((x, display_start, z), (x, display_end, z), f"width-gap-{index}")
            points.append((x, self._display_y(result, (start + end) / 2), z))
            labels.append(f"{format_mm(gap)} mm")
        self.add_point_labels(points, labels, name="width-gap-labels", point_size=0, font_size=12,
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
