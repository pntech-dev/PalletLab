import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type {
  CameraPreset,
  ViewportBeam,
  ViewportDimension,
  ViewportFaceNormal,
  ViewportInsertionMarker,
  ViewportPoint,
  StepModelSnapshot,
} from "./PalletViewport";
import type { StepModelPayload } from "./stepModelGeometry";
import { changePalletMargin, marginLinks, MARGIN_PAIRS, palletMargins, toggleMarginLink, type MarginIndex } from "./palletMargins";

const startupStartedAt = performance.now();

function reportStartupStage(stage: string) {
  const elapsed = Math.round(performance.now() - startupStartedAt);
  performance.mark(`palletlab-startup:${stage}`);
  console.info(`[PalletLab] Запуск: ${stage} (+${elapsed} мс)`);
}

// Fetch and evaluate the 3D renderer while the desktop bridge prepares the
// first project. Previously this request did not start until after calculation.
const palletViewportModule = import("./PalletViewport").then((module) => {
  reportStartupStage("модуль 3D-вида готов");
  return module;
});
const PalletViewport = lazy(() => palletViewportModule);

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

export type Direction = {
  beam_height: number;
  beam_width: number;
  support_distances: number[];
  first_edge_to_support: number;
  last_support_to_edge: number;
  margin_start: number;
  margin_end: number;
  support_positions?: number[] | null;
  round_pallet_size: boolean;
  rounding_step: 5 | 50;
};
type Layer = { id: string; axis: "length" | "width"; direction: Direction };

function rawPalletSize(direction: Direction): number {
  return direction.margin_start
    + direction.first_edge_to_support
    + direction.support_distances.reduce((total, distance) => total + distance, 0)
    + direction.last_support_to_edge
    + direction.margin_end;
}

function palletDetails(beams: ViewportBeam[]) {
  const groups = new Map<string, { height: number; width: number; length: number; count: number }>();
  for (const beam of beams) {
    const length = beam.orientation === "length" ? beam.size[0] : beam.size[1];
    const width = beam.orientation === "length" ? beam.size[1] : beam.size[0];
    const height = beam.size[2];
    const key = JSON.stringify([height, width, length]);
    const group = groups.get(key);
    if (group) group.count += 1;
    else groups.set(key, { height, width, length, count: 1 });
  }
  return [...groups.values()];
}

const formatMillimetres = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value);

const DIRECTION_FIELDS = [
  "beam_height",
  "beam_width",
  "support_distances",
  "first_edge_to_support",
  "last_support_to_edge",
  "margin_start",
  "margin_end",
] as const;
type DirectionField = (typeof DIRECTION_FIELDS)[number];
const DIRECTION_FIELD_LABELS: Record<DirectionField, string> = {
  beam_height: "Высота бруса, мм",
  beam_width: "Ширина бруса, мм",
  support_distances: "Расстояния между опорами, мм",
  first_edge_to_support: "До первой опоры, мм",
  last_support_to_edge: "После последней опоры, мм",
  margin_start: "Отступ с начала, мм",
  margin_end: "Отступ с конца, мм",
};
export type Project = {
  pallet: {
    length: Direction;
    width: Direction;
    layers: Layer[];
    upper_layer: "length" | "width";
    material_id: string;
    pallet_margins?: [number, number] | [number, number, number, number];
    pallet_margin_links?: [boolean, boolean];
    manual_beams?: { start_point?: number[] | null; [key: string]: unknown }[];
  };
  view: {
    camera: CameraPreset;
    show_length_dimensions: boolean;
    show_width_dimensions: boolean;
    hidden_layer_ids: string[];
  };
};
type Material = { id: string; name: string };
type BeamSection = { height: number; width: number };
const SECTION_PRESETS = [
  { id: "70x50", label: "70 × 50 мм", height: 70, width: 50 },
  { id: "25x100", label: "25 × 100 мм", height: 25, width: 100 },
  { id: "100x100", label: "100 × 100 мм", height: 100, width: 100 },
  { id: "100x200", label: "100 × 200 мм", height: 100, width: 200 },
  { id: "custom", label: "Свой размер" },
] as const;
type SectionPresetId = (typeof SECTION_PRESETS)[number]["id"];

function sectionPresetFor(direction: Direction): SectionPresetId {
  return SECTION_PRESETS.find(
    (preset) => "height" in preset
      && preset.height === direction.beam_height
      && preset.width === direction.beam_width,
  )?.id ?? "custom";
}

type DimensionTarget = { layerId: string; beamIndex: number };
type InsertionSlot = {
  axis: "length" | "width";
  layerId: string;
  afterBeamIndex: number;
  maximumClearGap: number;
  suggestedClearGap: number;
};
type StepImportOperation = {
  ok: boolean;
  cancelled?: boolean;
  operationId?: string;
  state?: "running" | "cancelling" | "completed" | "cancelled" | "failed";
  progress?: number;
  label?: string;
  error?: string;
};
type StepModelResponse = { ok: boolean; error?: string; assetUrl?: string };
type StepPalletResponse = CalculationResponse & {
  modelTransform?: number[];
  supportCount?: number;
  referenceFace?: number;
};
type CommandResponse = { ok: boolean; cancelled?: boolean; error?: string; output?: string };
type UpdateStatus = {
  state: "idle" | "unavailable" | "checking" | "current" | "check_failed" | "available" | "downloading" | "ready" | "installing" | "failed";
  version?: string;
  received?: number;
  total?: number;
  error?: string;
};
type SolidWorksTemplateResponse = CommandResponse & { path?: string };
type SolidWorksMaterialsResponse = CommandResponse & { materialLibrary?: string; materials?: string[] };
type SolidWorksOptions = {
  partTemplate: string;
  assemblyTemplate: string;
  materialLibrary: string;
  materialName: string;
};
type SolidWorksSettingsResponse = CommandResponse & { options?: SolidWorksOptions | null };
type DrawingCad = "solidworks" | "kompas";
type DrawingScope = "assembly" | "parts_and_assembly";
type DrawingTemplatesResponse = CommandResponse & { templates?: Partial<Record<DrawingCad, string>> };
type ExportResult = {
  target: "КОМПАС-3D" | "SolidWorks" | "Чертежи SolidWorks" | "Чертежи КОМПАС-3D";
  ok: boolean;
  message: string;
};

const AUTOSAVE_KEY = "palletlab.web.autosave.v1";
const SOLIDWORKS_OPTIONS_KEY = "palletlab.web.solidworks-options.v1";
const HISTORY_LIMIT = 50;

function copyProject(project: Project): Project {
  return JSON.parse(JSON.stringify(project)) as Project;
}

function projectsMatch(first: Project, second: Project): boolean {
  return JSON.stringify(first) === JSON.stringify(second);
}

function recoveredProject(): Project | null {
  try {
    const raw = window.localStorage.getItem(AUTOSAVE_KEY);
    return raw ? (JSON.parse(raw) as Project) : null;
  } catch {
    return null;
  }
}

function discardRecoveredProject() {
  try {
    window.localStorage.removeItem(AUTOSAVE_KEY);
  } catch {
    // Recovery is optional when an embedded browser disables local storage.
  }
}

function storedSolidWorksOptions(): SolidWorksOptions | null {
  try {
    const raw = window.localStorage.getItem(SOLIDWORKS_OPTIONS_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<SolidWorksOptions>;
    return typeof value.partTemplate === "string"
      && typeof value.assemblyTemplate === "string"
      && typeof value.materialLibrary === "string"
      && typeof value.materialName === "string"
      ? value as SolidWorksOptions
      : null;
  } catch {
    return null;
  }
}

declare global {
  interface Window {
    pywebview?: {
      api?: {
        status: () => Promise<ApplicationStatus>;
        default_project: () => Promise<object>;
        calculate: (project: object) => Promise<CalculationResponse>;
        materials: () => Promise<Material[]>;
        check_update: () => Promise<UpdateStatus>;
        update_status: () => Promise<UpdateStatus>;
        download_update: () => Promise<UpdateStatus>;
        install_update: () => Promise<UpdateStatus>;
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
          saveAs: boolean,
        ) => Promise<{ ok: boolean; cancelled?: boolean; error?: string }>;
        open_project: () => Promise<{
          ok: boolean;
          cancelled?: boolean;
          error?: string;
          project?: Project;
        }>;
        export_kompas: (project: Project) => Promise<CommandResponse>;
        select_solidworks_template: (kind: "part" | "assembly") => Promise<SolidWorksTemplateResponse>;
        select_solidworks_material_library: () => Promise<SolidWorksMaterialsResponse>;
        solidworks_export_settings: () => Promise<SolidWorksSettingsResponse>;
        save_solidworks_export_settings: (options: SolidWorksOptions) => Promise<CommandResponse>;
        export_solidworks: (project: Project, options: SolidWorksOptions) => Promise<CommandResponse>;
        select_drawing_template: (cad: DrawingCad) => Promise<SolidWorksTemplateResponse>;
        drawing_settings: () => Promise<DrawingTemplatesResponse>;
        save_drawing_template: (cad: DrawingCad, template: string) => Promise<CommandResponse>;
        create_drawings: (project: Project, cad: DrawingCad, scope: DrawingScope, template: string | null) => Promise<CommandResponse>;
        import_step_model: () => Promise<StepImportOperation>;
        step_import_status: (operationId: string) => Promise<StepImportOperation>;
        cancel_step_import: (operationId: string) => Promise<StepImportOperation>;
        step_model_snapshot: (operationId: string) => Promise<StepModelResponse>;
        build_step_pallet: (operationId: string, project: Project, faceIndex: number) => Promise<StepPalletResponse>;
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
  const [savedProject, setSavedProject] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [update, setUpdate] = useState<UpdateStatus>({ state: "idle" });
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [distanceText, setDistanceText] = useState<Record<string, string>>({});
  const [marginDrafts, setMarginDrafts] = useState<Partial<Record<MarginIndex, string>>>({});
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);
  const [draggedLayerId, setDraggedLayerId] = useState<string | null>(null);
  const [dropLayerId, setDropLayerId] = useState<string | null>(null);
  const [dropAfterLayer, setDropAfterLayer] = useState(false);
  const [hiddenLayerIds, setHiddenLayerIds] = useState<string[]>([]);
  const [camera, setCamera] = useState<CameraPreset>("isometric");
  const [viewportExpanded, setViewportExpanded] = useState(false);
  const [cameraRequest, setCameraRequest] = useState(0);
  const [fitRequest, setFitRequest] = useState(0);
  const [stepImport, setStepImport] = useState<StepImportOperation | null>(null);
  const [stepModel, setStepModel] = useState<StepModelSnapshot | null>(null);
  const [selectedStepFace, setSelectedStepFace] = useState<number | null>(null);
  const [stepPalletBuilt, setStepPalletBuilt] = useState(false);
  const [solidWorksOptions, setSolidWorksOptions] = useState<SolidWorksOptions | null>(storedSolidWorksOptions);
  const [solidWorksMaterials, setSolidWorksMaterials] = useState<string[]>([]);
  const [exporting, setExporting] = useState<"kompas" | "solidworks" | "drawings" | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [exportChoiceOpen, setExportChoiceOpen] = useState(false);
  const [solidWorksSetupOpen, setSolidWorksSetupOpen] = useState(false);
  const [solidWorksDraft, setSolidWorksDraft] = useState<SolidWorksOptions | null>(null);
  const [solidWorksSetupError, setSolidWorksSetupError] = useState<string | null>(null);
  const [drawingsSetupOpen, setDrawingsSetupOpen] = useState(false);
  const [drawingCad, setDrawingCad] = useState<DrawingCad>("solidworks");
  const [drawingScope, setDrawingScope] = useState<DrawingScope>("assembly");
  const [drawingTemplates, setDrawingTemplates] = useState<Partial<Record<DrawingCad, string>>>({});
  const [drawingSetupError, setDrawingSetupError] = useState<string | null>(null);
  const [buildingStepPallet, setBuildingStepPallet] = useState(false);
  const [selectedBeams, setSelectedBeams] = useState<ViewportBeam[]>([]);
  const [beamTool, setBeamTool] = useState<"none" | "delete" | "section">("none");
  const [section, setSection] = useState<BeamSection>({
    height: 70,
    width: 50,
  });
  const [sectionPreset, setSectionPreset] = useState<SectionPresetId>("70x50");
  const [customLayerSectionIds, setCustomLayerSectionIds] = useState<string[]>([]);
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
  const [viewportToolError, setViewportToolError] = useState<string | null>(null);
  const [viewportToolErrorVersion, setViewportToolErrorVersion] = useState(0);
  const [, setHistoryVersion] = useState(0);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const undoStack = useRef<Project[]>([]);
  const redoStack = useRef<Project[]>([]);
  const formEditStart = useRef<Project | null>(null);
  const viewportToolErrorTimeout = useRef<number | null>(null);
  const lastNotifiedCalculationError = useRef<string | null>(null);
  const connectionStarted = useRef(false);
  const calculatedInitialProject = useRef<Project | null>(null);
  const stepPlacement = useRef<{ transform: number[]; starts: [number, number] } | null>(null);

  const reportFirstViewportFrame = useCallback(() => {
    reportStartupStage("первый кадр 3D-вида");
  }, []);

  function showViewportToolError(message: string) {
    if (viewportToolErrorTimeout.current !== null) {
      window.clearTimeout(viewportToolErrorTimeout.current);
    }
    setViewportToolError(message);
    setViewportToolErrorVersion((value) => value + 1);
    viewportToolErrorTimeout.current = window.setTimeout(() => {
      viewportToolErrorTimeout.current = null;
      setViewportToolError(null);
    }, 5_000);
  }

  useEffect(() => () => {
    if (viewportToolErrorTimeout.current !== null) window.clearTimeout(viewportToolErrorTimeout.current);
  }, []);

  useEffect(() => {
    if (!calculationError) {
      lastNotifiedCalculationError.current = null;
      return;
    }
    if (lastNotifiedCalculationError.current === calculationError) return;
    lastNotifiedCalculationError.current = calculationError;
    showViewportToolError(calculationError);
  }, [calculationError]);

  function applyProject(nextProject: Project) {
    setProject(nextProject);
    setCamera(nextProject.view.camera);
    setHiddenLayerIds(nextProject.view.hidden_layer_ids);
    setCustomLayerSectionIds(
      nextProject.pallet.layers
        .filter((layer) => sectionPresetFor(layer.direction) === "custom")
        .map((layer) => layer.id),
    );
    setDistanceText(
      Object.fromEntries(
        nextProject.pallet.layers.map((layer) => [
          layer.id,
          layer.direction.support_distances.join(" "),
        ]),
      ),
    );
    setExpandedLayerId((current) =>
      nextProject.pallet.layers.some((layer) => layer.id === current)
        ? current
        : nextProject.pallet.layers[0]?.id ?? null,
    );
  }

  function updateHistory(previous: Project, next: Project) {
    if (projectsMatch(previous, next)) return;
    undoStack.current.push(copyProject(previous));
    if (undoStack.current.length > HISTORY_LIMIT) undoStack.current.shift();
    redoStack.current = [];
    setHistoryVersion((value) => value + 1);
  }

  function updateProject(nextProject: Project) {
    if (!project) return;
    updateHistory(project, nextProject);
    applyProject(nextProject);
  }

  function beginFormEdit() {
    if (project && !formEditStart.current) formEditStart.current = copyProject(project);
  }

  function finishFormEdit() {
    const previous = formEditStart.current;
    formEditStart.current = null;
    if (previous && project) updateHistory(previous, project);
  }

  function clearInteractionState() {
    setSelectedBeams([]);
    setBeamTool("none");
    stopDimensionEditing();
    stopInsertion();
  }

  function undo() {
    finishFormEdit();
    const previous = undoStack.current.pop();
    if (!project || !previous) return;
    redoStack.current.push(copyProject(project));
    applyProject(previous);
    clearInteractionState();
    setHistoryVersion((value) => value + 1);
  }

  function redo() {
    finishFormEdit();
    const next = redoStack.current.pop();
    if (!project || !next) return;
    undoStack.current.push(copyProject(project));
    applyProject(next);
    clearInteractionState();
    setHistoryVersion((value) => value + 1);
  }

  function applyCalculation(response: CalculationResponse) {
    // Invalid intermediate form values must not discard the last valid 3D
    // snapshot. Keeping it visible lets a user correct the input immediately.
    if (response.ok && response.snapshot) {
      setCalculation(response);
      setCalculationError(null);
    } else {
      const message = response.error ?? "Не удалось рассчитать поддон.";
      if (insertionMode || beamTool !== "none" || dimensionEditing) {
        showViewportToolError(message);
      } else {
        setCalculationError(message);
      }
    }
  }

  useEffect(() => {
    async function connect() {
      if (connectionStarted.current) return;
      const api = window.pywebview?.api;
      if (!api) return;
      connectionStarted.current = true;
      try {
        reportStartupStage("мост Python подключён");
        const [nextStatus, defaultProject] = await Promise.all([
          api.status(),
          api.default_project(),
        ]);
        const recovered = recoveredProject();
        const initialProject = recovered ?? (defaultProject as Project);
        const initialCalculation = await api.calculate(initialProject);
        reportStartupStage("первый расчёт завершён");
        if (recovered) {
          if (initialCalculation.ok && initialCalculation.snapshot) {
            calculatedInitialProject.current = initialCalculation.snapshot.project;
            applyProject(initialCalculation.snapshot.project);
            applyCalculation(initialCalculation);
            setRecoveryNotice("Восстановлен последний автосохранённый проект.");
          } else {
            discardRecoveredProject();
            applyProject(defaultProject as Project);
          }
        } else {
          if (initialCalculation.ok && initialCalculation.snapshot) {
            calculatedInitialProject.current = initialCalculation.snapshot.project;
            applyProject(initialCalculation.snapshot.project);
            applyCalculation(initialCalculation);
          } else {
            applyProject(defaultProject as Project);
          }
        }
        setStatus(nextStatus);
        // These settings are only needed when their export dialogs are opened.
        // Do not make the first usable 3D view wait for two extra bridge calls.
        void api.solidworks_export_settings()
          .then((savedSolidWorksSettings) => {
            if (savedSolidWorksSettings.ok && savedSolidWorksSettings.options) {
              setSolidWorksOptions(savedSolidWorksSettings.options);
            }
          })
          .catch(() => undefined);
        void api.drawing_settings()
          .then((savedDrawingSettings) => {
            if (savedDrawingSettings.ok && savedDrawingSettings.templates) {
              setDrawingTemplates(savedDrawingSettings.templates);
            }
          })
          .catch(() => undefined);
      } catch {
        setStatus(null);
      }
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
    if (calculatedInitialProject.current === project) {
      calculatedInitialProject.current = null;
      return;
    }
    const timeout = window.setTimeout(() => {
      void calculateProject();
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [project, status]);

  useEffect(() => {
    if (!status) return undefined;
    const timeout = window.setTimeout(() => {
      void window.pywebview?.api?.check_update().then(setUpdate).catch(() => undefined);
    }, 1500);
    return () => window.clearTimeout(timeout);
  }, [status]);

  useEffect(() => {
    if (update.state !== "checking" && update.state !== "downloading") return undefined;
    const timer = window.setInterval(() => {
      void window.pywebview?.api?.update_status().then(setUpdate).catch(() => undefined);
    }, 500);
    return () => window.clearInterval(timer);
  }, [update.state]);

  useEffect(() => {
    if (!project) return;
    const timeout = window.setTimeout(() => {
      try {
        window.localStorage.setItem(AUTOSAVE_KEY, JSON.stringify(project));
      } catch {
        // Recovery must not prevent editing when browser storage is unavailable.
      }
    }, 1000);
    return () => window.clearTimeout(timeout);
  }, [project]);

  async function saveProject(saveAs = false) {
    if (!project || saving) return;
    const savedVersion = JSON.stringify(project);
    setSaving(true);
    let response: { ok: boolean; cancelled?: boolean; error?: string };
    try {
      response = await window.pywebview!.api!.save_project(project, saveAs);
    } catch {
      setCalculationError("Не удалось сохранить проект.");
      return;
    } finally {
      setSaving(false);
    }
    if (response.ok) {
      setSavedProject(savedVersion);
      discardRecoveredProject();
      setRecoveryNotice(null);
    } else if (!response.cancelled)
      setCalculationError(response.error ?? "Не удалось сохранить проект.");
  }
  async function openProject() {
    const response = await window.pywebview!.api!.open_project();
    if (response.project) {
      applyProject(response.project);
      setSavedProject(JSON.stringify(response.project));
      setCalculationError(null);
      undoStack.current = [];
      redoStack.current = [];
      discardRecoveredProject();
      setRecoveryNotice(null);
      setHistoryVersion((value) => value + 1);
    } else if (!response.cancelled) {
      setCalculationError(response.error ?? "Не удалось открыть проект.");
    }
  }

  async function rememberSolidWorksOptions(options: SolidWorksOptions): Promise<boolean> {
    setSolidWorksOptions(options);
    try {
      window.localStorage.setItem(SOLIDWORKS_OPTIONS_KEY, JSON.stringify(options));
    } catch {
      // Export configuration is optional when embedded storage is unavailable.
    }
    const response = await window.pywebview?.api?.save_solidworks_export_settings(options);
    if (!response?.ok) {
      setSolidWorksSetupError(response?.error ?? "Не удалось сохранить настройки экспорта SolidWorks.");
      return false;
    }
    return true;
  }

  async function selectSolidWorksTemplate(kind: "part" | "assembly") {
    const response = await window.pywebview?.api?.select_solidworks_template(kind);
    if (!response || response.cancelled) return;
    if (!response.ok || !response.path) {
      setSolidWorksSetupError(response?.error ?? "Не удалось выбрать шаблоны SolidWorks.");
      return;
    }
    const previous = solidWorksDraft ?? solidWorksOptions ?? storedSolidWorksOptions();
    setSolidWorksDraft({
      partTemplate: kind === "part" ? response.path : previous?.partTemplate ?? "",
      assemblyTemplate: kind === "assembly" ? response.path : previous?.assemblyTemplate ?? "",
      materialLibrary: previous?.materialLibrary ?? "",
      materialName: previous?.materialName ?? "",
    });
  }

  async function selectSolidWorksMaterialLibrary() {
    const response = await window.pywebview?.api?.select_solidworks_material_library();
    if (!response || response.cancelled) return;
    if (!response.ok || !response.materialLibrary || !response.materials?.length) {
      setSolidWorksSetupError(response?.error ?? "Не удалось прочитать библиотеку материалов SolidWorks.");
      return;
    }
    const previous = solidWorksDraft ?? solidWorksOptions ?? storedSolidWorksOptions();
    const materialName = response.materials.includes(previous?.materialName ?? "")
      ? previous!.materialName
      : response.materials[0];
    setSolidWorksMaterials(response.materials);
    setSolidWorksDraft({
      partTemplate: previous?.partTemplate ?? "",
      assemblyTemplate: previous?.assemblyTemplate ?? "",
      materialLibrary: response.materialLibrary,
      materialName,
    });
  }

  function openSolidWorksSetup() {
    setSolidWorksSetupError(null);
    setSolidWorksDraft(solidWorksOptions ?? storedSolidWorksOptions() ?? {
      partTemplate: "",
      assemblyTemplate: "",
      materialLibrary: "",
      materialName: "",
    });
    setSolidWorksSetupOpen(true);
  }

  async function exportKompas() {
    const api = window.pywebview?.api;
    if (!api || !project) return;
    setExporting("kompas");
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    try {
      const response = await api.export_kompas(project);
      if (!response.cancelled) {
        setExportResult({
          target: "КОМПАС-3D",
          ok: response.ok,
          message: response.ok
            ? `Экспорт завершён. Файлы сохранены в папке:\n${response.output}`
            : response.error ?? "Экспорт в КОМПАС-3D не выполнен.",
        });
      }
    } finally {
      setExporting(null);
    }
  }

  async function exportSolidWorks(options: SolidWorksOptions) {
    const api = window.pywebview?.api;
    if (!api || !project) return;
    setExporting("solidworks");
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    try {
      const response = await api.export_solidworks(project, options);
      if (!response.cancelled) {
        setExportResult({
          target: "SolidWorks",
          ok: response.ok,
          message: response.ok
            ? `Экспорт завершён. Файлы сохранены в папке:\n${response.output}`
            : response.error ?? "Экспорт в SolidWorks не выполнен.",
        });
      }
    } finally {
      setExporting(null);
    }
  }

  function beginSolidWorksExport() {
    if (!solidWorksOptions || Object.values(solidWorksOptions).some((value) => !value)) {
      openSolidWorksSetup();
      return;
    }
    void exportSolidWorks(solidWorksOptions);
  }

  function saveSolidWorksSetup() {
    if (!solidWorksDraft || Object.values(solidWorksDraft).some((value) => !value)) return;
    void (async () => {
      if (!await rememberSolidWorksOptions(solidWorksDraft)) return;
      setSolidWorksSetupError(null);
      setSolidWorksSetupOpen(false);
    })();
  }

  async function selectDrawingTemplate() {
    const api = window.pywebview?.api;
    if (!api) return;
    const response = await api.select_drawing_template(drawingCad);
    if (!response || response.cancelled) return;
    if (!response.ok || !response.path) {
      setDrawingSetupError(response?.error ?? "Не удалось выбрать шаблон чертежа.");
      return;
    }
    const saved = await api.save_drawing_template(drawingCad, response.path);
    if (!saved.ok) {
      setDrawingSetupError(saved.error ?? "Не удалось сохранить шаблон чертежа.");
      return;
    }
    setDrawingTemplates((current) => ({ ...current, [drawingCad]: response.path! }));
    setDrawingSetupError(null);
  }

  function openDrawingsSetup() {
    setDrawingSetupError(null);
    setDrawingsSetupOpen(true);
  }

  async function createDrawings() {
    const api = window.pywebview?.api;
    if (!api || !project) return;
    setDrawingsSetupOpen(false);
    setExporting("drawings");
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    try {
      const response = await api.create_drawings(project, drawingCad, drawingScope, drawingTemplates[drawingCad] ?? null);
      if (!response.cancelled) {
        const target = drawingCad === "solidworks" ? "Чертежи SolidWorks" : "Чертежи КОМПАС-3D";
        setExportResult({
          target,
          ok: response.ok,
          message: response.ok
            ? `Чертежи сохранены в папке:\n${response.output}`
            : response.error ?? "Создание чертежей не выполнено.",
        });
      }
    } finally {
      setExporting(null);
    }
  }

  async function importStepModel() {
    const api = window.pywebview?.api;
    if (!api) return;
    const response = await api.import_step_model();
    if (response.cancelled) return;
    setStepModel(null);
    setSelectedStepFace(null);
    setStepPalletBuilt(false);
    setBuildingStepPallet(false);
    setStepImport(response);
  }

  async function cancelStepImport() {
    const api = window.pywebview?.api;
    if (!api || !stepImport?.operationId) return;
    setStepImport(await api.cancel_step_import(stepImport.operationId));
  }

  useEffect(() => {
    if (!stepImport?.operationId || !["running", "cancelling"].includes(stepImport.state ?? "")) return;
    const timeout = window.setTimeout(async () => {
      const api = window.pywebview?.api;
      if (api) setStepImport(await api.step_import_status(stepImport.operationId!));
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [stepImport]);

  useEffect(() => {
    if (stepImport?.state === "failed") {
      setCalculationError(stepImport.error ?? "Не удалось импортировать STEP-модель.");
    }
  }, [stepImport?.error, stepImport?.state]);

  useEffect(() => {
    async function loadPreparedModel() {
      const api = window.pywebview?.api;
      if (!api || !stepImport?.operationId || stepImport.state !== "completed") return;
      try {
        const response = await api.step_model_snapshot(stepImport.operationId);
        if (response.ok && response.assetUrl) {
          const { prepareStepModel } = await import("./stepModelGeometry");
          const prepared = await prepareStepModel({ assetUrl: response.assetUrl } satisfies StepModelPayload);
          setStepModel(prepared);
          setFitRequest((value) => value + 1);
        } else {
          setCalculationError(response.error ?? "Не удалось подготовить STEP-модель для просмотра.");
        }
      } catch (error) {
        setCalculationError(error instanceof Error ? error.message : "Не удалось подготовить STEP-модель для просмотра.");
      }
    }
    void loadPreparedModel();
  }, [stepImport?.operationId, stepImport?.state]);

  async function buildStepPallet(faceIndex = selectedStepFace) {
    const api = window.pywebview?.api;
    if (!api || !project || !stepImport?.operationId || faceIndex === null || buildingStepPallet) return;
    setBuildingStepPallet(true);
    try {
      const response = await api.build_step_pallet(stepImport.operationId, project, faceIndex);
      applyCalculation(response);
      if (response.ok && response.snapshot && response.modelTransform) {
        const margins = palletMargins(response.snapshot.project);
        stepPlacement.current = {
          transform: response.modelTransform,
          starts: [margins[0], margins[2]],
        };
        updateHistory(project, response.snapshot.project);
        applyProject(response.snapshot.project);
        setStepModel((model) => model ? { ...model, transform: response.modelTransform! } : model);
        setSelectedStepFace(null);
        setStepPalletBuilt(true);
        setFitRequest((value) => value + 1);
        setCalculationError(null);
      }
    } catch (error) {
      setCalculationError(error instanceof Error ? error.message : "Не удалось построить поддон по модели.");
    } finally {
      setBuildingStepPallet(false);
    }
  }

  function selectStepSupport(faceId: number) {
    if (stepPalletBuilt || buildingStepPallet) return;
    setSelectedStepFace(faceId);
    // The established desktop workflow starts the calculation directly from a
    // support-face click.  Keeping the web flow identical also prevents the
    // selected model from looking like a completed, but empty, operation.
    void buildStepPallet(faceId);
  }

  async function resetProject() {
    const api = window.pywebview?.api;
    if (!api || !project) return;
    const defaultProject = (await api.default_project()) as Project;
    // The desktop reset restores the example geometry but intentionally keeps
    // the material selection, so both frontends have the same semantics.
    const nextProject = {
      ...defaultProject,
      pallet: { ...defaultProject.pallet, material_id: project.pallet.material_id },
    };
    updateProject(nextProject);
    setStepImport(null);
    setStepModel(null);
    setSelectedStepFace(null);
    setStepPalletBuilt(false);
    setBuildingStepPallet(false);
    clearInteractionState();
    setCalculationError(null);
  }

  function basePointDistance(support: { beam: ViewportBeam; point: ViewportPoint }) {
    const alongX = support.beam.size[0] >= support.beam.size[1];
    return (alongX ? support.point[0] : support.point[2]) * 1000 - section.width / 2;
  }

  function toggleBeam(beam: ViewportBeam, point?: ViewportPoint, normal?: ViewportFaceNormal) {
    if (insertionMode) {
      if (manualReferenceMode === "face" && manualSupports.length === 2) {
        const support = manualSupports[0].beam;
        const alongX = support.size[0] >= support.size[1];
        const directionalNormal = alongX ? normal?.[0] : normal?.[2];
        if (directionalNormal === undefined || Math.abs(directionalNormal) < 0.9) {
          showViewportToolError("Выберите боковую грань бруса в направлении нового бруса.");
          return;
        }
        setManualReference(beam);
        setManualReferenceFace(
          alongX
            ? directionalNormal > 0 ? "x_max" : "x_min"
            : directionalNormal > 0 ? "y_max" : "y_min",
        );
        setManualDistance(0);
        return;
      }
      if (manualSupports.length === 1 && manualSupports[0].beam.physicalLayerId !== beam.physicalLayerId) {
        showViewportToolError("Вторую опору нужно выбрать на том же слое, что и первую.");
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
      if (manualSupports.length === 0) {
        setManualDistance(basePointDistance(support));
      }
      setManualSupports((current) =>
        current.length === 2 ? [support] : [...current, support],
      );
      return;
    } else if (beamTool === "none") {
      return;
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
      updateHistory(project, response.snapshot.project);
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
      updateHistory(project, response.snapshot.project);
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
      updateHistory(project, response.snapshot.project);
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
    setManualReferenceFace("x_min");
    setManualReferenceMode("base");
    setSelectedBeams([]);
  }

  function undoLastToolSelection() {
    setViewportToolError(null);
    if (!stepPalletBuilt && !buildingStepPallet && stepModel) {
      setSelectedStepFace(null);
      return;
    }
    if (insertionMode) {
      if (manualReference) {
        setManualReference(null);
        return;
      }
      setManualSupports((current) => current.slice(0, -1));
      return;
    }
    if (beamTool !== "none") {
      setSelectedBeams((current) => current.slice(0, -1));
      return;
    }
    if (dimensionEditing) setSelectedDimension(null);
  }

  function activateBeamTool(tool: "delete" | "section") {
    stopDimensionEditing();
    stopInsertion();
    setBeamTool(tool);
    setSelectedBeams([]);
  }

  function activateDimensionEditing() {
    stopInsertion();
    setBeamTool("none");
    setSelectedBeams([]);
    setDimensionEditing(true);
  }

  function activateInsertion() {
    stopDimensionEditing();
    setBeamTool("none");
    setSelectedBeams([]);
    setInsertionMode(true);
  }

  async function insertSelectedBeam() {
    const api = window.pywebview?.api;
    if (!api || !project || !selectedSlot) return;
    const response = await api.insert_beam(project, selectedSlot, insertionGap);
    applyCalculation(response);
    if (response.ok && response.snapshot) {
      updateHistory(project, response.snapshot.project);
      applyProject(response.snapshot.project);
      setSelectedSlot(null);
    }
  }

  function selectInsertion(marker: ViewportInsertionMarker) {
    setSelectedSlot(marker.slot);
    setInsertionGap(marker.slot.suggestedClearGap);
  }

  async function addManualBeam() {
    const api = window.pywebview?.api;
    if (!api || !project || manualSupports.length !== 2
        || (manualReferenceMode === "face" && !manualReference)) return;
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
    if (!response.ok) {
      showViewportToolError(response.error ?? "Не удалось добавить брус.");
      return;
    }
    applyCalculation(response);
    if (response.snapshot) {
      updateHistory(project, response.snapshot.project);
      applyProject(response.snapshot.project);
      setManualSupports([]);
      setManualReference(null);
      setSelectedBeams([]);
    }
  }

  useEffect(() => {
    const handleKeyboardShortcut = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        stopDimensionEditing();
        stopInsertion();
        setBeamTool("none");
        setSelectedBeams([]);
        return;
      }
      if (
        event.key === "Enter" &&
        !dimensionEditing &&
        !insertionMode &&
        !(event.target instanceof HTMLButtonElement)
      ) {
        if (beamTool === "delete" && selectedBeams.length > 0) {
          event.preventDefault();
          void deleteSelectedBeams();
        } else if (beamTool === "section" && selectedBeams.length > 0) {
          event.preventDefault();
          void changeSelectedBeamSections();
        }
        return;
      }
      if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
      // `key` follows the active keyboard layout (for example, "я" under a
      // Russian layout). `code` denotes the physical Z/Y key and therefore
      // makes project history shortcuts layout-independent.
      if (event.code === "KeyZ") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if (event.code === "KeyY") {
        event.preventDefault();
        redo();
      }
    };
    // Capture runs before the browser applies native undo/redo to an input.
    window.addEventListener("keydown", handleKeyboardShortcut, true);
    return () =>
      window.removeEventListener("keydown", handleKeyboardShortcut, true);
  });

  function updateLayerDirection(
    index: number,
    field: DirectionField,
    value: string,
  ) {
    if (!project) return;
    const layer = project.pallet.layers[index];
    if (!layer) return;
    if (field === "support_distances") {
      setDistanceText({ ...distanceText, [layer.id]: value });
      const distances = value.split(/\s+/).filter(Boolean).map(Number);
      if (distances.some(Number.isNaN)) return;
      updateLayerDirectionValue(index, field, distances);
      return;
    }
    updateLayerDirectionValue(index, field, Number(value));
  }

  function updateLayerDirectionValue(
    index: number,
    field: DirectionField,
    parsed: number | number[],
  ) {
    updateLayerDirectionPatch(index, { [field]: parsed } as Partial<Direction>);
  }

  function updateLayerDirectionPatch(index: number, patch: Partial<Direction>) {
    if (!project) return;
    const layer = project.pallet.layers[index];
    if (!layer) return;
    const updatedDirection = { ...layer.direction, ...patch } as Direction;
    const targetRawSize = rawPalletSize(updatedDirection);
    const layers = project.pallet.layers.map((item, layerIndex) => {
      if (layerIndex === index) {
        return { ...item, direction: updatedDirection };
      }
      if (item.axis !== layer.axis) return item;

      // Parallel layers may use different support grids, but they form one
      // pallet envelope. Keep their grids intact and move only the dependent
      // end margin, matching the established legacy editor behaviour.
      const marginEnd = item.direction.margin_end + targetRawSize - rawPalletSize(item.direction);
      return { ...item, direction: { ...item.direction, margin_end: marginEnd } };
    });
    setProject({
      ...project,
      pallet: {
        ...project.pallet,
        layers,
      },
    });
  }

  function updatePalletMargin(index: MarginIndex, value: string) {
    if (!project) return;
    if (value.trim() === "") return;
    const next = Number(value);
    if (!Number.isFinite(next) || next < 0) return;
    setProject(changePalletMargin(project, index, next));
  }

  function layerSectionPreset(layer: Layer): SectionPresetId {
    return customLayerSectionIds.includes(layer.id)
      ? "custom"
      : sectionPresetFor(layer.direction);
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
    updateProject({
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
        ? { ...layer, axis, direction: { ...project.pallet[axis] } }
        : layer,
    );
    updateProject({ ...project, pallet: { ...project.pallet, layers } });
  }

  function addLayer() {
    if (!project) return;
    const nextNumber = Math.max(
      ...project.pallet.layers.map((layer, index) => layerNumber(layer, index)),
      0,
    ) + 1;
    const layerId = `layer-${nextNumber === 3 ? 1 : nextNumber - 1}`;
    const source = project.pallet.layers.at(-2) ?? project.pallet.layers.at(-1);
    updateProject({
      ...project,
      pallet: {
        ...project.pallet,
        layers: [
          ...project.pallet.layers,
          source
            ? { id: layerId, axis: source.axis, direction: { ...source.direction, support_distances: [...source.direction.support_distances] } }
            : { id: layerId, axis: "length", direction: { ...project.pallet.length } },
        ],
      },
    });
    setExpandedLayerId(layerId);
  }

  function layerNumber(layer: Layer, fallbackIndex: number) {
    if (layer.id === "length") return 1;
    if (layer.id === "width") return 2;
    const suffix = /^layer-(\d+)$/.exec(layer.id)?.[1];
    if (suffix === undefined) return fallbackIndex + 1;
    return suffix === "1" ? 3 : Number(suffix) + 1;
  }

  function toggleLayerVisibility(layerId: string) {
    if (!project) return;
    const hiddenLayerIds = project.view.hidden_layer_ids.includes(layerId)
      ? project.view.hidden_layer_ids.filter((id) => id !== layerId)
      : [...project.view.hidden_layer_ids, layerId];
    setHiddenLayerIds(hiddenLayerIds);
    updateProject({
      ...project,
      view: { ...project.view, hidden_layer_ids: hiddenLayerIds },
    });
    setSelectedBeams((current) => current.filter((beam) => beam.layerId !== layerId));
    setManualSupports((current) => current.filter(({ beam }) => beam.layerId !== layerId));
    if (manualReference?.layerId === layerId) setManualReference(null);
  }

  function moveLayer(sourceId: string, targetId: string, insertAfter: boolean) {
    if (!project || sourceId === targetId) return;
    const source = project.pallet.layers.find((layer) => layer.id === sourceId);
    const layers = project.pallet.layers.filter((layer) => layer.id !== sourceId);
    const targetIndex = layers.findIndex((layer) => layer.id === targetId);
    if (!source || targetIndex < 0) return;
    layers.splice(targetIndex + (insertAfter ? 1 : 0), 0, source);
    updateProject({ ...project, pallet: { ...project.pallet, layers } });
  }

  function removeLayer(index: number) {
    if (!project || project.pallet.layers.length <= 2) return;
    const removedLayerId = project.pallet.layers[index]?.id;
    setCustomLayerSectionIds((current) => current.filter((id) => id !== removedLayerId));
    updateProject({
      ...project,
      pallet: {
        ...project.pallet,
        layers: project.pallet.layers.filter(
          (_, layerIndex) => layerIndex !== index,
        ),
      },
      view: {
        ...project.view,
        hidden_layer_ids: project.view.hidden_layer_ids.filter((id) => id !== removedLayerId),
      },
    });
  }

  const rounding = project?.pallet.length.round_pallet_size
    ? (String(project.pallet.length.rounding_step) as "5" | "50")
    : "none";
  const manualHud: ReactNode = insertionMode && manualSupports.length === 2 ? (
    <div className="manual-hud">
      <strong>Новый брус</strong>
      <label>
        Отсчёт расстояния
        <select
          value={manualReferenceMode}
          onChange={(event) => {
            const mode = event.target.value as "base" | "face";
            setManualReferenceMode(mode);
            setManualReference(null);
            setManualDistance(mode === "base" ? basePointDistance(manualSupports[0]) : 0);
          }}
        >
          <option value="base">От нулевой точки</option>
          <option value="face">От выбранной грани</option>
        </select>
      </label>
      {manualReferenceMode === "face" ? (
        manualReference ? (
          <span>Опора: {manualReference.layerId} · брус {manualReference.layerIndex + 1}</span>
        ) : (
          <span>Выберите боковую грань в 3D-виде</span>
        )
      ) : null}
      <label>
        Расстояние, мм
        <input
          type="number"
          value={manualDistance}
          onChange={(event) => setManualDistance(Number(event.target.value))}
          onKeyDown={(event) => {
            if (event.key === "Enter") void addManualBeam();
            if (event.key === "Escape") stopInsertion();
          }}
        />
      </label>
      <button type="button" onClick={addManualBeam} disabled={manualReferenceMode === "face" && !manualReference}>Добавить брус</button>
      <button type="button" onClick={stopInsertion}>Отмена</button>
    </div>
  ) : null;
  const dimensionHud: ReactNode = dimensionEditing && selectedDimension ? (
    <div className="manual-hud">
      <strong>Изменить расстояние</strong>
      <label>
        Значение, мм
        <input
          type="number"
          autoFocus
          value={distanceValue}
          onChange={(event) => setDistanceValue(Number(event.target.value))}
          onKeyDown={(event) => {
            if (event.key === "Enter") void changeSelectedDistance();
            if (event.key === "Escape") stopDimensionEditing();
          }}
        />
      </label>
      <button type="button" onClick={changeSelectedDistance}>Применить</button>
      <button type="button" onClick={stopDimensionEditing}>Отмена</button>
    </div>
  ) : null;
  const sectionHud: ReactNode = beamTool === "section" && selectedBeams.length > 0 ? (
    <div className="manual-hud section-hud">
      <strong>Сечение бруса{selectedBeams.length > 1 ? ` · ${selectedBeams.length}` : ""}</strong>
      <label>
        Стандартное сечение
        <select
          value={sectionPreset}
          onChange={(event) => {
            const presetId = event.target.value as SectionPresetId;
            setSectionPreset(presetId);
            const preset = SECTION_PRESETS.find((item) => item.id === presetId);
            if (preset && "height" in preset && "width" in preset) {
              setSection({ height: preset.height, width: preset.width });
            }
          }}
        >
          {SECTION_PRESETS.map((preset) => (
            <option key={preset.id} value={preset.id}>{preset.label}</option>
          ))}
        </select>
      </label>
      <div className="section-hud-dimensions">
        <label>
          Высота, мм
          <input
            type="number"
            min="1"
            value={section.height}
            disabled={sectionPreset !== "custom"}
            onChange={(event) => setSection({ ...section, height: Number(event.target.value) })}
          />
        </label>
        <label>
          Ширина, мм
          <input
            type="number"
            min="1"
            value={section.width}
            disabled={sectionPreset !== "custom"}
            onChange={(event) => setSection({ ...section, width: Number(event.target.value) })}
          />
        </label>
      </div>
      <button type="button" onClick={() => void changeSelectedBeamSections()}>Применить</button>
      <button type="button" onClick={() => { setBeamTool("none"); setSelectedBeams([]); }}>Отмена</button>
    </div>
  ) : null;
  const viewportToolbar: ReactNode = (
    <>
      {viewportExpanded ? <button type="button" className="secondary" onClick={addLayer} disabled={!project}>Добавить слой</button> : null}
      <div className="viewport-tool-group viewport-history-actions">
        <button type="button" className="secondary" onClick={undo} disabled={!project || undoStack.current.length === 0}>Назад</button>
        <button type="button" className="secondary" onClick={redo} disabled={!project || redoStack.current.length === 0}>Вперёд</button>
      </div>
      <div className="viewport-tool-group viewport-mode-actions">
        <button type="button" className={insertionMode ? "active-tool" : ""} onClick={() => insertionMode ? stopInsertion() : activateInsertion()}>Добавить брус</button>
        <button
          type="button"
          className={beamTool === "delete" ? "active-tool" : ""}
          onClick={() => {
            if (beamTool !== "delete") {
              activateBeamTool("delete");
            } else if (selectedBeams.length > 0) {
              void deleteSelectedBeams();
            } else {
              setBeamTool("none");
            }
          }}
        >
          {beamTool === "delete" ? `Удалить (${selectedBeams.length})` : "Удалить брус"}
        </button>
        <button type="button" className={beamTool === "section" ? "active-tool" : ""} onClick={() => beamTool === "section" ? (setBeamTool("none"), setSelectedBeams([])) : activateBeamTool("section")}>Изменить сечение</button>
        <button type="button" className={dimensionEditing ? "active-tool" : ""} onClick={() => dimensionEditing ? stopDimensionEditing() : activateDimensionEditing()}>Изменить расстояние</button>
      </div>
      {viewportExpanded && calculation?.snapshot?.pallet ? (
        <span className="viewport-toolbar-summary">
          Длина: {formatMillimetres(calculation.snapshot.pallet.size.length)} мм · Ширина: {formatMillimetres(calculation.snapshot.pallet.size.width)} мм · Высота: {formatMillimetres(calculation.snapshot.pallet.size.height)} мм · {calculation.snapshot.pallet.beams.length} шт.
        </span>
      ) : <div className="viewport-tool-spacer" />}
      <label className="viewport-view-select">
        <span>Вид</span>
        <select
          value={camera}
          onChange={(event) => {
            if (!project) return;
            const preset = event.target.value as CameraPreset;
            setCamera(preset);
            setCameraRequest((value) => value + 1);
            updateProject({ ...project, view: { ...project.view, camera: preset } });
          }}
        >
          <option value="isometric">Изометрия</option>
          <option value="top">Сверху</option>
          <option value="front">Спереди</option>
          <option value="side">Сбоку</option>
        </select>
      </label>
      <button type="button" className="secondary" onClick={() => setViewportExpanded((value) => !value)} aria-pressed={viewportExpanded} aria-label={viewportExpanded ? "Свернуть область просмотра" : "Развернуть область просмотра"}>
        {viewportExpanded ? "Свернуть" : "Развернуть"}
      </button>
    </>
  );

  return (
    <main className="app-shell">
      <header className="app-header">
        <strong className="app-brand">PalletLab</strong>
        <nav className="app-actions" aria-label="Действия с проектом">
          <button type="button" className="secondary" onClick={openProject} disabled={!status}>Открыть</button>
          <button type="button" className="secondary" onClick={() => void saveProject()} disabled={!project || saving || JSON.stringify(project) === savedProject}>Сохранить</button>
          <button type="button" className="secondary" onClick={() => void saveProject(true)} disabled={!project || saving}>Сохранить как</button>
          <button
            type="button"
            className="secondary"
            onClick={() => void importStepModel()}
            disabled={!status || stepImport?.state === "running" || stepImport?.state === "cancelling"}
          >
            Импорт
          </button>
          <button type="button" onClick={() => setExportChoiceOpen(true)} disabled={!project || exporting !== null}>
            Экспорт
          </button>
          <button type="button" className="secondary" onClick={openDrawingsSetup} disabled={!project || exporting !== null}>
            Создать чертёж
          </button>
        </nav>
        {updateDismissed && ["available", "ready", "failed"].includes(update.state) ? (
          <button type="button" className="secondary" onClick={() => setUpdateDismissed(false)}>Доступно обновление</button>
        ) : null}
        <button type="button" className="secondary export-settings" onClick={openSolidWorksSetup} disabled={!project || exporting !== null}>
          Настройки экспорта
        </button>
      </header>
      <div className={`workspace${viewportExpanded ? " is-viewport-expanded" : ""}`}>
        <aside className="editor-panel" aria-label="Редактор поддона">
          <div className="editor-heading">
            <p className="eyebrow">Редактор</p>
            <p className="status">
              {status ? `${status.application} ${status.version}` : "Подключение…"}
            </p>
          </div>
        {!updateDismissed && ["available", "downloading", "ready", "failed", "installing"].includes(update.state) ? (
          <div className="modal-backdrop">
            <section className="modal progress-modal" role="dialog" aria-modal="true" aria-labelledby="update-title" aria-live="polite">
              <h2 id="update-title">Обновление PalletLab</h2>
              {update.state === "available" ? <p>Доступна версия {update.version}.</p> : null}
              {update.state === "downloading" ? <>
                <p>Скачивание и проверка обновления…</p>
                {update.total ? <progress max={update.total} value={update.received ?? 0} /> : <progress />}
              </> : null}
              {update.state === "ready" ? <>
                <p>Версия {update.version} готова к установке. Приложение закроется.</p>
                {project && JSON.stringify(project) !== savedProject ? <p>Перед установкой сохраните проект.</p> : null}
              </> : null}
              {update.state === "installing" ? <p>Запускается установка обновления…</p> : null}
              {update.error ? <p className="error">{update.error}</p> : null}
              <footer className="modal-actions">
                {update.state !== "downloading" && update.state !== "installing" ? <button type="button" className="secondary" onClick={() => setUpdateDismissed(true)}>Позже</button> : null}
                {update.state === "available" || update.state === "failed" ? <button type="button" onClick={() => void window.pywebview?.api?.download_update().then(setUpdate)}>Скачать</button> : null}
                {update.state === "ready" && project && JSON.stringify(project) !== savedProject ? <button type="button" disabled={saving} onClick={() => void saveProject()}>Сохранить проект</button> : null}
                {update.state === "ready" ? <button type="button" disabled={!project || JSON.stringify(project) !== savedProject || saving} onClick={() => void window.pywebview?.api?.install_update().then(setUpdate)}>Установить</button> : null}
              </footer>
            </section>
          </div>
        ) : null}
        {exportChoiceOpen ? (
          <div className="modal-backdrop" role="presentation">
            <section className="modal export-choice-modal" role="dialog" aria-modal="true" aria-labelledby="export-choice-title">
              <h2 id="export-choice-title">Экспорт модели</h2>
              <p>Выберите CAD-систему для экспорта поддона.</p>
              <div className="export-choice-actions">
                <button type="button" onClick={() => { setExportChoiceOpen(false); void exportKompas(); }}>КОМПАС-3D</button>
                <button type="button" onClick={() => { setExportChoiceOpen(false); beginSolidWorksExport(); }}>SolidWorks</button>
              </div>
              <footer className="modal-actions"><button type="button" className="secondary" onClick={() => setExportChoiceOpen(false)}>Отмена</button></footer>
            </section>
          </div>
        ) : null}
        {solidWorksSetupOpen && solidWorksDraft ? (
          <div className="modal-backdrop" role="presentation">
            <section className="modal" role="dialog" aria-modal="true" aria-labelledby="solidworks-settings-title">
              <h2 id="solidworks-settings-title">Настройка экспорта SolidWorks</h2>
              <p>Выберите шаблоны и библиотеку материалов. Настройка сохранится для следующих запусков.</p>
              <label className="file-field">
                Шаблон детали (.prtdot)
                <div className="file-field-control"><input value={solidWorksDraft.partTemplate} readOnly /><button type="button" onClick={() => void selectSolidWorksTemplate("part")}>Обзор…</button></div>
              </label>
              <label className="file-field">
                Шаблон сборки (.asmdot)
                <div className="file-field-control"><input value={solidWorksDraft.assemblyTemplate} readOnly /><button type="button" onClick={() => void selectSolidWorksTemplate("assembly")}>Обзор…</button></div>
              </label>
              <label className="file-field">
                Библиотека материалов (.sldmat)
                <div className="file-field-control"><input value={solidWorksDraft.materialLibrary} readOnly /><button type="button" onClick={() => void selectSolidWorksMaterialLibrary()}>Обзор…</button></div>
              </label>
              <p className="modal-hint">Стандартный путь: <code>C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\lang\russian\sldmaterials\solidworks materials.sldmat</code></p>
              <label className="material-field">
                Материал SolidWorks
                <select
                  value={solidWorksDraft.materialName}
                  disabled={solidWorksMaterials.length === 0}
                  onChange={(event) => setSolidWorksDraft({ ...solidWorksDraft, materialName: event.target.value })}
                >
                  {solidWorksMaterials.length ? solidWorksMaterials.map((name) => <option key={name} value={name}>{name}</option>) : <option>{solidWorksDraft.materialName || "Сначала выберите библиотеку"}</option>}
                </select>
              </label>
              {solidWorksSetupError ? <p className="error">{solidWorksSetupError}</p> : null}
              <footer className="modal-actions">
                <button type="button" onClick={saveSolidWorksSetup} disabled={Object.values(solidWorksDraft).some((value) => !value)}>Сохранить</button>
                <button type="button" className="secondary" onClick={() => { setSolidWorksSetupError(null); setSolidWorksSetupOpen(false); }}>Отмена</button>
              </footer>
            </section>
          </div>
        ) : null}
        {drawingsSetupOpen ? (
          <div className="modal-backdrop" role="presentation">
            <section className="modal drawing-modal" role="dialog" aria-modal="true" aria-labelledby="drawings-title">
              <h2 id="drawings-title">Создание CAD-чертежей</h2>
              <p>Выберите CAD-систему и состав чертежей. Затем укажите папку ранее экспортированных моделей.</p>
              <label>
                CAD-система
                <select value={drawingCad} onChange={(event) => setDrawingCad(event.target.value as DrawingCad)}>
                  <option value="solidworks">SolidWorks</option>
                  <option value="kompas">КОМПАС-3D</option>
                </select>
              </label>
              <label>
                Состав чертежей
                <select value={drawingScope} onChange={(event) => setDrawingScope(event.target.value as DrawingScope)}>
                  <option value="assembly">Только сборка</option>
                  <option value="parts_and_assembly">Детали и сборка</option>
                </select>
              </label>
              <label className="file-field">
                Шаблон чертежа ({drawingCad === "solidworks" ? ".drwdot" : ".cdt"}, необязательно)
                <div className="file-field-control">
                  <input value={drawingTemplates[drawingCad] ?? ""} readOnly placeholder="Будет использован шаблон CAD по умолчанию" />
                  <button type="button" onClick={() => void selectDrawingTemplate()}>Обзор…</button>
                </div>
              </label>
              <p className="modal-hint">Выбранный шаблон сохраняется для последующих запусков.</p>
              {drawingSetupError ? <p className="error">{drawingSetupError}</p> : null}
              <footer className="modal-actions">
                <button type="button" onClick={() => void createDrawings()}>Выбрать папку и создать</button>
                <button type="button" className="secondary" onClick={() => setDrawingsSetupOpen(false)}>Отмена</button>
              </footer>
            </section>
          </div>
        ) : null}
        {exporting ? (
          <div className="modal-backdrop" role="presentation">
            <section className="modal progress-modal" role="dialog" aria-modal="true" aria-live="polite">
              <h2>Экспорт выполняется</h2>
              <p>{exporting === "drawings" ? "CAD-система создаёт чертежи…" : exporting === "solidworks" ? "SolidWorks создаёт детали и сборку…" : "КОМПАС-3D создаёт детали и сборку…"}</p>
              <progress aria-label="Процесс экспорта" />
              <p className="modal-hint">Не закрывайте PalletLab и CAD-систему до завершения операции.</p>
            </section>
          </div>
        ) : null}
        {exportResult ? (
          <div className="modal-backdrop" role="presentation">
            <section className="modal result-modal" role="dialog" aria-modal="true" aria-labelledby="export-result-title">
              <h2 id="export-result-title">{exportResult.ok ? "Экспорт завершён" : "Не удалось экспортировать"}</h2>
              <p><strong>{exportResult.target}</strong></p>
              <p className={exportResult.ok ? "success-message" : "error"}>{exportResult.message}</p>
              <footer className="modal-actions"><button type="button" onClick={() => setExportResult(null)}>Закрыть</button></footer>
            </section>
          </div>
        ) : null}
        {recoveryNotice ? <p className="recovery-notice">{recoveryNotice}</p> : null}
        {stepImport && ["running", "cancelling"].includes(stepImport.state ?? "") ? (
          <div className="modal-backdrop" role="presentation">
            <section className="modal progress-modal" role="dialog" aria-modal="true" aria-live="polite" aria-labelledby="step-import-title">
              <h2 id="step-import-title">Импорт STEP-модели</h2>
              <p>{stepImport.label ?? "Подготавливаем STEP-модель…"}</p>
              <progress max="100" value={stepImport.progress ?? 0} aria-label="Прогресс импорта STEP-модели" />
              <p className="modal-hint">Не изменяйте проект до окончания импорта.</p>
              {stepImport.state === "running" ? (
                <footer className="modal-actions">
                  <button type="button" className="secondary" onClick={() => void cancelStepImport()}>Отменить импорт</button>
                </footer>
              ) : null}
            </section>
          </div>
        ) : null}
        {project ? (
          <div className="directions">
            <fieldset className="rounding">
              <legend>Округление поддона</legend>
              {(["50", "5", "none"] as const).map((value) => (
                <label key={value}>
                  <input
                    type="radio"
                    name="rounding"
                    value={value}
                    checked={rounding === value}
                    onChange={() => setRounding(value)}
                  />
                  {value === "none" ? "Без округления" : `${value} мм`}
                </label>
              ))}
            </fieldset>
            <section className="layer-stack" aria-label="Слои поддона">
              <div className="layer-stack-heading">
                <div>
                  <p className="eyebrow">Конструкция</p>
                  <h2>Слои поддона</h2>
                </div>
                <button type="button" className="secondary" onClick={addLayer}>
                  Добавить слой
                </button>
              </div>
              <div className="layer-stack-list">
              {[...project.pallet.layers].reverse().map((layer) => {
                const index = project.pallet.layers.findIndex((item) => item.id === layer.id);
                return (
                <section
                  className={`layer-card${expandedLayerId === layer.id ? " is-expanded" : ""}${draggedLayerId === layer.id ? " is-dragging" : ""}${dropLayerId === layer.id ? (dropAfterLayer ? " is-drop-after" : " is-drop-before") : ""}`}
                  key={layer.id}
                  onDragOver={(event) => {
                    event.preventDefault();
                    const bounds = event.currentTarget.getBoundingClientRect();
                    setDropLayerId(layer.id);
                    setDropAfterLayer(event.clientY > bounds.top + bounds.height / 2);
                  }}
                  onDrop={(event) => {
                    event.preventDefault();
                    const sourceId = event.dataTransfer.getData("text/plain") || draggedLayerId;
                    const bounds = event.currentTarget.getBoundingClientRect();
                    if (sourceId) moveLayer(sourceId, layer.id, event.clientY <= bounds.top + bounds.height / 2);
                    setDraggedLayerId(null);
                    setDropLayerId(null);
                  }}
                >
                  <div className="layer-card-header">
                    <span
                      className="layer-drag-handle"
                      draggable
                      role="img"
                      aria-label={`Перетащить слой ${layerNumber(layer, index)}`}
                      title="Перетащить слой"
                      onDragStart={(event) => {
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData("text/plain", layer.id);
                        setDraggedLayerId(layer.id);
                      }}
                      onDragEnd={() => {
                        setDraggedLayerId(null);
                        setDropLayerId(null);
                      }}
                    >
                      ⠿
                    </span>
                    <button
                      type="button"
                      className="layer-toggle"
                      aria-expanded={expandedLayerId === layer.id}
                      onClick={() =>
                        setExpandedLayerId((current) => current === layer.id ? null : layer.id)
                      }
                    >
                      <span>Слой {layerNumber(layer, index)}</span>
                      <small>{layer.axis === "length" ? "Вдоль длины" : "Вдоль ширины"}</small>
                    </button>
                    <button
                      type="button"
                      className="layer-visibility secondary"
                      onClick={() => toggleLayerVisibility(layer.id)}
                      aria-pressed={hiddenLayerIds.includes(layer.id)}
                    >
                      {hiddenLayerIds.includes(layer.id) ? "Показать" : "Скрыть"}
                    </button>
                    <button
                      type="button"
                      className="icon-button secondary"
                      aria-label={`Удалить слой ${layerNumber(layer, index)}`}
                      onClick={() => removeLayer(index)}
                      disabled={project.pallet.layers.length <= 1}
                    >
                      ×
                    </button>
                  </div>
                  {expandedLayerId === layer.id ? (
                    <div className="layer-card-content">
                      <label>
                        Направление брусьев
                        <select
                          value={layer.axis}
                          onChange={(event) =>
                            updateLayerAxis(index, event.target.value as "length" | "width")
                          }
                        >
                          <option value="length">Вдоль длины</option>
                          <option value="width">Вдоль ширины</option>
                        </select>
                      </label>
                      <label>
                        Стандартное сечение
                        <select
                          value={layerSectionPreset(layer)}
                          onChange={(event) => {
                            const presetId = event.target.value as SectionPresetId;
                            if (presetId === "custom") {
                              setCustomLayerSectionIds((current) => current.includes(layer.id) ? current : [...current, layer.id]);
                              return;
                            }
                            setCustomLayerSectionIds((current) => current.filter((id) => id !== layer.id));
                            const preset = SECTION_PRESETS.find((item) => item.id === presetId);
                            if (preset && "height" in preset && "width" in preset) {
                              updateLayerDirectionPatch(index, {
                                beam_height: preset.height,
                                beam_width: preset.width,
                              });
                            }
                          }}
                        >
                          {SECTION_PRESETS.map((preset) => (
                            <option key={preset.id} value={preset.id}>{preset.label}</option>
                          ))}
                        </select>
                      </label>
                      <div className="layer-section-dimensions">
                        <label>
                          Высота, мм
                          <input
                            type="number"
                            min="1"
                            value={layer.direction.beam_height}
                            disabled={layerSectionPreset(layer) !== "custom"}
                            onFocus={beginFormEdit}
                            onBlur={finishFormEdit}
                            onChange={(event) => {
                              setCustomLayerSectionIds((current) => current.includes(layer.id) ? current : [...current, layer.id]);
                              updateLayerDirection(index, "beam_height", event.target.value);
                            }}
                          />
                        </label>
                        <label>
                          Ширина, мм
                          <input
                            type="number"
                            min="1"
                            value={layer.direction.beam_width}
                            disabled={layerSectionPreset(layer) !== "custom"}
                            onFocus={beginFormEdit}
                            onBlur={finishFormEdit}
                            onChange={(event) => {
                              setCustomLayerSectionIds((current) => current.includes(layer.id) ? current : [...current, layer.id]);
                              updateLayerDirection(index, "beam_width", event.target.value);
                            }}
                          />
                        </label>
                      </div>
                      {DIRECTION_FIELDS.filter((field) => field !== "beam_height" && field !== "beam_width" && field !== "margin_start" && field !== "margin_end").map((field) => (
                        <label key={field} className={field === "support_distances" ? "layer-field-wide" : undefined}>
                          {DIRECTION_FIELD_LABELS[field]}
                          <input
                            value={
                              field === "support_distances"
                                ? distanceText[layer.id] ?? layer.direction.support_distances.join(" ")
                                : layer.direction[field]
                            }
                            onFocus={beginFormEdit}
                            onBlur={finishFormEdit}
                            onChange={(event) => updateLayerDirection(index, field, event.target.value)}
                          />
                        </label>
                      ))}
                    </div>
                  ) : null}
                </section>
                );
              })}
              </div>
            </section>
              {project ? <section className="pallet-margins">
                <h2>Отступы поддона</h2>
                {MARGIN_PAIRS.map(({ first, second, link, labels: names, description }) => {
                  const linked = marginLinks(project)[link];
                  return <div className="pallet-margins-fields" key={link}>
                    <label>{names[0]}<input type="number" min="0" value={marginDrafts[first] ?? palletMargins(project)[first]}
                      onFocus={() => { beginFormEdit(); setMarginDrafts((drafts) => ({ ...drafts, [first]: String(palletMargins(project)[first]) })); }}
                      onBlur={() => { setMarginDrafts((drafts) => { const next = { ...drafts }; delete next[first]; return next; }); finishFormEdit(); }}
                      onChange={(event) => { setMarginDrafts((drafts) => ({ ...drafts, [first]: event.target.value })); updatePalletMargin(first, event.target.value); }} /></label>
                    <button type="button" className={`margin-link secondary${linked ? " is-linked" : ""}`}
                      aria-pressed={linked} aria-label={`${linked ? "Разъединить" : "Связать"} отступы ${description}`}
                      title={linked ? "Разъединить отступы" : "Связать отступы"}
                      onClick={() => updateProject(toggleMarginLink(project, link))}>
                      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M10 13a5 5 0 0 0 7.1 0l2.1-2.1a5 5 0 0 0-7.1-7.1L11 4.9" />
                        <path d="M14 11a5 5 0 0 0-7.1 0l-2.1 2.1a5 5 0 0 0 7.1 7.1l1.1-1.1" />
                        {!linked && <path d="M4 4l16 16" />}
                      </svg>
                    </button>
                    <label>{names[1]}<input type="number" min="0" disabled={linked} value={marginDrafts[second] ?? palletMargins(project)[second]}
                      onFocus={() => { beginFormEdit(); setMarginDrafts((drafts) => ({ ...drafts, [second]: String(palletMargins(project)[second]) })); }}
                      onBlur={() => { setMarginDrafts((drafts) => { const next = { ...drafts }; delete next[second]; return next; }); finishFormEdit(); }}
                      onChange={(event) => { setMarginDrafts((drafts) => ({ ...drafts, [second]: event.target.value })); updatePalletMargin(second, event.target.value); }} /></label>
                  </div>;
                })}
              </section> : null}
              <div className="layer-stack-footer">
                <button type="button" className="secondary" onClick={() => void resetProject()}>
                  Сбросить проект
                </button>
              </div>
          </div>
        ) : null}
        </aside>
        <section className="viewport-panel" aria-label="3D просмотр">
        {calculation?.ok && calculation.snapshot?.pallet ? (
          <>
            <Suspense fallback={<p>Загрузка 3D-вида…</p>}>
              <PalletViewport
                beams={calculation.snapshot.pallet.beams}
                dimensions={calculation.snapshot.pallet.dimensions}
                preset={camera}
                presetRequest={cameraRequest}
                fitRequest={fitRequest}
                stepModel={stepModel && stepPalletBuilt && stepPlacement.current && calculation?.snapshot
                  ? { ...stepModel, transform: stepPlacement.current.transform.map((value, index) => {
                    const current = palletMargins(calculation.snapshot!.project);
                    if (index === 12) return value + (current[0] - stepPlacement.current!.starts[0]) / 1000;
                    if (index === 14) return value + (current[2] - stepPlacement.current!.starts[1]) / 1000;
                    return value;
                  }) }
                  : stepModel}
                selectedStepFace={selectedStepFace}
                onSelectStepFace={selectStepSupport}
                stepFaceSelectionEnabled={!stepPalletBuilt && !buildingStepPallet}
                showPallet={stepModel === null || stepPalletBuilt}
                hiddenLayerIds={hiddenLayerIds}
                selectedBeams={selectedBeams.map(
                  (beam) => `${beam.layerId}:${beam.layerIndex}`,
                )}
                dimensionEditing={dimensionEditing}
                hoveredDimension={hoveredDimension}
                selectedDimension={selectedDimension ? {
                  layerId: selectedDimension.layerId,
                  index: selectedDimension.index,
                } : null}
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
                manualSupports={manualSupports}
                manualSection={section}
                manualReference={manualReference ? { beam: manualReference, face: manualReferenceFace } : null}
                manualDistance={manualDistance}
                manualHud={manualHud}
                dimensionHud={dimensionHud}
                sectionHud={sectionHud}
                toolbar={viewportToolbar}
                fitViewControl={<button type="button" className="secondary" onClick={() => setFitRequest((value) => value + 1)}>Вписать</button>}
                toolHint={
                  !stepPalletBuilt && !buildingStepPallet && stepModel !== null
                    ? selectedStepFace === null
                      ? "Выберите нижнюю грань опоры\nПКМ — отменить последний выбор"
                      : "Грань опоры выбрана\nПКМ — отменить последний выбор"
                    : insertionMode
                    ? manualSupports.length === 0
                      ? "Выберите первый опорный брус\nПКМ — отменить последний выбор"
                      : manualSupports.length === 1
                        ? "Выберите второй параллельный опорный брус\nПКМ — отменить последний выбор"
                        : manualReferenceMode === "face" && !manualReference
                          ? "Выберите боковую грань для отсчёта\nПКМ — отменить последний выбор"
                          : "Укажите расстояние в панели\nПКМ — отменить последний выбор"
                    : beamTool === "delete"
                      ? "Выберите брусья для удаления\nПКМ — отменить последний выбор"
                      : beamTool === "section"
                        ? "Выберите брусья для изменения сечения\nПКМ — отменить последний выбор"
                        : dimensionEditing
                          ? "Выберите размерную линию для редактирования\nПКМ — отменить последний выбор"
                          : null
                }
                toolError={viewportToolError}
                toolErrorVersion={viewportToolErrorVersion}
                onFirstFrame={reportFirstViewportFrame}
                onUndoToolSelection={
                  (!stepPalletBuilt && !buildingStepPallet && stepModel !== null) || insertionMode || beamTool !== "none" || dimensionEditing
                    ? undoLastToolSelection
                    : undefined
                }
                beamSelectionEnabled={insertionMode || beamTool !== "none"}
              />
            </Suspense>
            <div className="pallet-summary-transition" aria-hidden={viewportExpanded} inert={viewportExpanded}>
            <div className="pallet-summary">
              <section className="pallet-summary-card" aria-label="Габариты поддона">
                <h2>Габариты поддона</h2>
                <dl className="pallet-summary-sizes">
                  <div><dt>Длина</dt><dd>{formatMillimetres(calculation.snapshot.pallet.size.length)} <span>мм</span></dd></div>
                  <div><dt>Ширина</dt><dd>{formatMillimetres(calculation.snapshot.pallet.size.width)} <span>мм</span></dd></div>
                  <div><dt>Высота</dt><dd>{formatMillimetres(calculation.snapshot.pallet.size.height)} <span>мм</span></dd></div>
                </dl>
              </section>
              <section className="pallet-summary-card" aria-label="Детали поддона">
                <h2>Детали</h2>
                <div className="pallet-details-scroll" tabIndex={0} aria-label="Список деталей поддона">
                  {palletDetails(calculation.snapshot.pallet.beams).map((detail) => (
                    <div className="pallet-detail" key={`${detail.height}-${detail.width}-${detail.length}`}>
                      <strong>{formatMillimetres(detail.height)} × {formatMillimetres(detail.width)} × {formatMillimetres(detail.length)} мм</strong>
                      <span>{detail.count} шт.</span>
                    </div>
                  ))}
                </div>
              </section>
            </div>
            </div>
          </>
        ) : null}
        </section>
      </div>
    </main>
  );
}
