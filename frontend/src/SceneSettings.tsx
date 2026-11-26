import { useEffect, useRef, useState } from "react";
import { Settings } from "lucide-react";
import { Checkbox } from "./design/Checkbox";
import { Slider } from "./design/Slider";

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
        <Settings size={16} aria-hidden="true" />
      </button>
      <div id="scene-settings-panel" className={`manual-hud scene-settings-panel${open ? " is-open" : ""}`}
        aria-hidden={!open} inert={!open}>
        <strong>Настройки сцены</strong>
        {hasModel ? <>
          <label className="scene-settings-check">
            <Checkbox checked={modelVisible} onChange={(event) => setModelVisible(event.target.checked)} />
            <span>Показывать 3D-модель</span>
          </label>
          <label className="scene-settings-range">
            <span>Прозрачность</span>
            <Slider min={0} max={100} step={1} value={transparency} disabled={!modelVisible}
              onChange={(event) => setTransparency(Number(event.target.value))} />
            <output>{transparency}%</output>
          </label>
          <hr />
        </> : null}
        <label className="scene-settings-check">
          <Checkbox checked={dimensionsVisible} onChange={(event) => setDimensionsVisible(event.target.checked)} />
          <span>Показывать размеры</span>
        </label>
        <hr />
        <label className="scene-settings-check">
          <Checkbox checked={gridVisible} onChange={(event) => setGridVisible(event.target.checked)} />
          <span>Показывать сетку</span>
        </label>
      </div>
    </div>
  );
}
