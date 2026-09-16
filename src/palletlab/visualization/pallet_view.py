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

    def show_pallet(self, result: PalletResult) -> None:
        self.clear()
        for beam in result.beams_3d:
            cube = pv.Cube(center=(beam.x, beam.y, beam.z), x_length=beam.size_x,
                           y_length=beam.size_y, z_length=beam.size_z)
            color = "#b7791f" if beam.orientation == "length" else "#8b5a2b"
            self.add_mesh(cube, color=color, show_edges=True, edge_color="#4a2c12", smooth_shading=False)
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
