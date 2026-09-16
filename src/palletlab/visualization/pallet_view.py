"""PyVista viewport that consumes only pre-calculated Beam3D geometry."""

from __future__ import annotations

import pyvista as pv
from pyvistaqt import QtInteractor

from palletlab.core.models import PalletResult
from palletlab.ui.results_panel import format_mm


class PalletView(QtInteractor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.set_background("#f5f7fa")
        self.add_axes()
        self.show_grid(color="#b8c2cc")

    def show_pallet(self, result: PalletResult, show_length_gaps: bool = True, show_width_gaps: bool = True) -> None:
        self.clear()
        for beam in result.beams_3d:
            cube = pv.Cube(center=(beam.x, beam.y, beam.z), x_length=beam.size_x,
                           y_length=beam.size_y, z_length=beam.size_z)
            color = "#b7791f" if beam.orientation == "length" else "#8b5a2b"
            self.add_mesh(cube, color=color, show_edges=True, edge_color="#4a2c12", smooth_shading=False)
        if show_length_gaps:
            self._add_length_gap_dimensions(result)
        if show_width_gaps:
            self._add_width_gap_dimensions(result)
        self.add_axes()
        self.add_text(
            f"Length: {format_mm(result.pallet_length)} mm\n"
            f"Width: {format_mm(result.pallet_width)} mm\n"
            f"Height: {format_mm(result.pallet_height)} mm",
            position="upper_left", font_size=11, color="#1f2937", name="dimensions",
        )
        # The initial orientation is a plan view: X grows left-to-right and
        # Y grows from the upper edge downward, so coordinate origin (0, 0)
        # is the visible upper-left pallet corner.
        self.camera_top()

    def _add_line(self, start: tuple[float, float, float], end: tuple[float, float, float], name: str) -> None:
        self.add_mesh(pv.Line(start, end), color="#25636a", line_width=2, name=name)

    def _add_length_gap_dimensions(self, result: PalletResult) -> None:
        """Draw clear gaps along X above the pallet's zero-Y edge."""
        direction = result.length_result
        offset = max(50.0, result.pallet_width * 0.055)
        tick = max(20.0, offset * 0.22)
        y, z = -offset, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for index, gap in enumerate(direction.gaps):
            start = direction.beam_centers[index] + direction.beam_width / 2
            end = direction.beam_centers[index + 1] - direction.beam_width / 2
            self._add_line((start, y, z), (end, y, z), f"length-gap-{index}")
            self._add_line((start, y - tick, z), (start, y + tick, z), f"length-tick-start-{index}")
            self._add_line((end, y - tick, z), (end, y + tick, z), f"length-tick-end-{index}")
            points.append(((start + end) / 2, y - tick * 1.3, z))
            labels.append(f"{format_mm(gap)} мм")
        self.add_point_labels(points, labels, name="length-gap-labels", point_size=0, font_size=12,
                              text_color="#173f45", shape_color="#fffdf9", shape_opacity=0.88,
                              fill_shape=True, always_visible=True)

    def _add_width_gap_dimensions(self, result: PalletResult) -> None:
        """Draw clear gaps along Y left of the pallet's zero-X edge."""
        direction = result.width_result
        offset = max(50.0, result.pallet_length * 0.035)
        tick = max(20.0, offset * 0.22)
        x, z = -offset, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for index, gap in enumerate(direction.gaps):
            start = direction.beam_centers[index] + direction.beam_width / 2
            end = direction.beam_centers[index + 1] - direction.beam_width / 2
            self._add_line((x, start, z), (x, end, z), f"width-gap-{index}")
            self._add_line((x - tick, start, z), (x + tick, start, z), f"width-tick-start-{index}")
            self._add_line((x - tick, end, z), (x + tick, end, z), f"width-tick-end-{index}")
            points.append((x - tick * 1.9, (start + end) / 2, z))
            labels.append(f"{format_mm(gap)} мм")
        self.add_point_labels(points, labels, name="width-gap-labels", point_size=0, font_size=12,
                              text_color="#173f45", shape_color="#fffdf9", shape_opacity=0.88,
                              fill_shape=True, always_visible=True)

    def camera_isometric(self) -> None:
        self.view_isometric()
        self.reset_camera()

    def camera_top(self) -> None:
        self.view_xy()
        self.camera.SetViewUp(0, -1, 0)
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
