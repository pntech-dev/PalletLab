import { useEffect, useState } from "react";

type ApplicationStatus = {
  application: string;
  version: string;
  snapshotVersion: number;
};

type CalculationResponse = {
  ok: boolean;
  error?: string;
  snapshot?: {
    pallet: { size: { length: number; width: number; height: number }; beams: unknown[] } | null;
  };
};

type Direction = {
  beam_height: number; beam_width: number; support_distances: number[];
  first_edge_to_support: number; last_support_to_edge: number; margin_start: number; margin_end: number;
  round_pallet_size: boolean; rounding_step: 5 | 50;
};
type Project = { pallet: { length: Direction; width: Direction; upper_layer: "length" | "width"; material_id: string } };
type Material = { id: string; name: string };

declare global {
  interface Window {
    pywebview?: {
      api?: {
        status: () => Promise<ApplicationStatus>;
        default_project: () => Promise<object>;
        calculate: (project: object) => Promise<CalculationResponse>;
        materials: () => Promise<Material[]>;
      };
    };
  }
}

export function App() {
  const [status, setStatus] = useState<ApplicationStatus | null>(null);
  const [calculation, setCalculation] = useState<CalculationResponse | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);

  useEffect(() => {
    function connect() {
      const api = window.pywebview?.api;
      if (!api) return;
      api.status().then(setStatus).catch(() => setStatus(null));
      api.default_project().then((value) => setProject(value as Project));
      api.materials().then(setMaterials);
    }

    window.addEventListener("pywebviewready", connect, { once: true });
    connect();
    return () => window.removeEventListener("pywebviewready", connect);
  }, []);

  async function calculateDefaultProject() {
    const api = window.pywebview?.api;
    if (!api) return;
    if (project) setCalculation(await api.calculate(project));
  }

  function updateDirection(axis: "length" | "width", field: keyof Direction, value: string) {
    if (!project) return;
    const parsed = field === "support_distances"
      ? value.split(/\s+/).filter(Boolean).map(Number)
      : Number(value);
    setProject({ ...project, pallet: { ...project.pallet, [axis]: { ...project.pallet[axis], [field]: parsed } } });
  }

  function setRounding(value: "none" | "5" | "50") {
    if (!project) return;
    const update = (direction: Direction): Direction => ({
      ...direction,
      round_pallet_size: value !== "none",
      rounding_step: value === "50" ? 50 : 5,
    });
    setProject({ ...project, pallet: { ...project.pallet, length: update(project.pallet.length), width: update(project.pallet.width) } });
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
        <button type="button" onClick={calculateDefaultProject} disabled={!status}>
          Calculate project
        </button>
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
          {(["length", "width"] as const).map((axis) => <fieldset key={axis}>
            <legend>{axis === "length" ? "Length direction" : "Width direction"}</legend>
            {(["beam_height", "beam_width", "support_distances", "first_edge_to_support", "last_support_to_edge", "margin_start", "margin_end"] as const).map((field) => <label key={field}>
              {field.replaceAll("_", " ")}
              <input value={Array.isArray(project.pallet[axis][field]) ? project.pallet[axis][field].join(" ") : project.pallet[axis][field]}
                onChange={(event) => updateDirection(axis, field, event.target.value)} />
            </label>)}
          </fieldset>)}
        </div> : null}
        {calculation?.ok && calculation.snapshot?.pallet ? (
          <p className="result">
            {calculation.snapshot.pallet.size.length} × {calculation.snapshot.pallet.size.width} × {calculation.snapshot.pallet.size.height} mm
            · {calculation.snapshot.pallet.beams.length} beams
          </p>
        ) : null}
        {calculation && !calculation.ok ? <p className="error">{calculation.error}</p> : null}
      </section>
    </main>
  );
}
