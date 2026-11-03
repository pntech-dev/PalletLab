import { useEffect, useState } from "react";

type ApplicationStatus = {
  application: string;
  version: string;
  snapshotVersion: number;
};

declare global {
  interface Window {
    pywebview?: { api?: { status: () => Promise<ApplicationStatus> } };
  }
}

export function App() {
  const [status, setStatus] = useState<ApplicationStatus | null>(null);

  useEffect(() => {
    window.pywebview?.api?.status().then(setStatus).catch(() => setStatus(null));
  }, []);

  return (
    <main className="migration-shell">
      <section>
        <p className="eyebrow">PalletLab</p>
        <h1>Web application host</h1>
        <p>This temporary shell verifies the React-to-Python bridge before the existing workflows move here.</p>
        <p className="status">
          {status ? `${status.application} ${status.version} · API ${status.snapshotVersion}` : "Connecting to Python…"}
        </p>
      </section>
    </main>
  );
}
