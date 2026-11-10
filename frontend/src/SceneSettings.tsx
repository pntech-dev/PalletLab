import { useEffect, useRef, useState } from "react";

type SceneSettingsProps = {
  hasModel: boolean;
  modelVisible: boolean;
  setModelVisible: (value: boolean) => void;
  transparency: number;
  setTransparency: (value: number) => void;
  dimensionsVisible: boolean;
  setDimensionsVisible: (value: boolean) => void;
  gridVisible: boolean;
  setGridVisible: (value: boolean) => void;
};

export default function SceneSettings({
  hasModel, modelVisible, setModelVisible, transparency, setTransparency,
  dimensionsVisible, setDimensionsVisible, gridVisible, setGridVisible,
}: SceneSettingsProps) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !container.current?.contains(event.target)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="scene-settings-anchor" ref={container}
      onPointerDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
      <button type="button" className="scene-settings-toggle" aria-label="Настройки сцены"
        aria-expanded={open} aria-controls="scene-settings-panel" onClick={() => setOpen((value) => !value)}>
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path strokeLinecap="round" d="M4 7h10m4 0h2M4 17h2m4 0h10" />
          <circle cx="16" cy="7" r="2" /><circle cx="8" cy="17" r="2" />
        </svg>
      </button>
      <div id="scene-settings-panel" className={`manual-hud scene-settings-panel${open ? " is-open" : ""}`}
        aria-hidden={!open} inert={!open}>
        <strong>Настройки сцены</strong>
        {hasModel ? <>
          <label className="scene-settings-check">
            <input type="checkbox" checked={modelVisible} onChange={(event) => setModelVisible(event.target.checked)} />
            <span>Показывать 3D-модель</span>
          </label>
          <label className="scene-settings-range">
            <span>Прозрачность <output>{transparency}%</output></span>
            <input type="range" min="0" max="100" step="1" value={transparency} disabled={!modelVisible}
              onChange={(event) => setTransparency(Number(event.target.value))} />
          </label>
          <hr />
        </> : null}
        <label className="scene-settings-check">
          <input type="checkbox" checked={dimensionsVisible} onChange={(event) => setDimensionsVisible(event.target.checked)} />
          <span>Показывать размеры</span>
        </label>
        <hr />
        <label className="scene-settings-check">
          <input type="checkbox" checked={gridVisible} onChange={(event) => setGridVisible(event.target.checked)} />
          <span>Показывать сетку</span>
        </label>
      </div>
    </div>
  );
}
