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
};
type Project = { pallet: { length: Direction; width: Direction } };

declare global {
  interface Window {
    pywebview?: {
      api?: {
        status: () => Promise<ApplicationStatus>;
        default_project: () => Promise<object>;
        calculate: (project: object) => Promise<CalculationResponse>;
      };
    };
  }
}

export function App() {
  const [status, setStatus] = useState<ApplicationStatus | null>(null);
  const [calculation, setCalculation] = useState<CalculationResponse | null>(null);
  const [project, setProject] = useState<Project | null>(null);

  useEffect(() => {
    function connect() {
      const api = window.pywebview?.api;
      if (!api) return;
      api.status().then(setStatus).catch(() => setStatus(null));
      api.default_project().then((value) => setProject(value as Project));
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
