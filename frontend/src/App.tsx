import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import type {
  CameraPreset,
  ViewportBeam,
  ViewportDimension,
  ViewportInsertionMarker,
  ViewportPoint,
} from "./PalletViewport";

const PalletViewport = lazy(() => import("./PalletViewport"));

type ApplicationStatus = {
  application: string;
  version: string;
  snapshotVersion: number;
};

type CalculationResponse = {
  ok: boolean;
  error?: string;
  snapshot?: {
    project: Project;
    pallet: {
      size: { length: number; width: number; height: number };
      beams: ViewportBeam[];
      dimensions: ViewportDimension[];
      insertionMarkers: ViewportInsertionMarker[];
    } | null;
  };
};

type Direction = {
  beam_height: number;
  beam_width: number;
  support_distances: number[];
  first_edge_to_support: number;
  last_support_to_edge: number;
  margin_start: number;
  margin_end: number;
  round_pallet_size: boolean;
  rounding_step: 5 | 50;
};
type Layer = { id: string; axis: "length" | "width"; direction: Direction };
type Project = {
  pallet: {
    length: Direction;
    width: Direction;
    layers: Layer[];
    upper_layer: "length" | "width";
    material_id: string;
  };
};
type Material = { id: string; name: string };
type BeamSection = { height: number; width: number };
type DimensionTarget = { layerId: string; beamIndex: number };
type InsertionSlot = {
  axis: "length" | "width";
  layerId: string;
  afterBeamIndex: number;
  maximumClearGap: number;
  suggestedClearGap: number;
};

declare global {
  interface Window {
    pywebview?: {
      api?: {
        status: () => Promise<ApplicationStatus>;
        default_project: () => Promise<object>;
        calculate: (project: object) => Promise<CalculationResponse>;
        materials: () => Promise<Material[]>;
        delete_beams: (
          project: object,
          selection: Record<string, number[]>,
        ) => Promise<CalculationResponse>;
        change_beam_sections: (
          project: object,
          selection: Record<string, number[]>,
          section: BeamSection,
        ) => Promise<CalculationResponse>;
        change_beam_distance: (
          project: object,
          target: DimensionTarget,
          faceDistance: number,
        ) => Promise<CalculationResponse>;
        insert_beam: (
          project: object,
          slot: InsertionSlot,
          clearGap: number,
        ) => Promise<CalculationResponse>;
        add_manual_beam: (
          project: object,
          supports: { layerId: string; layerIndex: number }[],
          options: object,
        ) => Promise<CalculationResponse>;
        save_project: (
          project: object,
        ) => Promise<{ ok: boolean; cancelled?: boolean; error?: string }>;
        open_project: () => Promise<{
          ok: boolean;
          cancelled?: boolean;
          error?: string;
          project?: Project;
        }>;
      };
    };
  }
}

export function App() {
  const [status, setStatus] = useState<ApplicationStatus | null>(null);
  const [calculation, setCalculation] = useState<CalculationResponse | null>(
    null,
  );
  const [calculationError, setCalculationError] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [distanceText, setDistanceText] = useState<
    Record<"length" | "width", string>
  >({ length: "", width: "" });
  const [camera, setCamera] = useState<CameraPreset>("isometric");
  const [selectedBeams, setSelectedBeams] = useState<ViewportBeam[]>([]);
  const [section, setSection] = useState<BeamSection>({
    height: 70,
    width: 50,
  });
  const [selectedDimension, setSelectedDimension] =
    useState<ViewportDimension | null>(null);
  const [distanceValue, setDistanceValue] = useState(0);
  const [dimensionEditing, setDimensionEditing] = useState(false);
  const [hoveredDimension, setHoveredDimension] = useState<string | null>(null);
  const [insertionMode, setInsertionMode] = useState(false);
  const [selectedSlot, setSelectedSlot] = useState<InsertionSlot | null>(null);
  const [insertionGap, setInsertionGap] = useState(0);
  const [manualSupports, setManualSupports] = useState<
    { beam: ViewportBeam; point: ViewportPoint }[]
  >([]);
  const [manualDistance, setManualDistance] = useState(0);
  const [manualReferenceMode, setManualReferenceMode] = useState<"base" | "face">("base");
  const [manualReference, setManualReference] = useState<ViewportBeam | null>(null);
  const [manualReferenceFace, setManualReferenceFace] = useState<"x_min" | "x_max" | "y_min" | "y_max">("x_min");

  function applyProject(nextProject: Project) {
    setProject(nextProject);
    setDistanceText({
      length: nextProject.pallet.length.support_distances.join(" "),
      width: nextProject.pallet.width.support_distances.join(" "),
    });
  }

  function applyCalculation(response: CalculationResponse) {
    // Invalid intermediate form values must not discard the last valid 3D
    // snapshot. Keeping it visible lets a user correct the input immediately.
    if (response.ok && response.snapshot) {
      setCalculation(response);
      setCalculationError(null);
    } else {
      setCalculationError(response.error ?? "Не удалось рассчитать поддон.");
    }
  }

  useEffect(() => {
    function connect() {
      const api = window.pywebview?.api;
      if (!api) return;
      api
        .status()
        .then(setStatus)
        .catch(() => setStatus(null));
      api.default_project().then((value) => {
        const project = value as Project;
        applyProject(project);
      });
      api.materials().then(setMaterials);
    }

    window.addEventListener("pywebviewready", connect, { once: true });
    connect();
    return () => window.removeEventListener("pywebviewready", connect);
  }, []);

  async function calculateProject() {
    const api = window.pywebview?.api;
    if (!api) return;
    if (project) applyCalculation(await api.calculate(project));
  }

  useEffect(() => {
    if (!status || !project) return;
    const timeout = window.setTimeout(() => {
      void calculateProject();
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [project, status]);

  async function saveProject() {
    if (!project) return;
    const response = await window.pywebview!.api!.save_project(project);
    if (!response.ok && !response.cancelled)
      setCalculationError(response.error ?? "Не удалось сохранить проект.");
  }
  async function openProject() {
    const response = await window.pywebview!.api!.open_project();
    if (response.project) {
      applyProject(response.project);
      setCalculationError(null);
    } else if (!response.cancelled) {
      setCalculationError(response.error ?? "Не удалось открыть проект.");
    }
  }

  function toggleBeam(beam: ViewportBeam, point?: ViewportPoint) {
    if (insertionMode) {
      if (manualReferenceMode === "face" && manualSupports.length === 2) {
        setManualReference(beam);
        return;
      }
      const support = {
        beam,
        point:
          point ??
          ([
            beam.center[0] / 1000,
            beam.center[2] / 1000,
            beam.center[1] / 1000,
          ] as ViewportPoint),
      };
      setManualSupports((current) =>
        current.length === 2 ? [support] : [...current, support],
      );
    }
    setSelectedBeams((selected) => {
      const alreadySelected = selected.some(
        (item) =>
          item.layerId === beam.layerId && item.layerIndex === beam.layerIndex,
      );
      return alreadySelected
        ? selected.filter(
            (item) =>
              item.layerId !== beam.layerId ||
              item.layerIndex !== beam.layerIndex,
          )
        : [...selected, beam];
    });
  }

  async function deleteSelectedBeams() {
    const api = window.pywebview?.api;
    if (!api || !project || selectedBeams.length === 0) return;
    const selection = selectedBeams.reduce<Record<string, number[]>>(
      (byLayer, beam) => {
        (byLayer[beam.layerId] ??= []).push(beam.layerIndex);
        return byLayer;
      },
      {},
    );
    const response = await api.delete_beams(project, selection);
    applyCalculation(response);
    if (response.ok && response.snapshot) {
      applyProject(response.snapshot.project);
      setSelectedBeams([]);
    }
  }

  async function changeSelectedBeamSections() {
    const api = window.pywebview?.api;
    if (!api || !project || selectedBeams.length === 0) return;
    const selection = selectedBeams.reduce<Record<string, number[]>>(
      (byLayer, beam) => {
        (byLayer[beam.layerId] ??= []).push(beam.layerIndex);
        return byLayer;
      },
      {},
    );
    const response = await api.change_beam_sections(
      project,
      selection,
      section,
    );
    applyCalculation(response);
    if (response.ok && response.snapshot) {
      applyProject(response.snapshot.project);
      setSelectedBeams([]);
    }
  }

  function selectDimension(dimension: ViewportDimension) {
    if (!dimension.editable) return;
    setSelectedDimension(dimension);
    setDistanceValue(dimension.editValue ?? dimension.value);
  }

  async function changeSelectedDistance() {
    const api = window.pywebview?.api;
    if (!api || !project || !selectedDimension) return;
    const response = await api.change_beam_distance(
      project,
      {
        layerId: selectedDimension.layerId,
        beamIndex: selectedDimension.index,
      },
      distanceValue,
    );
    applyCalculation(response);
    if (response.ok && response.snapshot) {
      applyProject(response.snapshot.project);
      setSelectedDimension(null);
    }
  }

  function stopDimensionEditing() {
    setDimensionEditing(false);
    setSelectedDimension(null);
    setHoveredDimension(null);
  }

  function stopInsertion() {
    setInsertionMode(false);
    setSelectedSlot(null);
    setManualSupports([]);
    setManualReference(null);
    setSelectedBeams([]);
  }

  async function insertSelectedBeam() {
    const api = window.pywebview?.api;
    if (!api || !project || !selectedSlot) return;
    const response = await api.insert_beam(project, selectedSlot, insertionGap);
    applyCalculation(response);
    if (response.ok && response.snapshot) {
      applyProject(response.snapshot.project);
      setSelectedSlot(null);
    }
  }

  function selectInsertion(marker: ViewportInsertionMarker) {
    setSelectedSlot(marker.slot);
    setInsertionGap(marker.slot.suggestedClearGap);
  }

  function selectManualSupport(beam: ViewportBeam, point: ViewportPoint) {
    setManualSupports((current) =>
      current.length === 2 ? [{ beam, point }] : [...current, { beam, point }],
    );
  }

  async function addManualBeam() {
    const api = window.pywebview?.api;
    if (!api || !project || manualSupports.length !== 2) return;
    const response = await api.add_manual_beam(
      project,
      manualSupports.map(({ beam }) => ({
        layerId: beam.layerId,
        layerIndex: beam.layerIndex,
      })),
      {
        distance: manualDistance,
        section,
        reference: manualReference ? { layerId: manualReference.layerId, layerIndex: manualReference.layerIndex } : undefined,
        referenceFace: manualReference ? manualReferenceFace : undefined,
      },
    );
    applyCalculation(response);
    if (response.ok && response.snapshot) {
      applyProject(response.snapshot.project);
      setManualSupports([]);
      setSelectedBeams([]);
    }
  }

  useEffect(() => {
    const cancelEditing = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        stopDimensionEditing();
        stopInsertion();
      }
    };
    window.addEventListener("keydown", cancelEditing);
    return () => window.removeEventListener("keydown", cancelEditing);
  }, []);

  function updateDirection(
    axis: "length" | "width",
    field: keyof Direction,
    value: string,
  ) {
    if (!project) return;
    if (field === "support_distances") {
      setDistanceText({ ...distanceText, [axis]: value });
      const distances = value.split(/\s+/).filter(Boolean).map(Number);
      if (distances.some(Number.isNaN)) return;
      updateDirectionValue(axis, field, distances);
      return;
    }
    updateDirectionValue(axis, field, Number(value));
  }

  function updateDirectionValue(
    axis: "length" | "width",
    field: keyof Direction,
    parsed: number | number[],
  ) {
    if (!project) return;
    const direction = { ...project.pallet[axis], [field]: parsed } as Direction;
    setProject({
      ...project,
      pallet: {
        ...project.pallet,
        [axis]: direction,
        layers: project.pallet.layers.map((layer) =>
          layer.axis === axis ? { ...layer, direction } : layer,
        ),
      },
    });
  }

  function setRounding(value: "none" | "5" | "50") {
    if (!project) return;
    const update = (direction: Direction): Direction => ({
      ...direction,
      round_pallet_size: value !== "none",
      rounding_step: value === "50" ? 50 : 5,
    });
    const length = update(project.pallet.length);
    const width = update(project.pallet.width);
    setProject({
      ...project,
      pallet: {
        ...project.pallet,
        length,
        width,
        layers: project.pallet.layers.map((layer) => ({
          ...layer,
          direction: update(layer.direction),
        })),
      },
    });
  }

  function updateLayerAxis(index: number, axis: "length" | "width") {
    if (!project) return;
    const layers = project.pallet.layers.map((layer, layerIndex) =>
      layerIndex === index
        ? { ...layer, axis, direction: project.pallet[axis] }
        : layer,
    );
    setProject({ ...project, pallet: { ...project.pallet, layers } });
  }

  function addLayer() {
    if (!project) return;
    const layerId = `layer-${project.pallet.layers.length}`;
    setProject({
      ...project,
      pallet: {
        ...project.pallet,
        layers: [
          ...project.pallet.layers,
          { id: layerId, axis: "length", direction: project.pallet.length },
        ],
      },
    });
  }

  function removeLayer(index: number) {
    if (!project || project.pallet.layers.length <= 2) return;
    setProject({
      ...project,
      pallet: {
        ...project.pallet,
        layers: project.pallet.layers.filter(
          (_, layerIndex) => layerIndex !== index,
        ),
      },
    });
  }

  const rounding = project?.pallet.length.round_pallet_size
    ? (String(project.pallet.length.rounding_step) as "5" | "50")
    : "none";
  const manualHud: ReactNode = insertionMode ? (
    <div className="manual-hud">
      <strong>{manualSupports.length === 0 ? "Click the first support beam." : manualSupports.length === 1 ? "Click a second parallel support beam." : "Configure the new beam."}</strong>
      {manualSupports.length === 2 ? <><label>Reference <select value={manualReferenceMode} onChange={(event) => { setManualReferenceMode(event.target.value as "base" | "face"); if (event.target.value === "base") setManualReference(null); }}><option value="base">Base point</option><option value="face">Selected beam face</option></select></label>{manualReferenceMode === "face" ? <span>{manualReference ? `Reference beam: ${manualReference.layerId} ${manualReference.layerIndex + 1}` : "Click a beam as reference."}</span> : null}<label>Distance<input type="number" value={manualDistance} onChange={(event) => setManualDistance(Number(event.target.value))} onKeyDown={(event) => { if (event.key === "Enter") void addManualBeam(); if (event.key === "Escape") stopInsertion(); }} /></label><button type="button" onClick={addManualBeam}>Add beam</button><button type="button" onClick={stopInsertion}>Cancel</button></> : null}
    </div>
  ) : null;

  return (
    <main className="migration-shell">
      <section>
        <p className="eyebrow">PalletLab</p>
        <h1>Web application host</h1>
        <p>
          This temporary shell verifies the React-to-Python bridge before the
          existing workflows move here.
        </p>
        <p className="status">
          {status
            ? `${status.application} ${status.version} · API ${status.snapshotVersion}`
            : "Connecting to Python…"}
        </p>
        <button type="button" onClick={calculateProject} disabled={!status}>
          Calculate project
        </button>
        <div className="file-actions">
          <button type="button" onClick={openProject} disabled={!status}>
            Open
          </button>
          <button type="button" onClick={saveProject} disabled={!project}>
            Save
          </button>
        </div>
        {project ? (
          <div className="directions">
            <fieldset className="rounding">
              <legend>Pallet rounding</legend>
              {(["none", "5", "50"] as const).map((value) => (
                <label key={value}>
                  <input
                    type="radio"
                    name="rounding"
                    value={value}
                    checked={rounding === value}
                    onChange={() => setRounding(value)}
                  />
                  {value === "none" ? "No rounding" : `Round ${value} mm`}
                </label>
              ))}
            </fieldset>
            <fieldset className="project-options">
              <legend>Project options</legend>
              <label>
                Upper layer
                <select
                  value={project.pallet.upper_layer}
                  onChange={(event) =>
                    setProject({
                      ...project,
                      pallet: {
                        ...project.pallet,
                        upper_layer: event.target.value as "length" | "width",
                      },
                    })
                  }
                >
                  <option value="length">Length</option>
                  <option value="width">Width</option>
                </select>
              </label>
              <label>
                Material
                <select
                  value={project.pallet.material_id}
                  onChange={(event) =>
                    setProject({
                      ...project,
                      pallet: {
                        ...project.pallet,
                        material_id: event.target.value,
                      },
                    })
                  }
                >
                  {materials.map((material) => (
                    <option key={material.id} value={material.id}>
                      {material.name}
                    </option>
                  ))}
                </select>
              </label>
            </fieldset>
            <fieldset className="layers">
              <legend>Layers</legend>
              {project.pallet.layers.map((layer, index) => (
                <div className="layer-row" key={layer.id}>
                  <span>
                    {index + 1}. {layer.id}
                  </span>
                  <select
                    value={layer.axis}
                    onChange={(event) =>
                      updateLayerAxis(
                        index,
                        event.target.value as "length" | "width",
                      )
                    }
                  >
                    <option value="length">Length</option>
                    <option value="width">Width</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => removeLayer(index)}
                    disabled={project.pallet.layers.length <= 2}
                  >
                    Remove
                  </button>
                </div>
              ))}
              <button type="button" onClick={addLayer}>
                Add layer
              </button>
            </fieldset>
            {(["length", "width"] as const).map((axis) => (
              <fieldset key={axis}>
                <legend>
                  {axis === "length" ? "Length direction" : "Width direction"}
                </legend>
                {(
                  [
                    "beam_height",
                    "beam_width",
                    "support_distances",
                    "first_edge_to_support",
                    "last_support_to_edge",
                    "margin_start",
                    "margin_end",
                  ] as const
                ).map((field) => (
                  <label key={field}>
                    {field.replaceAll("_", " ")}
                    <input
                      value={
                        field === "support_distances"
                          ? distanceText[axis]
                          : project.pallet[axis][field]
                      }
                      onChange={(event) =>
                        updateDirection(axis, field, event.target.value)
                      }
                    />
                  </label>
                ))}
              </fieldset>
            ))}
          </div>
        ) : null}
        {calculation?.ok && calculation.snapshot?.pallet ? (
          <>
            <p className="result">
              {calculation.snapshot.pallet.size.length} ×{" "}
              {calculation.snapshot.pallet.size.width} ×{" "}
              {calculation.snapshot.pallet.size.height} mm ·{" "}
              {calculation.snapshot.pallet.beams.length} beams
            </p>
            <p className="selection-status">
              {selectedBeams.length
                ? `Selected beams: ${selectedBeams.length}`
                : "Select beams in the 3D view"}
            </p>
            <div className="camera-actions">
              {(["isometric", "top", "front", "side"] as CameraPreset[]).map(
                (preset) => (
                  <button
                    type="button"
                    key={preset}
                    onClick={() => setCamera(preset)}
                  >
                    {preset}
                  </button>
                ),
              )}
              <label>
                Section height
                <input
                  type="number"
                  min="1"
                  value={section.height}
                  onChange={(event) =>
                    setSection({
                      ...section,
                      height: Number(event.target.value),
                    })
                  }
                />
              </label>
              <label>
                Section width
                <input
                  type="number"
                  min="1"
                  value={section.width}
                  onChange={(event) =>
                    setSection({
                      ...section,
                      width: Number(event.target.value),
                    })
                  }
                />
              </label>
              <button
                type="button"
                onClick={changeSelectedBeamSections}
                disabled={selectedBeams.length === 0}
              >
                Change section
              </button>
              <button
                type="button"
                onClick={deleteSelectedBeams}
                disabled={selectedBeams.length === 0}
              >
                Delete selected ({selectedBeams.length})
              </button>
              <button
                type="button"
                className={dimensionEditing ? "active-tool" : ""}
                onClick={() =>
                  dimensionEditing
                    ? stopDimensionEditing()
                    : setDimensionEditing(true)
                }
              >
                {dimensionEditing ? "Finish dimension edit" : "Edit dimensions"}
              </button>
              <button
                type="button"
                className={insertionMode ? "active-tool" : ""}
                onClick={() =>
                  insertionMode ? stopInsertion() : setInsertionMode(true)
                }
              >
                {insertionMode ? "Finish insertion" : "Add beam"}
              </button>
            </div>
            {dimensionEditing && selectedDimension ? (
              <div className="distance-editor">
                <span>
                  Selected dimension: {selectedDimension.value.toFixed(0)} mm
                </span>
                <label>
                  New face distance
                  <input
                    type="number"
                    value={distanceValue}
                    onChange={(event) =>
                      setDistanceValue(Number(event.target.value))
                    }
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void changeSelectedDistance();
                      if (event.key === "Escape") stopDimensionEditing();
                    }}
                  />
                </label>
                <button type="button" onClick={changeSelectedDistance}>
                  Apply distance
                </button>
                <button type="button" onClick={stopDimensionEditing}>
                  Cancel
                </button>
              </div>
            ) : dimensionEditing ? (
              <p className="dimension-hint">
                Hover a dimension line, then click it to edit. Esc closes this
                mode.
              </p>
            ) : null}
            {insertionMode ? (
              <p className="dimension-hint">
                {manualSupports.length === 0
                  ? "Click the first support beam at the desired insertion point."
                  : manualSupports.length === 1
                    ? "Click a second parallel support beam."
                    : "Set the position below, then confirm with Enter or Add beam."}
              </p>
            ) : null}
            <Suspense fallback={<p>Loading 3D view…</p>}>
              <PalletViewport
                beams={calculation.snapshot.pallet.beams}
                dimensions={calculation.snapshot.pallet.dimensions}
                preset={camera}
                selectedBeams={selectedBeams.map(
                  (beam) => `${beam.layerId}:${beam.layerIndex}`,
                )}
                dimensionEditing={dimensionEditing}
                hoveredDimension={hoveredDimension}
                onToggleBeam={toggleBeam}
                onSelectDimension={selectDimension}
                onHoverDimension={(dimension) =>
                  setHoveredDimension(
                    dimension
                      ? `${dimension.layerId}:${dimension.index}`
                      : null,
                  )
                }
                insertionMarkers={calculation.snapshot.pallet.insertionMarkers}
                insertionMode={insertionMode}
                selectedSlot={selectedSlot}
                onSelectInsertion={selectInsertion}
                manualMode={insertionMode}
                manualSupports={manualSupports}
                onSelectManualSupport={selectManualSupport}
                manualHud={manualHud}
              />
            </Suspense>
          </>
        ) : null}
        {false && insertionMode && manualSupports.length === 2 ? (
          <div className="distance-editor">
            <span>
              Two supports selected. Set the offset from the base point.
            </span>
            <fieldset>
              <legend>Reference</legend>
              <label><input type="radio" checked={manualReferenceMode === "base"} onChange={() => { setManualReferenceMode("base"); setManualReference(null); }} />Base point</label>
              <label><input type="radio" checked={manualReferenceMode === "face"} onChange={() => setManualReferenceMode("face")} />Selected beam face</label>
            </fieldset>
            {manualReferenceMode === "face" ? <><p>{manualReference ? `Reference: ${manualReference?.layerId} · beam ${(manualReference?.layerIndex ?? 0) + 1}` : "Click a beam to choose the reference."}</p><label>Face<select value={manualReferenceFace} onChange={(event) => setManualReferenceFace(event.target.value as "x_min" | "x_max" | "y_min" | "y_max")}><option value="x_min">X minimum</option><option value="x_max">X maximum</option><option value="y_min">Y minimum</option><option value="y_max">Y maximum</option></select></label></> : null}
            <label>
              Distance
              <input
                type="number"
                value={manualDistance}
                onChange={(event) =>
                  setManualDistance(Number(event.target.value))
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter") void addManualBeam();
                  if (event.key === "Escape") stopInsertion();
                }}
              />
            </label>
            <button type="button" onClick={addManualBeam}>
              Add beam
            </button>
            <button type="button" onClick={stopInsertion}>
              Cancel
            </button>
          </div>
        ) : insertionMode ? (
          <p className="dimension-hint">
            Click two parallel support beams. The first click marks the
            insertion layer; Esc cancels.
          </p>
        ) : null}
        {calculationError ? <p className="error">{calculationError}</p> : null}
      </section>
    </main>
  );
}
