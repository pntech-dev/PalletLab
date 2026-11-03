import { lazy, Suspense, useEffect, useState } from "react";
import type { CameraPreset, ViewportBeam, ViewportDimension } from "./PalletViewport";

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
    pallet: { size: { length: number; width: number; height: number }; beams: ViewportBeam[]; dimensions: ViewportDimension[] } | null;
  };
};

type Direction = {
  beam_height: number; beam_width: number; support_distances: number[];
  first_edge_to_support: number; last_support_to_edge: number; margin_start: number; margin_end: number;
  round_pallet_size: boolean; rounding_step: 5 | 50;
};
type Layer = { id: string; axis: "length" | "width"; direction: Direction };
type Project = { pallet: { length: Direction; width: Direction; layers: Layer[]; upper_layer: "length" | "width"; material_id: string } };
type Material = { id: string; name: string };

declare global {
  interface Window {
    pywebview?: {
      api?: {
        status: () => Promise<ApplicationStatus>;
        default_project: () => Promise<object>;
        calculate: (project: object) => Promise<CalculationResponse>;
        materials: () => Promise<Material[]>;
        delete_beams: (project: object, selection: Record<string, number[]>) => Promise<CalculationResponse>;
        save_project: (project: object) => Promise<{ ok: boolean; cancelled?: boolean; error?: string }>;
        open_project: () => Promise<{ ok: boolean; cancelled?: boolean; error?: string; project?: Project }>;
      };
    };
  }
}

export function App() {
  const [status, setStatus] = useState<ApplicationStatus | null>(null);
  const [calculation, setCalculation] = useState<CalculationResponse | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [distanceText, setDistanceText] = useState<Record<"length" | "width", string>>({ length: "", width: "" });
  const [camera, setCamera] = useState<CameraPreset>("isometric");
  const [selectedBeams, setSelectedBeams] = useState<ViewportBeam[]>([]);

  useEffect(() => {
    function connect() {
      const api = window.pywebview?.api;
      if (!api) return;
      api.status().then(setStatus).catch(() => setStatus(null));
      api.default_project().then((value) => {
        const project = value as Project;
        setProject(project);
        setDistanceText({ length: project.pallet.length.support_distances.join(" "), width: project.pallet.width.support_distances.join(" ") });
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
    if (project) setCalculation(await api.calculate(project));
  }

  useEffect(() => {
    if (!status || !project) return;
    const timeout = window.setTimeout(() => { void calculateProject(); }, 300);
    return () => window.clearTimeout(timeout);
  }, [project, status]);

  async function saveProject() { if (project) setCalculation(await window.pywebview!.api!.save_project(project) as CalculationResponse); }
  async function openProject() {
    const response = await window.pywebview!.api!.open_project();
    if (response.project) setProject(response.project);
  }

  function toggleBeam(beam: ViewportBeam) {
    setSelectedBeams((selected) => {
      const alreadySelected = selected.some((item) => item.layerId === beam.layerId && item.layerIndex === beam.layerIndex);
      return alreadySelected
        ? selected.filter((item) => item.layerId !== beam.layerId || item.layerIndex !== beam.layerIndex)
        : [...selected, beam];
    });
  }

  async function deleteSelectedBeams() {
    const api = window.pywebview?.api;
    if (!api || !project || selectedBeams.length === 0) return;
    const selection = selectedBeams.reduce<Record<string, number[]>>((byLayer, beam) => {
      (byLayer[beam.layerId] ??= []).push(beam.layerIndex);
      return byLayer;
    }, {});
    const response = await api.delete_beams(project, selection);
    setCalculation(response);
    if (response.ok && response.snapshot) {
      setProject(response.snapshot.project);
      setSelectedBeams([]);
    }
  }

  function updateDirection(axis: "length" | "width", field: keyof Direction, value: string) {
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

  function updateDirectionValue(axis: "length" | "width", field: keyof Direction, parsed: number | number[]) {
    if (!project) return;
    const direction = { ...project.pallet[axis], [field]: parsed } as Direction;
    setProject({ ...project, pallet: {
      ...project.pallet,
      [axis]: direction,
      layers: project.pallet.layers.map((layer) => layer.axis === axis ? { ...layer, direction } : layer),
    } });
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
    setProject({ ...project, pallet: {
      ...project.pallet, length, width,
      layers: project.pallet.layers.map((layer) => ({ ...layer, direction: update(layer.direction) })),
    } });
  }

  function updateLayerAxis(index: number, axis: "length" | "width") {
    if (!project) return;
    const layers = project.pallet.layers.map((layer, layerIndex) => layerIndex === index
      ? { ...layer, axis, direction: project.pallet[axis] }
      : layer);
    setProject({ ...project, pallet: { ...project.pallet, layers } });
  }

  function addLayer() {
    if (!project) return;
    const layerId = `layer-${project.pallet.layers.length}`;
    setProject({ ...project, pallet: { ...project.pallet, layers: [...project.pallet.layers, { id: layerId, axis: "length", direction: project.pallet.length }] } });
  }

  function removeLayer(index: number) {
    if (!project || project.pallet.layers.length <= 2) return;
    setProject({ ...project, pallet: { ...project.pallet, layers: project.pallet.layers.filter((_, layerIndex) => layerIndex !== index) } });
  }

  const rounding = project?.pallet.length.round_pallet_size
    ? String(project.pallet.length.rounding_step) as "5" | "50"
    : "none";

  return (
    <main className="migration-shell">
      <section>
        <p className="eyebrow">PalletLab</p>
        <h1>Web application host</h1>
        <p>This temporary shell verifies the React-to-Python bridge before the existing workflows move here.</p>
        <p className="status">
          {status ? `${status.application} ${status.version} · API ${status.snapshotVersion}` : "Connecting to Python…"}
        </p>
        <button type="button" onClick={calculateProject} disabled={!status}>
          Calculate project
        </button>
        <div className="file-actions"><button type="button" onClick={openProject} disabled={!status}>Open</button><button type="button" onClick={saveProject} disabled={!project}>Save</button></div>
        {project ? <div className="directions">
          <fieldset className="rounding">
            <legend>Pallet rounding</legend>
            {(["none", "5", "50"] as const).map((value) => <label key={value}>
              <input type="radio" name="rounding" value={value}
                checked={rounding === value}
                onChange={() => setRounding(value)} />
              {value === "none" ? "No rounding" : `Round ${value} mm`}
            </label>)}
          </fieldset>
          <fieldset className="project-options">
            <legend>Project options</legend>
            <label>Upper layer
              <select value={project.pallet.upper_layer} onChange={(event) => setProject({ ...project, pallet: { ...project.pallet, upper_layer: event.target.value as "length" | "width" } })}>
                <option value="length">Length</option><option value="width">Width</option>
              </select>
            </label>
            <label>Material
              <select value={project.pallet.material_id} onChange={(event) => setProject({ ...project, pallet: { ...project.pallet, material_id: event.target.value } })}>
                {materials.map((material) => <option key={material.id} value={material.id}>{material.name}</option>)}
              </select>
            </label>
          </fieldset>
          <fieldset className="layers">
            <legend>Layers</legend>
            {project.pallet.layers.map((layer, index) => <div className="layer-row" key={layer.id}>
              <span>{index + 1}. {layer.id}</span>
              <select value={layer.axis} onChange={(event) => updateLayerAxis(index, event.target.value as "length" | "width")}>
                <option value="length">Length</option><option value="width">Width</option>
              </select>
              <button type="button" onClick={() => removeLayer(index)} disabled={project.pallet.layers.length <= 2}>Remove</button>
            </div>)}
            <button type="button" onClick={addLayer}>Add layer</button>
          </fieldset>
          {(["length", "width"] as const).map((axis) => <fieldset key={axis}>
            <legend>{axis === "length" ? "Length direction" : "Width direction"}</legend>
            {(["beam_height", "beam_width", "support_distances", "first_edge_to_support", "last_support_to_edge", "margin_start", "margin_end"] as const).map((field) => <label key={field}>
              {field.replaceAll("_", " ")}
              <input value={field === "support_distances" ? distanceText[axis] : project.pallet[axis][field]}
                onChange={(event) => updateDirection(axis, field, event.target.value)} />
            </label>)}
          </fieldset>)}
        </div> : null}
        {calculation?.ok && calculation.snapshot?.pallet ? (
          <><p className="result">
            {calculation.snapshot.pallet.size.length} × {calculation.snapshot.pallet.size.width} × {calculation.snapshot.pallet.size.height} mm
            · {calculation.snapshot.pallet.beams.length} beams
          </p><p className="selection-status">{selectedBeams.length ? `Selected beams: ${selectedBeams.length}` : "Select beams in the 3D view"}</p><div className="camera-actions">{(["isometric", "top", "front", "side"] as CameraPreset[]).map((preset) => <button type="button" key={preset} onClick={() => setCamera(preset)}>{preset}</button>)}<button type="button" onClick={deleteSelectedBeams} disabled={selectedBeams.length === 0}>Delete selected ({selectedBeams.length})</button></div><Suspense fallback={<p>Loading 3D view…</p>}><PalletViewport beams={calculation.snapshot.pallet.beams} dimensions={calculation.snapshot.pallet.dimensions} preset={camera} selectedBeams={selectedBeams.map((beam) => `${beam.layerId}:${beam.layerIndex}`)} onToggleBeam={toggleBeam} /></Suspense></>
        ) : null}
        {calculation && !calculation.ok ? <p className="error">{calculation.error}</p> : null}
      </section>
    </main>
  );
}
