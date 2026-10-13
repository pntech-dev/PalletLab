"""PyVista viewport that consumes only pre-calculated Beam3D geometry."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QTimer
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor

from palletlab.core.formatting import format_mm
from palletlab.core.models import PalletAxis, PalletResult
from palletlab.controllers.viewport_geometry import EditableDimension, InsertionMarker, PreviewBox


class PalletView(QtInteractor):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("border: 0px; margin: 0px; padding: 0px;")
        self.set_background("#f5f7fa")
        self._has_model = False
        self._axes_added = False
        self._annotation_actors: list[object] = []
        self._annotation_segments: list[pv.PolyData] | None = None
        self._insertion_slots: dict[object, InsertionMarker] = {}
        self._insertion_visual_actors: list[object] = []
        self._insertion_callback: Callable[[object], None] | None = None
        self._insertion_mode = False
        self._hovered_insertion_actor = None
        self._active_insertion_slot: InsertionSlot | None = None
        self._beam_actors: dict[object, tuple[PalletAxis, int]] = {}
        self._beam_counts: dict[PalletAxis, int] = {"length": 0, "width": 0}
        self._deletion_callback: Callable[[PalletAxis, int, bool], None] | None = None
        self._deletion_mode = False
        self._selected_deletion_actors: set[object] = set()
        self._hovered_deletion_actor = None
        self._distance_actors: dict[object, tuple[PalletAxis, int, float]] = {}
        self._distance_callback: Callable[[PalletAxis, int, float], None] | None = None
        self._distance_editing_mode = False
        self._selected_distance_actor = None
        self._hovered_distance_actor = None
        self._step_mesh: pv.PolyData | None = None
        self._step_edges: pv.PolyData | None = None
        self._step_model_actor = None
        self._step_edge_actor = None
        self._step_model_visible = True
        self._step_faces = ()
        self._support_callback: Callable[[int], None] | None = None
        self._support_face_indices: set[int] = set()
        self._reference_support_index: int | None = None
        self._step_face_cell_indices: dict[int, np.ndarray] = {}
        self._hovered_step_face_index: int | None = None
        self._step_hover_actor = None
        self._step_picker = pv._vtk.vtkCellPicker()
        self._step_picker.SetTolerance(0.0005)
        self._step_picker.PickFromListOn()
        self._mesh_picker = pv._vtk.vtkCellPicker()
        self._mesh_picker.SetTolerance(0.0005)
        # Picking is used on every mouse move in interactive modes.  Reusing
        # VTK's picker avoids repeated native-object allocation.
        self._prop_picker = pv._vtk.vtkPropPicker()
        self._interaction_colors = {
            "selected": pv.Color("#d83a3a").float_rgb,
            "selected_edge": pv.Color("#7a1717").float_rgb,
            "selected_hover": pv.Color("#ed6259").float_rgb,
            "selected_hover_edge": pv.Color("#9e211b").float_rgb,
            "length_beam": pv.Color("#b7791f").float_rgb,
            "width_beam": pv.Color("#8b5a2b").float_rgb,
            "default_edge": pv.Color("#4a2c12").float_rgb,
            "beam_hover": pv.Color("#e0a12b").float_rgb,
            "beam_hover_edge": pv.Color("#805518").float_rgb,
            "distance": pv.Color("#d28326").float_rgb,
            "distance_selected": pv.Color("#c23832").float_rgb,
        }
        self.iren.add_observer("MouseMoveEvent", self._update_insertion_hover)
        self.iren.add_observer("MouseMoveEvent", self._update_deletion_hover)
        self.iren.add_observer("MouseMoveEvent", self._update_distance_hover)
        self.iren.add_observer("MouseMoveEvent", self._update_step_face_hover)
        self.iren.add_observer("LeftButtonPressEvent", self._click_distance)
        self.iren.add_observer("LeftButtonPressEvent", self._click_insertion)
        self.iren.add_observer("LeftButtonPressEvent", self._click_deletion)
        self.iren.add_observer("LeftButtonPressEvent", self._pick_step_face)

    def show_pallet(self, result: PalletResult, show_length_gaps: bool = True, show_width_gaps: bool = True) -> None:
        camera_position = self.camera_position if self._has_model else None
        # Keep the STEP actor in the renderer.  Clearing the complete scene
        # made a large translucent model flash on every pallet recalculation.
        self._clear_pallet_actors()
        length_count = len(result.length_result.beam_centers)
        self._beam_counts = {
            "length": length_count,
            "width": len(result.width_result.beam_centers),
        }
        for beam_index, beam in enumerate(result.beams_3d):
            cube = self._beam_cube(result, beam)
            color = "#b7791f" if beam.orientation == "length" else "#8b5a2b"
            actor = self.add_mesh(
                cube,
                color=color,
                show_edges=True,
                edge_color="#4a2c12",
                smooth_shading=False,
                pickable=True,
                name=f"pallet-beam-{beam_index}",
                reset_camera=False,
            )
            axis = "length" if beam_index < length_count else "width"
            index = beam_index if axis == "length" else beam_index - length_count
            self._beam_actors[actor] = (axis, index)
        self.update_dimension_annotations(result, show_length_gaps, show_width_gaps, render=False)
        self._ensure_axes()
        self._sync_step_model_actor()
        if camera_position is None:
            self.camera_isometric()
        else:
            self.camera_position = camera_position
            self.render()
        self._has_model = True

    def _clear_pallet_actors(self) -> None:
        """Replace pallet-only actors without disturbing the STEP preview."""
        self.disable_insertion_mode(render=False)
        self.disable_deletion_mode(render=False)
        self.disable_distance_editing(render=False)
        self._remove_actors(list(self._beam_actors))
        self._beam_actors.clear()
        self._remove_actors(self._annotation_actors)
        self.remove_actor("length-dimension-labels-points", render=False)
        self.remove_actor("width-dimension-labels-points", render=False)
        self._annotation_segments = None

    def _ensure_axes(self) -> None:
        if self._axes_added:
            return
        self.add_axes(line_width=1, xlabel="X", ylabel="Y", zlabel="Z", viewport=(0, 0, 0.13, 0.13))
        self._axes_added = True

    def clear_workspace(self) -> None:
        """Remove the pallet and any imported machine before a new STEP import."""
        self.clear()
        self._annotation_actors.clear()
        self._beam_actors.clear()
        self._distance_actors.clear()
        self._step_mesh = None
        self._step_edges = None
        self._step_model_actor = None
        self._step_edge_actor = None
        self._step_faces = ()
        self._support_callback = None
        self._support_face_indices.clear()
        self._reference_support_index = None
        self._step_face_cell_indices.clear()
        self._hovered_step_face_index = None
        self._step_hover_actor = None
        self._has_model = False
        self._axes_added = False
        self._ensure_axes()
        self.render()

    def clear_step_model(self) -> None:
        """Forget only the imported machine while leaving a pallet render intact."""
        self.remove_actor("step-model", render=False)
        self.remove_actor("step-model-edges", render=False)
        self._step_mesh = None
        self._step_edges = None
        self._step_model_actor = None
        self._step_edge_actor = None
        self._step_faces = ()
        self._support_callback = None
        self._support_face_indices.clear()
        self._reference_support_index = None
        self._step_face_cell_indices.clear()
        self._hovered_step_face_index = None
        self._step_hover_actor = None
        self._step_model_visible = True
        self.render()

    def prepare_step_model_rebuild(self, callback: Callable[[int], None]) -> None:
        """Remove only pallet geometry and re-enable support picking on the visible model."""
        self._remove_actors(list(self._beam_actors))
        self._beam_actors.clear()
        self._beam_counts = {"length": 0, "width": 0}
        self._remove_actors(self._annotation_actors)
        self.remove_actor("length-dimension-labels-points", render=False)
        self.remove_actor("width-dimension-labels-points", render=False)
        self._remove_actors(list(self._distance_actors))
        self._distance_actors.clear()
        self._support_callback = callback
        self._support_face_indices.clear()
        self._reference_support_index = None
        self._hovered_step_face_index = None
        self._remove_step_hover_face()
        self._step_model_visible = True
        if self._step_mesh is not None:
            self._step_mesh.cell_data["face_colors"] = [(184, 194, 204)] * self._step_mesh.n_cells
            self._step_mesh.Modified()
        if self._step_model_actor is not None:
            self._step_model_actor.SetVisibility(True)
            self._step_model_actor.mapper.Update()
        if self._step_edge_actor is not None:
            self._step_edge_actor.SetVisibility(True)
        self.render()

    def show_step_model(self, mesh: pv.PolyData, edges: pv.PolyData, faces: tuple, callback: Callable[[int], None]) -> None:
        """Display an imported STEP mesh and wait for the user to choose a support face."""
        self.clear_workspace()
        self._step_mesh = mesh.copy(deep=True)
        self._step_mesh.cell_data["face_colors"] = np.tile(np.array((184, 194, 204), dtype=np.uint8), (mesh.n_cells, 1))
        self._step_edges = edges.copy(deep=True)
        self._step_faces = faces
        self._support_callback = callback
        self._support_face_indices.clear()
        self._reference_support_index = None
        self._index_step_faces()
        self._hovered_step_face_index = None
        self._remove_step_hover_face()
        self._step_model_visible = True
        self._add_step_model(render=False)
        # The imported model is the first visible scene, so fit it exactly
        # once here.  Later transient actors (hover highlights and edges)
        # must never silently alter a camera the user has already navigated.
        self.view_vector((-1, -1, 1), viewup=(0, 0, 1))
        self.reset_camera(render=True)
        # The STEP preview is already a real scene.  Subsequent pallet renders
        # must preserve any zoom/rotation the user made while choosing a face.
        self._has_model = True

    def stage_step_model(self, mesh: pv.PolyData, edges: pv.PolyData) -> None:
        """Prepare a correctly placed machine before rendering the new pallet."""
        # ``mesh`` and ``edges`` are freshly created for this calculation.
        # Retain them directly: duplicating a large assembly here can block the
        # UI for seconds immediately after the pallet appears.
        self._step_mesh = mesh
        self._step_mesh.cell_data["face_colors"] = np.tile(np.array((184, 194, 204), dtype=np.uint8), (mesh.n_cells, 1))
        self._step_edges = edges
        self._index_step_faces()
        self._hovered_step_face_index = None
        self._remove_step_hover_face()

    def commit_step_support_selection(self, support_indices: set[int], reference_index: int) -> None:
        """Highlight supports in the already-rendered placed model.

        This deliberately does not rebuild any VTK actors: the model and pallet
        were rendered together by ``show_pallet`` immediately beforehand.
        """
        if self._step_mesh is None:
            return
        self._support_face_indices = set(support_indices)
        self._reference_support_index = reference_index
        self._support_callback = None
        self._refresh_step_face_colors(render=True)

    def _refresh_step_face_colors(self, *, render: bool) -> None:
        if self._step_mesh is None:
            return
        colors = np.tile(np.array((184, 194, 204), dtype=np.uint8), (self._step_mesh.n_cells, 1))
        selected_faces = set(self._support_face_indices)
        if self._reference_support_index is not None:
            selected_faces.add(self._reference_support_index)
        for face_id in selected_faces:
            colors[self._step_face_cells(face_id)] = self._step_face_color(face_id)
        self._step_mesh.cell_data["face_colors"] = colors
        color_array = self._step_mesh.GetCellData().GetArray("face_colors")
        if color_array is not None:
            color_array.Modified()
        self._step_mesh.Modified()
        if self._step_model_actor is not None:
            self._step_model_actor.mapper.Update()
        if render:
            self.render()

    def _index_step_faces(self) -> None:
        """Clear the small on-demand face-cell cache after replacing the mesh."""
        self._step_face_cell_indices.clear()

    def _step_face_cells(self, face_id: int) -> np.ndarray:
        """Return one face's triangle cells without allocating an index for every face."""
        cached = self._step_face_cell_indices.get(face_id)
        if cached is not None:
            return cached
        if self._step_mesh is None:
            return np.empty(0, dtype=np.int64)
        cells = np.flatnonzero(np.asarray(self._step_mesh.cell_data["step_face_index"]) == face_id)
        # Hovering over a large assembly should not retain one index array per
        # CAD face.  A tiny LRU-like cache covers the current/previous faces.
        if len(self._step_face_cell_indices) >= 8:
            self._step_face_cell_indices.pop(next(iter(self._step_face_cell_indices)))
        self._step_face_cell_indices[face_id] = cells
        return cells

    def _step_face_color(self, face_id: int) -> tuple[int, int, int]:
        color = (184, 194, 204)
        if face_id in self._support_face_indices:
            color = (230, 41, 51)
        if face_id == self._reference_support_index:
            color = (255, 176, 26)
        return color

    def _update_step_face_hover(self, *_args) -> None:
        if self._support_callback is None or self._step_model_actor is None or not self._step_model_visible:
            return
        hovered = self._hardware_step_face_at_cursor()
        if hovered == self._hovered_step_face_index:
            return
        self._hovered_step_face_index = hovered
        self._show_step_hover_face(hovered)
        self.render()

    def _hardware_step_face_at_cursor(self) -> int | None:
        """Use GPU picking for hover; CPU cell picking is too slow for assemblies."""
        if self._step_mesh is None:
            return None
        x, y = self.iren.get_event_position()
        selector = pv._vtk.vtkOpenGLHardwareSelector()
        selector.SetFieldAssociation(pv._vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS)
        selector.SetRenderer(self.renderer)
        selector.SetArea(x, y, x, y)
        selection = selector.Select()
        try:
            for index in range(selection.GetNumberOfNodes()):
                node = selection.GetNode(index)
                if node is None or node.GetProperties().Get(pv._vtk.vtkSelectionNode.PROP()) != self._step_model_actor:
                    continue
                cell_ids = pv.convert_array(node.GetSelectionList())
                if len(cell_ids):
                    return int(self._step_mesh.cell_data["step_face_index"][int(cell_ids[0])])
        finally:
            selection.UnRegister(selection)
        return None

    def _show_step_hover_face(self, face_id: int | None) -> None:
        self._remove_step_hover_face()
        if face_id is None or self._step_mesh is None:
            return
        highlighted = self._step_mesh.extract_cells(self._step_face_cells(face_id))
        if "face_colors" in highlighted.cell_data:
            highlighted.cell_data.remove("face_colors")
        self._step_hover_actor = self.add_mesh(
            highlighted, color="#33b9ae", opacity=0.80, show_edges=True,
            edge_color="#147b75", line_width=2.0, pickable=False, name="step-hover-face",
            reset_camera=False,
        )

    def _remove_step_hover_face(self) -> None:
        if self._step_hover_actor is not None:
            self.remove_actor(self._step_hover_actor, render=False)
        self._step_hover_actor = None

    def show_staged_step_model(self) -> None:
        """Reveal a staged placement after a failed pallet calculation."""
        self._add_step_model(render=True)

    def toggle_step_model_visibility(self) -> bool:
        """Toggle the imported machine without changing the generated pallet."""
        if self._step_model_actor is None:
            return False
        self._step_model_visible = not self._step_model_visible
        self._step_model_actor.SetVisibility(self._step_model_visible)
        if self._step_edge_actor is not None:
            self._step_edge_actor.SetVisibility(self._step_model_visible)
        self.render()
        return self._step_model_visible

    def _add_step_model(self, *, render: bool) -> None:
        if self._step_mesh is None:
            return
        self._remove_step_hover_face()
        self.remove_actor("step-model", render=False)
        self.remove_actor("step-model-edges", render=False)
        self._step_edge_actor = None
        self._step_model_actor = self.add_mesh(
            self._step_mesh,
            scalars="face_colors",
            rgb=True,
            # Imported assemblies are often made of overlapping shells.  A
            # translucent surface and dark face edges keep their internal
            # members readable while still leaving a clickable solid model.
            opacity=0.60,
            show_edges=False,
            smooth_shading=False,
            pickable=True,
            name="step-model",
            reset_camera=False,
        )
        self._step_picker.InitializePickList()
        self._step_picker.AddPickList(self._step_model_actor)
        self._step_model_actor.SetVisibility(self._step_model_visible)
        if self._step_edges is not None and self._step_edges.n_cells:
            self._step_edge_actor = self.add_mesh(
                self._step_edges, color="#536271", opacity=0.85,
                line_width=1.35, pickable=False, name="step-model-edges", reset_camera=False,
            )
            self._step_edge_actor.SetVisibility(self._step_model_visible)
        if render:
            self.render()

    def _sync_step_model_actor(self) -> None:
        """Refresh STEP geometry without rendering an intermediate empty scene."""
        if self._step_mesh is None:
            return
        # Recreating the two actors is more reliable than changing a VTK
        # mapper's input in place: the latter can lose PyVista's opacity and
        # RGB cell-colour configuration.  All actor operations use
        # ``render=False``, so the user sees only the finished frame.
        self._add_step_model(render=False)

    def _pick_step_face(self, *_args) -> None:
        if self._support_callback is None or self._step_model_actor is None or not self._step_model_visible:
            return
        x, y = self.iren.get_event_position()
        self._step_picker.Pick(x, y, 0, self.renderer)
        if self._step_picker.GetActor() != self._step_model_actor:
            return
        cell_id = self._step_picker.GetCellId()
        if self._step_mesh is not None and 0 <= cell_id < self._step_mesh.n_cells:
            self._support_callback(int(self._step_mesh.cell_data["step_face_index"][cell_id]))
            # A modal validation message consumes the Qt mouse-release event.
            # End VTK's press state on the next event-loop turn so it cannot
            # interpret the following mouse move as camera rotation.
            QTimer.singleShot(0, self._stop_step_pick_interaction)

    def _stop_step_pick_interaction(self) -> None:
        style = self.iren.interactor.GetInteractorStyle()
        style.OnLeftButtonUp()
        style.StopState()

    def update_dimension_annotations(
        self, result: PalletResult, show_length_gaps: bool = True, show_width_gaps: bool = True, *, render: bool = True
    ) -> None:
        """Refresh only the distance annotations, leaving beam geometry intact."""
        self._remove_actors(self._annotation_actors)
        # ``add_point_labels`` owns an additional ``<name>-points`` actor.
        # It is not returned to us, so remove it by name when hiding or
        # replacing dimensions created by older renders.
        self.remove_actor("length-dimension-labels-points", render=False)
        self.remove_actor("width-dimension-labels-points", render=False)
        if show_length_gaps:
            self._add_length_gap_dimensions(result)
        if show_width_gaps:
            self._add_width_gap_dimensions(result)
        if render:
            self.render()

    def _remove_actors(self, actors: list[object]) -> None:
        """Remove one dynamic actor group without resetting the whole renderer."""
        for actor in actors:
            self.remove_actor(actor, render=False)
        actors.clear()

    @staticmethod
    def _beam_cube(result: PalletResult, beam) -> pv.PolyData:
        return pv.Cube(center=(beam.x, PalletView._display_y(result, beam.y), beam.z), x_length=beam.size_x,
                       y_length=beam.size_y, z_length=beam.size_z)

    def enable_insertion_mode(self, markers: tuple[InsertionMarker, ...], callback: Callable[[object], None]) -> None:
        """Show pickable plus markers in every gap that can fit one more beam."""
        self.disable_insertion_mode(render=False)
        self._insertion_mode = True
        self._insertion_callback = callback
        self._active_insertion_slot = None
        for item in markers:
            marker = pv.Text3D("+", height=item.size, depth=1, center=item.center)
            visual = self.add_mesh(marker, color="#1f7775", opacity=0.7, pickable=False,
                                   name=f"insert-symbol-{item.slot.axis}-{item.slot.after_beam_index}")
            self._insertion_visual_actors.append(visual)
            hit_size = max(48.0, item.size * 2.4)
            hitbox = pv.Cube(center=item.center, x_length=hit_size, y_length=hit_size,
                             z_length=max(12.0, item.size * 0.35))
            actor = self.add_mesh(hitbox, opacity=0.01, pickable=True,
                                  name=f"insert-slot-{item.slot.axis}-{item.slot.after_beam_index}")
            self._insertion_slots[actor] = item
        self.render()

    def disable_insertion_mode(self, *, render: bool = True) -> None:
        """Remove insertion affordances while preserving the currently displayed pallet."""
        self.disable_picking()
        for actor in self._insertion_slots:
            self.remove_actor(actor, render=False)
        self._remove_actors(self._insertion_visual_actors)
        self._insertion_slots.clear()
        self._insertion_callback = None
        self._insertion_mode = False
        self._hovered_insertion_actor = None
        self._active_insertion_slot = None
        self.clear_insertion_preview()
        if render:
            self.render()

    def enable_deletion_mode(self, callback: Callable[[PalletAxis, int, bool], None]) -> None:
        """Make only internal beams clickable and show selected ones in red."""
        self.disable_insertion_mode(render=False)
        self._deletion_mode = True
        self._deletion_callback = callback
        self._selected_deletion_actors.clear()
        self._hovered_deletion_actor = None
        self.render()

    def disable_deletion_mode(self, *, render: bool = True) -> None:
        if not self._deletion_mode and not self._selected_deletion_actors:
            return
        self.disable_picking()
        for actor in tuple(self._selected_deletion_actors):
            self._set_deletion_color(actor, selected=False)
        if self._hovered_deletion_actor and self._hovered_deletion_actor not in self._selected_deletion_actors:
            self._set_deletion_color(self._hovered_deletion_actor, selected=False)
        self._selected_deletion_actors.clear()
        self._deletion_callback = None
        self._deletion_mode = False
        self._hovered_deletion_actor = None
        if render:
            self.render()

    def _select_deletion_beam(self, actor) -> None:
        if not self._deletion_mode or actor not in self._beam_actors:
            return
        axis, index = self._beam_actors[actor]
        beam_count = self._beam_counts[axis]
        if index in (0, beam_count - 1):
            return
        selected = actor not in self._selected_deletion_actors
        if selected:
            self._selected_deletion_actors.add(actor)
        else:
            self._selected_deletion_actors.remove(actor)
        self._set_deletion_color(actor, selected)
        if not selected and actor == self._hovered_deletion_actor:
            self._set_deletion_hover_color(actor)
        if self._deletion_callback:
            self._deletion_callback(axis, index, selected)
        self.render()

    def _click_insertion(self, *_args) -> None:
        if not self._insertion_mode or self._active_insertion_slot is not None:
            return
        x, y = self.iren.get_event_position()
        self._mesh_picker.Pick(x, y, 0, self.renderer)
        self._select_insertion_slot(self._mesh_picker.GetActor())

    def _click_deletion(self, *_args) -> None:
        if not self._deletion_mode:
            return
        x, y = self.iren.get_event_position()
        self._mesh_picker.Pick(x, y, 0, self.renderer)
        self._select_deletion_beam(self._mesh_picker.GetActor())

    def _set_deletion_color(self, actor, selected: bool) -> None:
        axis, _ = self._beam_actors[actor]
        colors = self._interaction_colors
        color = colors["selected"] if selected else (colors["length_beam"] if axis == "width" else colors["width_beam"])
        edge_color = colors["selected_edge"] if selected else colors["default_edge"]
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetEdgeColor(*edge_color)

    def _set_deletion_hover_color(self, actor) -> None:
        if actor in self._selected_deletion_actors:
            actor.GetProperty().SetColor(*self._interaction_colors["selected_hover"])
            actor.GetProperty().SetEdgeColor(*self._interaction_colors["selected_hover_edge"])
        else:
            actor.GetProperty().SetColor(*self._interaction_colors["beam_hover"])
            actor.GetProperty().SetEdgeColor(*self._interaction_colors["beam_hover_edge"])

    def _update_deletion_hover(self, *_args) -> None:
        if not self._deletion_mode:
            return
        x, y = self.iren.get_event_position()
        self._prop_picker.Pick(x, y, 0, self.renderer)
        hovered = self._prop_picker.GetActor()
        if not self._is_removable_beam_actor(hovered):
            hovered = None
        if hovered == self._hovered_deletion_actor:
            return
        previous = self._hovered_deletion_actor
        self._hovered_deletion_actor = hovered
        if previous:
            self._set_deletion_color(previous, selected=previous in self._selected_deletion_actors)
        if hovered:
            self._set_deletion_hover_color(hovered)
        self.render()

    def _is_removable_beam_actor(self, actor) -> bool:
        if actor not in self._beam_actors:
            return False
        axis, index = self._beam_actors[actor]
        beam_count = self._beam_counts[axis]
        return 0 < index < beam_count - 1

    def enable_distance_editing(self, dimensions: tuple[EditableDimension, ...], callback: Callable[[PalletAxis, int, float], None]) -> None:
        """Overlay pickable internal dimension lines above the annotations."""
        self.disable_insertion_mode(render=False)
        self.disable_distance_editing(render=False)
        self._distance_editing_mode = True
        self._distance_callback = callback
        self._selected_distance_actor = None
        self._hovered_distance_actor = None
        for dimension in dimensions:
            actor = self.add_mesh(pv.Line(dimension.start, dimension.end), color="#d28326", line_width=14,
                                  opacity=0.01, pickable=True, name=f"editable-{dimension.axis}-dimension-{dimension.index}")
            self._distance_actors[actor] = (dimension.axis, dimension.index, dimension.value)
        self.render()

    def disable_distance_editing(self, *, render: bool = True) -> None:
        if not self._distance_editing_mode and not self._distance_actors:
            return
        self.disable_picking()
        for actor in self._distance_actors:
            self.remove_actor(actor, render=False)
        self._distance_actors.clear()
        self._distance_callback = None
        self._distance_editing_mode = False
        self._selected_distance_actor = None
        self._hovered_distance_actor = None
        if render:
            self.render()

    def _select_distance(self, actor) -> None:
        if not self._distance_editing_mode or actor not in self._distance_actors:
            return
        if self._selected_distance_actor and self._selected_distance_actor != actor:
            self._set_distance_color(self._selected_distance_actor, selected=False)
        self._selected_distance_actor = actor
        self._set_distance_color(actor, selected=True)
        axis, index, value = self._distance_actors[actor]
        if self._distance_callback:
            self._distance_callback(axis, index, value)
        self.render()

    def _click_distance(self, *_args) -> None:
        """Pick dimensions directly; PyVista mesh-picking ignores line actors on some VTK backends."""
        if not self._distance_editing_mode:
            return
        x, y = self.iren.get_event_position()
        self._prop_picker.Pick(x, y, 0, self.renderer)
        actor = self._prop_picker.GetActor()
        if actor in self._distance_actors:
            self._select_distance(actor)

    def _update_distance_hover(self, *_args) -> None:
        if not self._distance_editing_mode or not self._distance_actors:
            return
        x, y = self.iren.get_event_position()
        self._prop_picker.Pick(x, y, 0, self.renderer)
        hovered = self._prop_picker.GetActor()
        if hovered not in self._distance_actors:
            hovered = None
        if hovered == self._hovered_distance_actor:
            return
        previous = self._hovered_distance_actor
        self._hovered_distance_actor = hovered
        if previous and previous != self._selected_distance_actor:
            self._set_distance_color(previous, selected=False)
        if hovered and hovered != self._selected_distance_actor:
            hovered.GetProperty().SetColor(*self._interaction_colors["distance"])
            hovered.GetProperty().SetOpacity(0.95)
        self.render()

    def _set_distance_color(self, actor, selected: bool) -> None:
        color = self._interaction_colors["distance_selected" if selected else "distance"]
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(0.95 if selected else 0.01)

    def show_insertion_preview(self, preview: PreviewBox) -> None:
        """Draw a translucent candidate beam without committing it to the model."""
        self.clear_insertion_preview()
        cube = pv.Cube(center=preview.center, x_length=preview.size[0], y_length=preview.size[1], z_length=preview.size[2])
        self.add_mesh(cube, color="#23908a", opacity=0.46, show_edges=True, edge_color="#155854",
                      name="insertion-preview")
        self.render()

    def clear_insertion_preview(self) -> None:
        self.remove_actor("insertion-preview", render=False)

    def clear_insertion_selection(self) -> None:
        """Return insertion mode to hovering slots after an editor is closed."""
        self._active_insertion_slot = None

    def _select_insertion_slot(self, actor) -> None:
        for marker, slot in self._insertion_slots.items():
            if marker == actor:
                self._active_insertion_slot = slot
                # One insertion is confirmed at a time. Hide stale markers
                # while its editor is open; the mode rebuilds fresh ones after
                # confirmation.
                for hitbox in tuple(self._insertion_slots):
                    self.remove_actor(hitbox, render=False)
                self._insertion_slots.clear()
                self._remove_actors(self._insertion_visual_actors)
                if self._insertion_callback:
                    self._insertion_callback(slot.slot)
                self.render()
                return

    def _update_insertion_hover(self, *_args) -> None:
        if not self._insertion_mode or not self._insertion_slots or self._active_insertion_slot is not None:
            return
        x, y = self.iren.get_event_position()
        self._prop_picker.Pick(x, y, 0, self.renderer)
        hovered = self._prop_picker.GetActor()
        if hovered not in self._insertion_slots:
            hovered = None
        if hovered == self._hovered_insertion_actor:
            return
        self._hovered_insertion_actor = hovered
        for actor in self._insertion_slots:
            actor.GetProperty().SetOpacity(0.6 if actor == hovered else 0.35)
        if hovered:
            self.show_insertion_preview(self._insertion_slots[hovered].preview)
        else:
            self.clear_insertion_preview()
        self.render()

    @staticmethod
    def _display_y(result: PalletResult, y: float) -> float:
        """Mirror only the visual Y axis so calculated (0, 0) is upper-left."""
        return result.pallet_width - y

    def _add_dimension_segment(
        self, start: tuple[float, float, float], end: tuple[float, float, float], name: str
    ) -> None:
        """Draw one independent gap line; never form a continuous outer rail."""
        if self._annotation_segments is not None:
            self._annotation_segments.append(pv.Line(start, end))
            return
        actor = self.add_mesh(pv.Line(start, end), color="#3d8582", line_width=2, name=name, reset_camera=False)
        self._annotation_actors.append(actor)

    def _begin_annotation_batch(self) -> None:
        self._annotation_segments = []

    def _flush_annotation_batch(self, name: str) -> None:
        segments = self._annotation_segments
        self._annotation_segments = None
        if not segments:
            return
        actor = self.add_mesh(
            pv.merge(segments, merge_points=False), color="#3d8582", line_width=2, name=name, reset_camera=False
        )
        self._annotation_actors.append(actor)

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
        batching = isinstance(self, PalletView)
        if batching:
            self._begin_annotation_batch()
        direction = result.length_result
        offset = max(50.0, result.pallet_width * 0.055)
        tick = max(14.0, offset * 0.18)
        base = direction.beam_centers[0] - direction.beam_width / 2
        model_edge_y, z = 0.0, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        last_index = len(direction.beam_centers) - 1
        for index, center in enumerate(direction.beam_centers[1:], start=1):
            is_last_beam = index == last_index
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
        if batching:
            self._flush_annotation_batch("length-dimension-lines")
        actor = self.add_point_labels(points, labels, name="length-dimension-labels", show_points=False, font_size=12,
                                      text_color="#173f45", shape_color="#fffdf9", shape_opacity=0.88,
                                      fill_shape=True, always_visible=True, reset_camera=False)
        if hasattr(self, "_annotation_actors"):
            self._annotation_actors.append(actor)

    def _add_width_gap_dimensions(self, result: PalletResult) -> None:
        """Place stepped Y dimensions: inner faces, then the final outer face."""
        batching = isinstance(self, PalletView)
        if batching:
            self._begin_annotation_batch()
        direction = result.width_result
        offset = max(50.0, result.pallet_length * 0.035)
        tick = max(14.0, offset * 0.18)
        base = direction.beam_centers[0] - direction.beam_width / 2
        model_edge_x, z = 0.0, result.pallet_height + 2
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        last_index = len(direction.beam_centers) - 1
        for index, center in enumerate(direction.beam_centers[1:], start=1):
            is_last_beam = index == last_index
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
        if batching:
            self._flush_annotation_batch("width-dimension-lines")
        actor = self.add_point_labels(points, labels, name="width-dimension-labels", show_points=False, font_size=12,
                                      text_color="#173f45", shape_color="#fffdf9", shape_opacity=0.88,
                                      fill_shape=True, always_visible=True, reset_camera=False)
        if hasattr(self, "_annotation_actors"):
            self._annotation_actors.append(actor)

    def camera_isometric(self) -> None:
        # Turn the prior isometric view clockwise by one quarter turn: length
        # dimensions are above the pallet and width dimensions are to its left.
        self.view_vector((-1, -1, 1), viewup=(0, 0, 1))
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
