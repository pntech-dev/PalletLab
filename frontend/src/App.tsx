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
import { prepareStepModel, type StepModelPayload } from "./stepModelGeometry";

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
  view: {
    camera: CameraPreset;
    show_length_dimensions: boolean;
    show_width_dimensions: boolean;
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
type SolidWorksTemplateResponse = CommandResponse & { path?: string };
type SolidWorksMaterialsResponse = CommandResponse & { materialLibrary?: string; materials?: string[] };
type SolidWorksOptions = {
  partTemplate: string;
  assemblyTemplate: string;
  materialLibrary: string;
  materialName: string;
};
type SolidWorksSettingsResponse = CommandResponse & { options?: SolidWorksOptions | null };
type ExportResult = {
  target: "КОМПАС-3D" | "SolidWorks";
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
        export_kompas: (project: Project) => Promise<CommandResponse>;
        select_solidworks_template: (kind: "part" | "assembly") => Promise<SolidWorksTemplateResponse>;
        select_solidworks_material_library: () => Promise<SolidWorksMaterialsResponse>;
        solidworks_export_settings: () => Promise<SolidWorksSettingsResponse>;
        save_solidworks_export_settings: (options: SolidWorksOptions) => Promise<CommandResponse>;
        export_solidworks: (project: Project, options: SolidWorksOptions) => Promise<CommandResponse>;
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
  const [materials, setMaterials] = useState<Material[]>([]);
  const [distanceText, setDistanceText] = useState<
    Record<"length" | "width", string>
  >({ length: "", width: "" });
  const [camera, setCamera] = useState<CameraPreset>("isometric");
  const [cameraRequest, setCameraRequest] = useState(0);
  const [fitRequest, setFitRequest] = useState(0);
  const [stepImport, setStepImport] = useState<StepImportOperation | null>(null);
  const [stepModel, setStepModel] = useState<StepModelSnapshot | null>(null);
  const [selectedStepFace, setSelectedStepFace] = useState<number | null>(null);
  const [stepPalletBuilt, setStepPalletBuilt] = useState(false);
  const [solidWorksOptions, setSolidWorksOptions] = useState<SolidWorksOptions | null>(storedSolidWorksOptions);
  const [solidWorksMaterials, setSolidWorksMaterials] = useState<string[]>([]);
  const [exporting, setExporting] = useState<"kompas" | "solidworks" | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [solidWorksSetupOpen, setSolidWorksSetupOpen] = useState(false);
  const [solidWorksDraft, setSolidWorksDraft] = useState<SolidWorksOptions | null>(null);
  const [solidWorksSetupError, setSolidWorksSetupError] = useState<string | null>(null);
  const [buildingStepPallet, setBuildingStepPallet] = useState(false);
  const [selectedBeams, setSelectedBeams] = useState<ViewportBeam[]>([]);
  const [beamTool, setBeamTool] = useState<"none" | "delete" | "section">("none");
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
  const [viewportToolError, setViewportToolError] = useState<string | null>(null);
  const [viewportToolErrorVersion, setViewportToolErrorVersion] = useState(0);
  const [, setHistoryVersion] = useState(0);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const undoStack = useRef<Project[]>([]);
  const redoStack = useRef<Project[]>([]);
  const formEditStart = useRef<Project | null>(null);
  const viewportToolErrorTimeout = useRef<number | null>(null);

  function showViewportToolError(message: string) {
    if (viewportToolErrorTimeout.current !== null) {
      window.clearTimeout(viewportToolErrorTimeout.current);
    }
    setCalculationError(null);
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

  function applyProject(nextProject: Project) {
    setProject(nextProject);
    setCamera(nextProject.view.camera);
    setDistanceText({
      length: nextProject.pallet.length.support_distances.join(" "),
      width: nextProject.pallet.width.support_distances.join(" "),
    });
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
      const api = window.pywebview?.api;
      if (!api) return;
      try {
        const [nextStatus, defaultProject, nextMaterials, savedSolidWorksSettings] = await Promise.all([
          api.status(),
          api.default_project(),
          api.materials(),
          api.solidworks_export_settings(),
        ]);
        const recovered = recoveredProject();
        if (recovered) {
          const recovery = await api.calculate(recovered);
          if (recovery.ok && recovery.snapshot) {
            applyProject(recovery.snapshot.project);
            applyCalculation(recovery);
            setRecoveryNotice("Recovered the last autosaved project.");
          } else {
            discardRecoveredProject();
            applyProject(defaultProject as Project);
          }
        } else {
          applyProject(defaultProject as Project);
        }
        setStatus(nextStatus);
        setMaterials(nextMaterials);
        if (savedSolidWorksSettings.ok && savedSolidWorksSettings.options) {
          setSolidWorksOptions(savedSolidWorksSettings.options);
        }
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
    const timeout = window.setTimeout(() => {
      void calculateProject();
    }, 300);
    return () => window.clearTimeout(timeout);
  }, [project, status]);

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

  async function saveProject() {
    if (!project) return;
    const response = await window.pywebview!.api!.save_project(project);
    if (response.ok) {
      discardRecoveredProject();
      setRecoveryNotice(null);
    } else if (!response.cancelled)
      setCalculationError(response.error ?? "Не удалось сохранить проект.");
  }
  async function openProject() {
    const response = await window.pywebview!.api!.open_project();
    if (response.project) {
      applyProject(response.project);
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
      void exportSolidWorks(solidWorksDraft);
    })();
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
    async function loadPreparedModel() {
      const api = window.pywebview?.api;
      if (!api || !stepImport?.operationId || stepImport.state !== "completed") return;
      try {
        const response = await api.step_model_snapshot(stepImport.operationId);
        if (response.ok && response.assetUrl) {
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
      if (manualSupports.length === 1 && manualSupports[0].beam.layerId !== beam.layerId) {
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
      setBeamTool("none");
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
      setBeamTool("none");
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
        ? { ...layer, axis, direction: project.pallet[axis] }
        : layer,
    );
    updateProject({ ...project, pallet: { ...project.pallet, layers } });
  }

  function addLayer() {
    if (!project) return;
    const layerId = `layer-${project.pallet.layers.length}`;
    updateProject({
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
    updateProject({
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
  const manualHud: ReactNode = insertionMode && manualSupports.length === 2 ? (
    <div className="manual-hud">
      <strong>Configure the new beam.</strong>
      <label>
        Placement
        <select
          value={manualReferenceMode}
          onChange={(event) => {
            const mode = event.target.value as "base" | "face";
            setManualReferenceMode(mode);
            setManualReference(null);
            setManualDistance(mode === "base" ? basePointDistance(manualSupports[0]) : 0);
          }}
        >
          <option value="base">From zero</option>
          <option value="face">From selected face</option>
        </select>
      </label>
      {manualReferenceMode === "face" ? (
        manualReference ? (
          <span>Reference: {manualReference.layerId} · beam {manualReference.layerIndex + 1}</span>
        ) : (
          <span>Click the required side face in the 3D view.</span>
        )
      ) : null}
      <label>
        Distance
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
      <button type="button" onClick={addManualBeam} disabled={manualReferenceMode === "face" && !manualReference}>Add beam</button>
      <button type="button" onClick={stopInsertion}>Cancel</button>
    </div>
  ) : null;
  const dimensionHud: ReactNode = dimensionEditing && selectedDimension ? (
    <div className="manual-hud">
      <strong>New distance</strong>
      <label>
        Value
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
      <button type="button" onClick={changeSelectedDistance}>Apply distance</button>
      <button type="button" onClick={stopDimensionEditing}>Cancel</button>
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
          <button type="button" onClick={() => void resetProject()} disabled={!project}>
            Reset example
          </button>
          <button type="button" onClick={undo} disabled={!project || undoStack.current.length === 0}>
            Undo
          </button>
          <button type="button" onClick={redo} disabled={!project || redoStack.current.length === 0}>
            Redo
          </button>
          <button
            type="button"
            onClick={() => void importStepModel()}
            disabled={!status || stepImport?.state === "running" || stepImport?.state === "cancelling"}
          >
            Import STEP model
          </button>
        </div>
        {project ? (
          <fieldset className="cad-export">
            <legend>CAD export</legend>
            <div className="cad-export-actions">
              <button type="button" onClick={() => void exportKompas()} disabled={exporting !== null}>
                {exporting === "kompas" ? "Exporting KOMPAS-3D…" : "Export KOMPAS-3D"}
              </button>
              <button type="button" onClick={beginSolidWorksExport} disabled={exporting !== null}>
                {exporting === "solidworks" ? "Exporting SolidWorks…" : "Export SolidWorks"}
              </button>
              <button type="button" className="secondary" onClick={openSolidWorksSetup} disabled={exporting !== null}>
                SolidWorks settings
              </button>
            </div>
            <p className="cad-export-note">SolidWorks settings are requested only before the first export.</p>
          </fieldset>
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
        {exporting ? (
          <div className="modal-backdrop" role="presentation">
            <section className="modal progress-modal" role="dialog" aria-modal="true" aria-live="polite">
              <h2>Экспорт выполняется</h2>
              <p>{exporting === "solidworks" ? "SolidWorks создаёт детали и сборку…" : "КОМПАС-3D создаёт детали и сборку…"}</p>
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
        {stepImport ? (
          <div className={stepImport.state === "failed" ? "step-import error" : "step-import"}>
            <strong>STEP import</strong>
            <span>{stepImport.label ?? stepImport.error ?? "Preparing STEP model…"}</span>
            {stepImport.state === "running" || stepImport.state === "cancelling" ? (
              <progress max="100" value={stepImport.progress ?? 0} />
            ) : null}
            {stepImport.state === "running" ? (
              <button type="button" onClick={() => void cancelStepImport()}>Cancel import</button>
            ) : null}
            {stepImport.state === "completed" ? (
              <>
                <span>
                  {stepPalletBuilt
                    ? "The pallet was built from the selected support plane."
                    : stepModel
                      ? "Choose a planar support face in the 3D view."
                      : "Preparing the model for 3D view…"}
                </span>
                {buildingStepPallet ? <span>Building pallet from the selected support…</span> : null}
              </>
            ) : null}
          </div>
        ) : null}
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
                    updateProject({
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
                    updateProject({
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
                      onFocus={beginFormEdit}
                      onBlur={finishFormEdit}
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
                    onClick={() => {
                      if (!project) return;
                      setCamera(preset);
                      setCameraRequest((value) => value + 1);
                      updateProject({
                        ...project,
                        view: { ...project.view, camera: preset },
                      });
                    }}
                  >
                    {preset}
                  </button>
                ),
              )}
              <button type="button" onClick={() => setFitRequest((value) => value + 1)}>
                Fit view
              </button>
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
                onClick={() =>
                  beamTool === "section"
                    ? void changeSelectedBeamSections()
                    : activateBeamTool("section")
                }
              >
                {beamTool === "section" ? `Apply section (${selectedBeams.length})` : "Change section"}
              </button>
              <button
                type="button"
                onClick={() =>
                  beamTool === "delete"
                    ? void deleteSelectedBeams()
                    : activateBeamTool("delete")
                }
              >
                {beamTool === "delete" ? `Delete selected (${selectedBeams.length})` : "Delete beams"}
              </button>
              <button
                type="button"
                className={dimensionEditing ? "active-tool" : ""}
                onClick={() =>
                  dimensionEditing
                    ? stopDimensionEditing()
                    : activateDimensionEditing()
                }
              >
                {dimensionEditing ? "Finish dimension edit" : "Edit dimensions"}
              </button>
              <button
                type="button"
                className={insertionMode ? "active-tool" : ""}
                onClick={() =>
                  insertionMode ? stopInsertion() : activateInsertion()
                }
              >
                {insertionMode ? "Finish insertion" : "Add beam"}
              </button>
            </div>
            <Suspense fallback={<p>Loading 3D view…</p>}>
              <PalletViewport
                beams={calculation.snapshot.pallet.beams}
                dimensions={calculation.snapshot.pallet.dimensions}
                preset={camera}
                presetRequest={cameraRequest}
                fitRequest={fitRequest}
                stepModel={stepModel}
                selectedStepFace={selectedStepFace}
                onSelectStepFace={selectStepSupport}
                stepFaceSelectionEnabled={!stepPalletBuilt && !buildingStepPallet}
                showPallet={stepModel === null || stepPalletBuilt}
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
                toolHint={
                  !stepPalletBuilt && !buildingStepPallet && stepModel !== null
                    ? selectedStepFace === null
                      ? "Select the lower support face\nПКМ — отменить последний выбор"
                      : "Support face selected\nПКМ — отменить последний выбор"
                    : insertionMode
                    ? manualSupports.length === 0
                      ? "Select the first support beam\nПКМ — отменить последний выбор"
                      : manualSupports.length === 1
                        ? "Select the second parallel support beam\nПКМ — отменить последний выбор"
                        : manualReferenceMode === "face" && !manualReference
                          ? "Select the reference side face\nПКМ — отменить последний выбор"
                          : "Enter the distance in the panel\nПКМ — отменить последний выбор"
                    : beamTool === "delete"
                      ? "Select beams to delete\nПКМ — отменить последний выбор"
                      : beamTool === "section"
                        ? "Select beams to change their section\nПКМ — отменить последний выбор"
                        : dimensionEditing
                          ? "Select a dimension line to edit\nПКМ — отменить последний выбор"
                          : null
                }
                toolError={viewportToolError}
                toolErrorVersion={viewportToolErrorVersion}
                onUndoToolSelection={
                  (!stepPalletBuilt && !buildingStepPallet && stepModel !== null) || insertionMode || beamTool !== "none" || dimensionEditing
                    ? undoLastToolSelection
                    : undefined
                }
                beamSelectionEnabled={insertionMode || beamTool !== "none"}
              />
            </Suspense>
          </>
        ) : null}
        {calculationError ? <p className="error">{calculationError}</p> : null}
      </section>
    </main>
  );
}
