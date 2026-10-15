"""PyVista viewport that consumes only pre-calculated Beam3D geometry."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from PyQt5.QtCore import QTimer
import numpy as np
import pyvista as pv
from pyvistaqt import QtInteractor

from palletlab.core.formatting import format_mm
from palletlab.core.models import InsertionSlot, PalletAxis, PalletResult
from palletlab.controllers.viewport_geometry import EditableDimension, InsertionMarker, PreviewBox, beam_faces, editable_dimensions


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
        self._annotation_key: tuple[object, bool, bool, object] | None = None
        self._insertion_slots: dict[object, InsertionMarker] = {}
        self._insertion_visual_actors: list[object] = []
        self._insertion_callback: Callable[[object], None] | None = None
        self._insertion_mode = False
        self._hovered_insertion_actor = None
        self._active_insertion_slot: InsertionSlot | None = None
        # actor -> (layer id, axis, index in that layer).  The former
        # (axis, index) key becomes ambiguous as soon as two layers share an
        # axis, so every editor uses the physical layer identity.
        self._beam_actors: dict[object, tuple[str, PalletAxis, int]] = {}
        # Physical geometry keyed by its stable layer/index identity.  It lets
        # a normal recalculation replace only beams that actually changed.
        self._beam_actor_by_key: dict[tuple[str, int], object] = {}
        self._beam_specs: dict[tuple[str, int], object] = {}
        self._beam_counts: dict[str, int] = {}
        self._deletion_callback: Callable[[str, int, bool], bool] | None = None
        self._deletion_mode = False
        self._selected_deletion_actors: set[object] = set()
        self._hovered_deletion_actor = None
        self._section_callback: Callable[[str, int, bool], None] | None = None
        self._section_editing_mode = False
        self._selected_section_actors: set[object] = set()
        self._hovered_section_actor = None
        self._support_pick_callback: Callable[[str, int, str], None] | None = None
        self._support_pick_mode = False
        self._support_pick_all_faces = False
        self._hovered_support_actor = None
        self._hovered_support_face: str | None = None
        self._support_face_hover_actor = None
        self._distance_actors: dict[object, tuple[str, PalletAxis, int, float]] = {}
        self._distance_visual_actors: dict[object, object] = {}
        self._distance_callback: Callable[[str, int, float], None] | None = None
        self._distance_editing_mode = False
        self._selected_distance_actor = None
        self._hovered_distance_actor = None
        self._step_mesh: pv.PolyData | None = None
        self._step_edges: pv.PolyData | None = None
        self._step_model_actor = None
        self._step_edge_actor = None
        self._rendered_step_mesh: pv.PolyData | None = None
        self._step_model_visible = True
        self._step_faces = ()
        self._support_callback: Callable[[int], None] | None = None
        self._support_face_indices: set[int] = set()
        self._reference_support_index: int | None = None
        self._step_face_cell_indices: dict[int, np.ndarray] = {}
        self._hovered_step_face_index: int | None = None
        self._step_hover_actor = None
        self._step_hover_selector = pv._vtk.vtkOpenGLHardwareSelector()
        self._step_hover_selector.SetFieldAssociation(pv._vtk.vtkDataObject.FIELD_ASSOCIATION_CELLS)
        self._step_hover_selector.SetRenderer(self.renderer)
        self._last_step_hover_pick_at = float("-inf")
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
            "section_selected": pv.Color("#247ba0").float_rgb,
            "section_selected_edge": pv.Color("#124c67").float_rgb,
            "section_hover": pv.Color("#55b6d9").float_rgb,
            "section_hover_edge": pv.Color("#216f8d").float_rgb,
        }
        self.iren.add_observer("MouseMoveEvent", self._update_insertion_hover)
        self.iren.add_observer("MouseMoveEvent", self._update_deletion_hover)
        self.iren.add_observer("MouseMoveEvent", self._update_section_hover)
        self.iren.add_observer("MouseMoveEvent", self._update_distance_hover)
        self.iren.add_observer("MouseMoveEvent", self._update_step_face_hover)
        self.iren.add_observer("LeftButtonPressEvent", self._click_distance)
        self.iren.add_observer("LeftButtonPressEvent", self._click_insertion)
        self.iren.add_observer("LeftButtonPressEvent", self._click_deletion)
        self.iren.add_observer("LeftButtonPressEvent", self._click_section)
        self.iren.add_observer("LeftButtonPressEvent", self._click_support_face)
        self.iren.add_observer("MouseMoveEvent", self._update_support_face_hover)
        self.iren.add_observer("LeftButtonPressEvent", self._pick_step_face)

    def show_pallet(
        self, result: PalletResult, show_length_gaps: bool = True, show_width_gaps: bool = True, *,
        dimensions: tuple[EditableDimension, ...] | None = None,
    ) -> None:
        camera_position = self.camera_position if self._has_model else None
        # Keep the STEP actor and unchanged pallet beams in the renderer.
        # Recreating the complete scene made large models flash while also
        # discarding a camera position the user had already chosen.
        if self._has_beam_changes(result):
            self._clear_interaction_overlays()
        self._sync_beam_actors(result)
        self._beam_counts = {}
        for beam in result.beams_3d:
            layer_id = beam.layer_id or beam.orientation
            self._beam_counts[layer_id] = max(self._beam_counts.get(layer_id, 0), beam.layer_index + 1)
        self.update_dimension_annotations(result, show_length_gaps, show_width_gaps, render=False, dimensions=dimensions)
        self._ensure_axes()
        self._sync_step_model_actor()
        if camera_position is None:
            self.camera_isometric()
        else:
            self.camera_position = camera_position
            self.render()
        self._has_model = True

    def _sync_beam_actors(self, result: PalletResult) -> bool:
        """Keep unchanged beam actors and replace only changed geometry."""
        desired = self._desired_beam_specs(result)
        changed_keys = self._changed_beam_keys(self._beam_specs, desired)
        changed = False
        for key, actor in tuple(self._beam_actor_by_key.items()):
            if key not in changed_keys:
                continue
            self.remove_actor(actor, render=False)
            self._beam_actor_by_key.pop(key, None)
            self._beam_specs.pop(key, None)
            self._beam_actors.pop(actor, None)
            changed = True
        for beam in result.beams_3d:
            key = (beam.layer_id or beam.orientation, beam.layer_index)
            if key in self._beam_actor_by_key:
                continue
            cube = self._beam_cube(result, beam)
            color = "#b7791f" if beam.orientation == "length" else "#8b5a2b"
            actor = self.add_mesh(
                cube, color=color, show_edges=True, edge_color="#4a2c12",
                # A global enumerate index changes as soon as any preceding
                # beam is removed.  PyVista treats a repeated ``name`` as a
                # replacement, which used to make an unselected beam vanish
                # while the actor registry still referenced it.  This name is
                # the same stable identity used by the registry instead.
                smooth_shading=False, pickable=True,
                name=self._beam_actor_name(key), reset_camera=False,
            )
            axis: PalletAxis = "length" if beam.orientation == "width" else "width"
            self._beam_actor_by_key[key] = actor
            self._beam_specs[key] = beam
            self._beam_actors[actor] = (key[0], axis, beam.layer_index)
            changed = True
        return changed

    @staticmethod
    def _beam_actor_name(key: tuple[str, int]) -> str:
        """Return an actor name invariant under insertions in other layers."""
        layer_id, index = key
        return f"pallet-beam-{layer_id}-{index}"

    @staticmethod
    def _desired_beam_specs(result: PalletResult) -> dict[tuple[str, int], object]:
        return {
            (beam.layer_id or beam.orientation, beam.layer_index): beam
            for beam in result.beams_3d
        }

    def _has_beam_changes(self, result: PalletResult) -> bool:
        return bool(self._changed_beam_keys(self._beam_specs, self._desired_beam_specs(result)))

    @staticmethod
    def _changed_beam_keys(previous: dict[tuple[str, int], object], desired: dict[tuple[str, int], object]) -> set[tuple[str, int]]:
        """Return only actor identities whose geometry was added, removed or changed."""
        return {
            key for key in previous.keys() | desired.keys()
            if previous.get(key) != desired.get(key)
        }

    def _clear_interaction_overlays(self) -> None:
        """Remove transient picking actors before changed beams are replaced."""
        self.disable_insertion_mode(render=False)
        self.disable_deletion_mode(render=False)
        self.disable_section_editing(render=False)
        self.disable_distance_editing(render=False)
        self.disable_support_face_selection(render=False)

    def _clear_pallet_actors(self) -> None:
        """Replace pallet-only actors without disturbing the STEP preview."""
        self._clear_interaction_overlays()
        self._remove_actors(list(self._beam_actors))
        self._beam_actors.clear()
        self._beam_actor_by_key.clear()
        self._beam_specs.clear()
        self._remove_actors(self._annotation_actors)
        self.remove_actor("length-dimension-labels-points", render=False)
        self.remove_actor("width-dimension-labels-points", render=False)
        self._annotation_segments = None
        self._annotation_key = None

    def _ensure_axes(self) -> None:
        if self._axes_added:
            return
        self.add_axes(line_width=1, xlabel="X", ylabel="Y", zlabel="Z", viewport=(0, 0, 0.13, 0.13))
        self._axes_added = True

    def clear_workspace(self) -> None:
        """Remove scene objects without resetting the renderer's lighting palette."""
        # ``QtInteractor.clear`` recreates renderer state.  That subtly changes
        # the apparent timber colours after Reset even though every beam has
        # the same RGB value.  Remove only our actors so a reset looks exactly
        # like the pallet that was already on screen.
        self._clear_pallet_actors()
        self.remove_actor("step-model", render=False)
        self.remove_actor("step-model-edges", render=False)
        self._remove_step_hover_face()
        self._annotation_key = None
        self._distance_actors.clear()
        self._distance_visual_actors.clear()
        self._step_mesh = None
        self._step_edges = None
        self._step_model_actor = None
        self._step_edge_actor = None
        self._rendered_step_mesh = None
        self._step_faces = ()
        self._support_callback = None
        self._support_face_indices.clear()
        self._reference_support_index = None
        self._step_face_cell_indices.clear()
        self._hovered_step_face_index = None
        self._last_step_hover_pick_at = float("-inf")
        self._has_model = False
        self._ensure_axes()
        self.render()

    def clear_step_model(self) -> None:
        """Forget only the imported machine while leaving a pallet render intact."""
        self._remove_step_hover_face()
        self.remove_actor("step-model", render=False)
        self.remove_actor("step-model-edges", render=False)
        self._step_mesh = None
        self._step_edges = None
        self._step_model_actor = None
        self._step_edge_actor = None
        self._rendered_step_mesh = None
        self._step_faces = ()
        self._support_callback = None
        self._support_face_indices.clear()
        self._reference_support_index = None
        self._step_face_cell_indices.clear()
        self._hovered_step_face_index = None
        self._last_step_hover_pick_at = float("-inf")
        self._step_model_visible = True
        self.render()

    def prepare_step_model_rebuild(self, callback: Callable[[int], None]) -> None:
        """Remove only pallet geometry and re-enable support picking on the visible model."""
        self._clear_pallet_actors()
        self._beam_counts = {"length": 0, "width": 0}
        self._remove_actors(self._annotation_actors)
        self.remove_actor("length-dimension-labels-points", render=False)
        self.remove_actor("width-dimension-labels-points", render=False)
        self._remove_actors([*self._distance_actors, *self._distance_visual_actors.values()])
        self._distance_actors.clear()
        self._distance_visual_actors.clear()
        self._support_callback = callback
        self._support_face_indices.clear()
        self._reference_support_index = None
        self._hovered_step_face_index = None
        self._remove_step_hover_face()
        self._last_step_hover_pick_at = float("-inf")
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
        self._last_step_hover_pick_at = float("-inf")
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
        now = monotonic()
        # Hardware selection forces a render-pipeline pass.  Mouse events can
        # arrive much faster than a user can perceive a changed highlight.
        if now - self._last_step_hover_pick_at < 1 / 30:
            return
        self._last_step_hover_pick_at = now
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
        selector = self._step_hover_selector
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
        self._rendered_step_mesh = self._step_mesh
        if render:
            self.render()

    def _sync_step_model_actor(self) -> None:
        """Refresh STEP geometry without rendering an intermediate empty scene."""
        if self._step_mesh is None:
            return
        if self._step_model_actor is not None and self._rendered_step_mesh is self._step_mesh:
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
            QTimer.singleShot(0, self._stop_left_button_interaction)

    def _stop_left_button_interaction(self) -> None:
        """Release a VTK interaction left active when a tool opens or closes a dialog."""
        style = self.iren.interactor.GetInteractorStyle()
        style.OnLeftButtonUp()
        style.StopState()

    def update_dimension_annotations(
        self, result: PalletResult, show_length_gaps: bool = True, show_width_gaps: bool = True, *, render: bool = True,
        dimensions: tuple[EditableDimension, ...] | None = None,
    ) -> None:
        """Refresh only the distance annotations, leaving beam geometry intact."""
        key = (result, show_length_gaps, show_width_gaps, dimensions)
        if key == self._annotation_key:
            if render:
                self.render()
            return
        self._remove_actors(self._annotation_actors)
        # ``add_point_labels`` owns an additional ``<name>-points`` actor.
        # It is not returned to us, so remove it by name when hiding or
        # replacing dimensions created by older renders.
        self.remove_actor("length-dimension-labels-points", render=False)
        self.remove_actor("width-dimension-labels-points", render=False)
        if show_length_gaps:
            self._add_length_gap_dimensions(result, dimensions)
        if show_width_gaps:
            self._add_width_gap_dimensions(result, dimensions)
        self._annotation_key = key
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
            layer_id = item.slot.layer_id or item.slot.axis
            marker = pv.Text3D("+", height=item.size, depth=1, center=item.center)
            visual = self.add_mesh(marker, color="#1f7775", opacity=0.7, pickable=False,
                                   name=f"insert-symbol-{layer_id}-{item.slot.after_beam_index}")
            self._insertion_visual_actors.append(visual)
            hit_size = max(48.0, item.size * 2.4)
            hitbox = pv.Cube(center=item.center, x_length=hit_size, y_length=hit_size,
                             z_length=max(12.0, item.size * 0.35))
            actor = self.add_mesh(hitbox, opacity=0.01, pickable=True,
                                  name=f"insert-slot-{layer_id}-{item.slot.after_beam_index}")
            self._insertion_slots[actor] = item
        self.render()

    def disable_insertion_mode(self, *, render: bool = True) -> None:
        """Remove insertion affordances while preserving the currently displayed pallet."""
        was_active = self._insertion_mode or bool(self._insertion_slots)
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
        if was_active:
            QTimer.singleShot(0, self._stop_left_button_interaction)
        if render:
            self.render()

    def enable_deletion_mode(self, callback: Callable[[str, int, bool], bool]) -> None:
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
        if not self._deletion_mode or not self._is_removable_beam_actor(actor):
            return
        layer_id, _axis, index = self._beam_actors[actor]
        selected = actor not in self._selected_deletion_actors
        if selected:
            self._selected_deletion_actors.add(actor)
        else:
            self._selected_deletion_actors.remove(actor)
        self._set_deletion_color(actor, selected)
        if not selected and actor == self._hovered_deletion_actor:
            self._set_deletion_hover_color(actor)
        if self._deletion_callback and not self._deletion_callback(layer_id, index, selected):
            # The controller declined a stale identity.  Restore the actor
            # immediately so the red visual selection never disagrees with
            # the exact transaction that will be confirmed.
            if selected:
                self._selected_deletion_actors.remove(actor)
            else:
                self._selected_deletion_actors.add(actor)
            self._set_deletion_color(actor, selected=not selected)
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
        _layer_id, axis, _ = self._beam_actors[actor]
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
        return actor in self._beam_actors

    def enable_section_editing(self, callback: Callable[[str, int, bool], None]) -> None:
        """Make every beam selectable for a cross-section replacement."""
        self.disable_insertion_mode(render=False)
        self.disable_deletion_mode(render=False)
        self.disable_distance_editing(render=False)
        self._section_editing_mode = True
        self._section_callback = callback
        self._selected_section_actors.clear()
        self._hovered_section_actor = None
        self.render()

    def enable_support_face_selection(self, callback: Callable[[str, int, str], None]) -> None:
        """Pick upward or downward beam faces for creating a manual beam."""
        self.disable_insertion_mode(render=False)
        self.disable_deletion_mode(render=False)
        self.disable_section_editing(render=False)
        self.disable_distance_editing(render=False)
        self._support_pick_callback = callback
        self._support_pick_mode = True
        self._support_pick_all_faces = False
        self._hovered_support_actor = None
        self._hovered_support_face = None
        self._remove_support_face_hover()
        self.render()

    def enable_beam_face_selection(self, callback: Callable[[str, int, str], None]) -> None:
        """Select any face of a beam, including lateral faces for a reference."""
        self.enable_support_face_selection(callback)
        self._support_pick_all_faces = True

    def disable_support_face_selection(self, *, render: bool = True) -> None:
        was_active = self._support_pick_mode
        if self._hovered_support_actor is not None:
            self._restore_support_actor(self._hovered_support_actor)
        self._remove_support_face_hover()
        self._support_pick_callback = None
        self._support_pick_mode = False
        self._support_pick_all_faces = False
        self._hovered_support_actor = None
        self._hovered_support_face = None
        if was_active:
            # Selecting a support can open a modal dialog before VTK receives
            # its corresponding mouse-release event.  End the pending press
            # explicitly so the next mouse move cannot rotate the pallet.
            QTimer.singleShot(0, self._stop_left_button_interaction)
        if render:
            self.render()

    def _click_support_face(self, *_args) -> None:
        if not self._support_pick_mode:
            return
        x, y = self.iren.get_event_position()
        self._mesh_picker.Pick(x, y, 0, self.renderer)
        actor = self._mesh_picker.GetActor()
        if actor not in self._beam_actors:
            return
        face = self._picked_beam_face(actor)
        if face is None or (not self._support_pick_all_faces and face not in ("top", "bottom")):
            return
        layer_id, _axis, index = self._beam_actors[actor]
        if self._support_pick_callback:
            self._support_pick_callback(layer_id, index, face)

    def _restore_support_actor(self, actor) -> None:
        if actor not in self._beam_actors:
            return
        _layer_id, axis, _index = self._beam_actors[actor]
        actor.GetProperty().SetColor(*(self._interaction_colors["length_beam"] if axis == "width" else self._interaction_colors["width_beam"]))
        actor.GetProperty().SetEdgeColor(*self._interaction_colors["default_edge"])

    def _update_support_face_hover(self, *_args) -> None:
        if not self._support_pick_mode:
            return
        x, y = self.iren.get_event_position()
        self._mesh_picker.Pick(x, y, 0, self.renderer)
        hovered = self._mesh_picker.GetActor()
        face = self._picked_beam_face(hovered) if hovered in self._beam_actors else None
        if not self._support_pick_all_faces and face not in ("top", "bottom"):
            hovered, face = None, None
        if hovered == self._hovered_support_actor and face == getattr(self, "_hovered_support_face", None):
            return
        if self._hovered_support_actor is not None:
            self._restore_support_actor(self._hovered_support_actor)
        self._hovered_support_actor = hovered
        self._hovered_support_face = face
        self._remove_support_face_hover()
        if hovered is not None:
            hovered.GetProperty().SetColor(*self._interaction_colors["section_hover"])
            hovered.GetProperty().SetEdgeColor(*self._interaction_colors["section_hover_edge"])
            self._show_support_face_hover(hovered, face)
        self.render()

    def _picked_beam_face(self, actor) -> str | None:
        """Return the face closest to the current cell-picker hit, if any."""
        if actor not in self._beam_actors:
            return None
        bounds = actor.GetBounds()
        picked = self._mesh_picker.GetPickPosition()
        candidates = {
            "top": abs(picked[2] - bounds[5]), "bottom": abs(picked[2] - bounds[4]),
            "x_min": abs(picked[0] - bounds[0]), "x_max": abs(picked[0] - bounds[1]),
            "y_min": abs(picked[1] - bounds[2]), "y_max": abs(picked[1] - bounds[3]),
        }
        face = min(candidates, key=candidates.get)
        tolerance = max(1.0, max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 0.02)
        return face if candidates[face] <= tolerance else None

    def _show_support_face_hover(self, actor, face: str) -> None:
        """Overlay just the picked beam face instead of only tinting its body."""
        bounds = actor.GetBounds()
        thickness = max(0.5, min(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 0.025)
        x_min, x_max, y_min, y_max, z_min, z_max = bounds
        if face == "x_min":
            patch_bounds = (x_min - thickness, x_min + thickness, y_min, y_max, z_min, z_max)
        elif face == "x_max":
            patch_bounds = (x_max - thickness, x_max + thickness, y_min, y_max, z_min, z_max)
        elif face == "y_min":
            patch_bounds = (x_min, x_max, y_min - thickness, y_min + thickness, z_min, z_max)
        elif face == "y_max":
            patch_bounds = (x_min, x_max, y_max - thickness, y_max + thickness, z_min, z_max)
        elif face == "bottom":
            patch_bounds = (x_min, x_max, y_min, y_max, z_min - thickness, z_min + thickness)
        else:
            patch_bounds = (x_min, x_max, y_min, y_max, z_max - thickness, z_max + thickness)
        self._support_face_hover_actor = self.add_mesh(
            pv.Box(bounds=patch_bounds), color="#33b9ae", opacity=0.70,
            show_edges=True, edge_color="#147b75", line_width=2.0,
            pickable=False, name="beam-face-hover", reset_camera=False,
        )

    def _remove_support_face_hover(self) -> None:
        if self._support_face_hover_actor is not None:
            self.remove_actor(self._support_face_hover_actor, render=False)
        self._support_face_hover_actor = None

    def disable_section_editing(self, *, render: bool = True) -> None:
        if not self._section_editing_mode and not self._selected_section_actors:
            return
        self.disable_picking()
        for actor in tuple(self._selected_section_actors):
            self._set_section_color(actor, selected=False)
        if self._hovered_section_actor and self._hovered_section_actor not in self._selected_section_actors:
            self._set_section_color(self._hovered_section_actor, selected=False)
        self._selected_section_actors.clear()
        self._section_callback = None
        self._section_editing_mode = False
        self._hovered_section_actor = None
        if render:
            self.render()

    def _click_section(self, *_args) -> None:
        if not self._section_editing_mode:
            return
        x, y = self.iren.get_event_position()
        self._mesh_picker.Pick(x, y, 0, self.renderer)
        actor = self._mesh_picker.GetActor()
        if actor not in self._beam_actors:
            return
        layer_id, _axis, index = self._beam_actors[actor]
        selected = actor not in self._selected_section_actors
        if selected:
            self._selected_section_actors.add(actor)
        else:
            self._selected_section_actors.remove(actor)
        self._set_section_color(actor, selected=selected)
        if not selected and actor == self._hovered_section_actor:
            self._set_section_hover_color(actor)
        if self._section_callback:
            self._section_callback(layer_id, index, selected)
        self.render()

    def _set_section_color(self, actor, *, selected: bool) -> None:
        _layer_id, axis, _ = self._beam_actors[actor]
        colors = self._interaction_colors
        actor.GetProperty().SetColor(*(colors["section_selected"] if selected else (
            colors["length_beam"] if axis == "width" else colors["width_beam"]
        )))
        actor.GetProperty().SetEdgeColor(*(colors["section_selected_edge"] if selected else colors["default_edge"]))

    def _set_section_hover_color(self, actor) -> None:
        if actor in self._selected_section_actors:
            actor.GetProperty().SetColor(*self._interaction_colors["section_hover"])
            actor.GetProperty().SetEdgeColor(*self._interaction_colors["section_hover_edge"])
        else:
            actor.GetProperty().SetColor(*self._interaction_colors["beam_hover"])
            actor.GetProperty().SetEdgeColor(*self._interaction_colors["beam_hover_edge"])

    def _update_section_hover(self, *_args) -> None:
        if not self._section_editing_mode:
            return
        x, y = self.iren.get_event_position()
        self._prop_picker.Pick(x, y, 0, self.renderer)
        hovered = self._prop_picker.GetActor()
        if hovered not in self._beam_actors:
            hovered = None
        if hovered == self._hovered_section_actor:
            return
        previous = self._hovered_section_actor
        self._hovered_section_actor = hovered
        if previous:
            self._set_section_color(previous, selected=previous in self._selected_section_actors)
        if hovered:
            self._set_section_hover_color(hovered)
        self.render()

    def enable_distance_editing(self, dimensions: tuple[EditableDimension, ...], callback: Callable[[str, int, float], None]) -> None:
        """Overlay pickable internal dimension lines above the annotations."""
        self.disable_insertion_mode(render=False)
        self.disable_distance_editing(render=False)
        self._distance_editing_mode = True
        self._distance_callback = callback
        self._selected_distance_actor = None
        self._hovered_distance_actor = None
        # Annotation lines occupy the same coordinates as the editable
        # overlays.  Limit the cell picker to the overlays so it cannot pick
        # the decorative line actor first and silently ignore the click.
        self._mesh_picker.InitializePickList()
        self._mesh_picker.PickFromListOn()
        for dimension in dimensions:
            start = (dimension.start[0], dimension.start[1], dimension.start[2] + 0.5)
            end = (dimension.end[0], dimension.end[1], dimension.end[2] + 0.5)
            visual = self.add_mesh(pv.Line(start, end), color="#d28326", line_width=14,
                                   opacity=0.14, pickable=False,
                                   name=f"editable-{dimension.layer_id}-dimension-{dimension.index}")
            # Keep the visible yellow backing unchanged.  The separate
            # transparent tube is only a forgiving click target around it.
            hitbox = self.add_mesh(
                pv.Line(start, end).tube(radius=16.0, n_sides=8), color="#d28326", scalars=None,
                show_scalar_bar=False, opacity=0.001, pickable=True,
                name=f"editable-hitbox-{dimension.layer_id}-dimension-{dimension.index}",
            )
            self._mesh_picker.AddPickList(hitbox)
            self._distance_actors[hitbox] = (
                dimension.layer_id, dimension.axis, dimension.index,
                dimension.edit_value if dimension.edit_value is not None else dimension.value,
            )
            self._distance_visual_actors[hitbox] = visual
        self.render()

    def disable_distance_editing(self, *, render: bool = True) -> None:
        if not self._distance_editing_mode and not self._distance_actors:
            return
        self.disable_picking()
        for actor in self._distance_actors:
            self.remove_actor(actor, render=False)
        for actor in self._distance_visual_actors.values():
            self.remove_actor(actor, render=False)
        self._distance_actors.clear()
        self._distance_visual_actors.clear()
        self._mesh_picker.InitializePickList()
        self._mesh_picker.PickFromListOff()
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
        layer_id, _axis, index, value = self._distance_actors[actor]
        if self._distance_callback:
            self._distance_callback(layer_id, index, value)
        self.render()

    def _click_distance(self, *_args) -> None:
        """Select a dimension only when its actual line geometry is under the cursor."""
        if not self._distance_editing_mode:
            return
        x, y = self.iren.get_event_position()
        self._mesh_picker.Pick(x, y, 0, self.renderer)
        actor = self._mesh_picker.GetActor()
        if actor in self._distance_actors:
            self._select_distance(actor)

    def _update_distance_hover(self, *_args) -> None:
        if not self._distance_editing_mode or not self._distance_actors:
            return
        x, y = self.iren.get_event_position()
        self._mesh_picker.Pick(x, y, 0, self.renderer)
        hovered = self._mesh_picker.GetActor()
        if hovered not in self._distance_actors:
            hovered = None
        if hovered == self._hovered_distance_actor:
            return
        previous = self._hovered_distance_actor
        self._hovered_distance_actor = hovered
        if previous and previous != self._selected_distance_actor:
            self._set_distance_color(previous, selected=False)
        if hovered and hovered != self._selected_distance_actor:
            visual = self._distance_visual_actors.get(hovered, hovered)
            visual.GetProperty().SetColor(*self._interaction_colors["distance"])
            visual.GetProperty().SetOpacity(0.95)
        self.render()

    def _set_distance_color(self, actor, selected: bool) -> None:
        actor = self._distance_visual_actors.get(actor, actor)
        color = self._interaction_colors["distance_selected" if selected else "distance"]
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(0.95 if selected else 0.14)

    def show_insertion_preview(self, preview: PreviewBox, *, render: bool = True) -> None:
        """Draw a translucent candidate beam without committing it to the model."""
        self.clear_insertion_preview()
        cube = pv.Cube(center=preview.center, x_length=preview.size[0], y_length=preview.size[1], z_length=preview.size[2])
        self.add_mesh(cube, color="#23908a", opacity=0.46, show_edges=True, edge_color="#155854",
                      name="insertion-preview")
        if render:
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
            self.show_insertion_preview(self._insertion_slots[hovered].preview, render=False)
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

    def _add_length_gap_dimensions(
        self, result: PalletResult, dimensions: tuple[EditableDimension, ...] | None = None,
    ) -> None:
        """Draw every visible X dimension, including each same-direction layer."""
        if not isinstance(self, PalletView):
            # Keep this geometry-only path usable by the lightweight recorder
            # tests and other non-Qt consumers of the drawing helpers.
            direction = result.length_result
            faces = beam_faces(result, "length")
            offset = max(50.0, result.pallet_width * 0.055)
            tick = max(14.0, offset * 0.18)
            base = faces[0][0]
            z = result.pallet_height + 2
            points: list[tuple[float, float, float]] = []
            labels: list[str] = []
            last_index = len(direction.beam_centers) - 1
            for index in range(1, len(direction.beam_centers)):
                end = faces[index][1] if index == last_index else faces[index][0]
                display_y = self._display_y(result, -offset * index)
                self._add_dimension_segment((base, display_y, z), (end, display_y, z), f"length-dimension-{index}")
                self._add_t_end((base, display_y, z), "y", tick, f"length-start-tick-{index}")
                self._add_t_end((end, display_y, z), "y", tick, f"length-end-tick-{index}")
                points.append(((base + end) / 2, display_y, z))
                labels.append(f"{format_mm(end - base)} mm")
            self.add_point_labels(points, labels, name="length-dimension-labels", show_points=False)
            return
        self._add_editable_dimension_annotations(result, "length", dimensions)

    def _add_width_gap_dimensions(
        self, result: PalletResult, dimensions: tuple[EditableDimension, ...] | None = None,
    ) -> None:
        """Draw every visible Y dimension, including each same-direction layer."""
        self._add_editable_dimension_annotations(result, "width", dimensions)

    def _add_editable_dimension_annotations(
        self, result: PalletResult, axis: PalletAxis, dimensions: tuple[EditableDimension, ...] | None = None,
    ) -> None:
        """Render exactly the lines used by the distance-editing picker.

        Previously the editor generated handles for every layer, while the
        drawing showed labels only for the two legacy layers.  Extra-layer
        handles were therefore invisible and felt like selectable "ghost"
        distances.  Keeping both views derived from ``editable_dimensions``
        makes every selectable measurement visible first.
        """
        dimensions = tuple(dimension for dimension in (dimensions or editable_dimensions(result)) if dimension.axis == axis)
        if not dimensions:
            return
        self._begin_annotation_batch()
        tick = max(14.0, min(result.pallet_length, result.pallet_width) * 0.01)
        points: list[tuple[float, float, float]] = []
        labels: list[str] = []
        for dimension in dimensions:
            self._add_dimension_segment(dimension.start, dimension.end, f"{dimension.layer_id}-dimension-{dimension.index}")
            perpendicular = "y" if axis == "length" else "x"
            self._add_t_end(dimension.start, perpendicular, tick, f"{dimension.layer_id}-start-tick-{dimension.index}")
            self._add_t_end(dimension.end, perpendicular, tick, f"{dimension.layer_id}-end-tick-{dimension.index}")
            if axis == "length":
                model_y = self._display_y(result, 0.0)
                start_extension = dimension.start_extension or (dimension.start[0], model_y, dimension.start[2])
                end_extension = dimension.end_extension or (dimension.end[0], model_y, dimension.end[2])
                self._add_dimension_segment(start_extension, dimension.start,
                                            f"{dimension.layer_id}-start-extension-{dimension.index}")
                self._add_dimension_segment(end_extension, dimension.end,
                                            f"{dimension.layer_id}-end-extension-{dimension.index}")
            else:
                start_extension = dimension.start_extension or (0.0, dimension.start[1], dimension.start[2])
                end_extension = dimension.end_extension or (0.0, dimension.end[1], dimension.end[2])
                self._add_dimension_segment(start_extension, dimension.start,
                                            f"{dimension.layer_id}-start-extension-{dimension.index}")
                self._add_dimension_segment(end_extension, dimension.end,
                                            f"{dimension.layer_id}-end-extension-{dimension.index}")
            points.append(tuple((start + end) / 2 for start, end in zip(dimension.start, dimension.end)))
            labels.append(f"{format_mm(dimension.value)} mm")
        self._flush_annotation_batch(f"{axis}-dimension-lines")
        actor = self.add_point_labels(points, labels, name=f"{axis}-dimension-labels", show_points=False, font_size=12,
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
