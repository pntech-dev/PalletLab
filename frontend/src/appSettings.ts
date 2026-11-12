import type { Project } from "./App";
import type { CameraPreset } from "./PalletViewport";

export type AppSettings = {
  rounding: "50" | "5" | "none";
  autosaveEnabled: boolean;
  autosaveMinutes: number;
  showDimensions: boolean;
  showGrid: boolean;
  camera: CameraPreset;
  checkUpdates: boolean;
};

export const DEFAULT_SETTINGS: AppSettings = {
  rounding: "50", autosaveEnabled: true, autosaveMinutes: 1,
  showDimensions: true, showGrid: true, camera: "isometric", checkUpdates: true,
};

export function projectWithDefaults(project: Project, settings: AppSettings): Project {
  const direction = <T extends { round_pallet_size: boolean; rounding_step: 5 | 50 }>(value: T): T => ({
    ...value, round_pallet_size: settings.rounding !== "none", rounding_step: settings.rounding === "50" ? 50 : 5,
  });
  return {
    ...project,
    pallet: { ...project.pallet, rounding_step: settings.rounding === "none" ? 0 : settings.rounding === "50" ? 50 : 5, length: direction(project.pallet.length), width: direction(project.pallet.width),
      layers: project.pallet.layers.map((layer) => ({ ...layer, direction: direction(layer.direction) })) },
    view: { ...project.view, camera: settings.camera, show_length_dimensions: settings.showDimensions,
      show_width_dimensions: settings.showDimensions, show_grid: settings.showGrid },
  };
}
export function projectWithChangedDefaults(project: Project, previous: AppSettings, next: AppSettings): Project {
  const defaults = projectWithDefaults(project, next);
  return {
    ...project,
    pallet: previous.rounding === next.rounding ? project.pallet : defaults.pallet,
    view: {
      ...project.view,
      ...(previous.camera === next.camera ? {} : { camera: defaults.view.camera }),
      ...(previous.showDimensions === next.showDimensions ? {} : {
        show_length_dimensions: defaults.view.show_length_dimensions,
        show_width_dimensions: defaults.view.show_width_dimensions,
      }),
      ...(previous.showGrid === next.showGrid ? {} : { show_grid: defaults.view.show_grid }),
    },
  };
}

export function applyDefaultsIfUnmodified(project: Project, baseline: string | null, previous: AppSettings, next: AppSettings): Project | null {
  if (baseline === null || JSON.stringify(project) !== baseline) return null;
  return projectWithChangedDefaults(project, previous, next);
}
