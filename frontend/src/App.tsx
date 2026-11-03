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

  useEffect(() => {
    window.pywebview?.api?.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  async function calculateDefaultProject() {
    const api = window.pywebview?.api;
    if (!api) return;
    const project = await api.default_project();
    setCalculation(await api.calculate(project));
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
          Calculate current default project
        </button>
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
