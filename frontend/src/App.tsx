import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
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
import { changeIndependentPalletMargin, MARGIN_PAIRS, palletMargins, type MarginIndex } from "./palletMargins";
import { remainingImportFeedback, stepImportPhase } from "./stepImportUi";
import { nextToolbarManualExpanded } from "./viewportToolbarState";
import { betweenFaces, type BeamReference, type BeamReferenceFace } from "./manualBeamBetween";
import { manualSectionForSupport } from "./manualBeamSection";
import { SettingsDialog } from "./SettingsDialog";
import { Button } from "./design/Button";
import { Checkbox } from "./design/Checkbox";
import { Combobox } from "./design/Combobox";
import { SegmentedControl } from "./design/SegmentedControl";
import { ExpandableLabel, TOOLBAR_COLLAPSE_DURATION_MS, TOOLBAR_COLLAPSE_SPRING, TOOLBAR_EXPAND_DURATION_MS, TOOLBAR_EXPAND_SPRING } from "./design/ExpandableLabel";
import { Tooltip, TooltipProvider } from "./design/Tooltip";
import { Hud, HudHint } from "./design/Hud";
import { detailCount, PalletSummary } from "./design/PalletSummary";
import { Scrollbar } from "./design/Scrollbar";
import { ResetDialog } from "./design/ResetDialog";
import { ProgressIndicator } from "./design/ProgressIndicator";
import { MessageBox } from "./design/MessageBox";
import { FolderOpen, Save, SavePen, FolderInput, FolderOutput, Settings, Undo, Redo, Plus, Trash2, SquareDimensions, RulerDimensionLine, Maximize2, Minimize2, LockKeyhole, LockKeyholeOpen, Copy, Eye, EyeOff, GripVertical, ChevronDown, ChevronRight, Info, X, ScanSquare, LayersPlus } from "lucide-react";
import logo from "./assets/logo.svg";
import { DEFAULT_SETTINGS, projectWithDefaults, applyDefaultsIfUnmodified, type AppSettings } from "./appSettings";

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
  layerId?: string;
  snapshot?: {
    project: Project;
    pallet: {
      size: { length: number; width: number; height: number };
      massKg: number;
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
type Layer = { id: string; axis: "length" | "width"; direction: Direction; align_top?: boolean };
type ManualBeam = { id: string; first: [string, number]; second: [string, number]; first_face?: "top" | "bottom";
  reference?: [string, number] | null; second_reference?: [string, number] | null;
  physical_layer_id?: string; start_point?: number[] | null; [key: string]: unknown };

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
const formatKilograms = (value: number) => new Intl.NumberFormat("ru-RU", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
}).format(value);

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
  step_model?: {
    source: string;
    transform: number[];
    starts: [number, number];
    placement_matrix?: number[][];
  };
  pallet: {
    length: Direction;
    width: Direction;
    layers: Layer[];
    upper_layer: "length" | "width";
    rounding_step?: 0 | 5 | 50;
    material_id: string;
    pallet_margins?: [number, number] | [number, number, number, number];
    pallet_margin_links?: [boolean, boolean];
    manual_beams?: ManualBeam[];
    layer_sections?: { layer_id: string; index: number; height: number; width: number }[];
  };
  view: {
    camera: CameraPreset;
    show_length_dimensions: boolean;
    show_width_dimensions: boolean;
    show_grid?: boolean;
    hidden_layer_ids: string[];
    locked_layer_ids: string[];
  };
};
type ProjectHistory = { undo: Project[]; redo: Project[] };
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
  phase?: "faces" | "indeterminate";
  phaseProgress?: number | null;
  label?: string;
  error?: string;
  path?: string;
};
type StepModelResponse = { ok: boolean; error?: string; assetUrl?: string };
type StepPalletResponse = CalculationResponse & {
  modelTransform?: number[];
  placementMatrix?: number[][];
  supportCount?: number;
  referenceFace?: number;
};
type CommandResponse = { ok: boolean; cancelled?: boolean; error?: string; output?: string };
export type UpdateStatus = {
  state: "idle" | "unavailable" | "checking" | "current" | "check_failed" | "available" | "downloading" | "ready" | "installing" | "failed";
  version?: string;
  lastCheckedAt?: string | null;
  manualOnly?: boolean;
  received?: number;
  total?: number;
  error?: string;
};
type SolidWorksTemplateResponse = CommandResponse & { path?: string };
type SolidWorksMaterialsResponse = CommandResponse & { materialLibrary?: string; materials?: string[] };
export type SolidWorksOptions = {
  partTemplate: string;
  assemblyTemplate: string;
  drawingTemplate: string;
  materialLibrary: string;
  materialName: string;
};
type SolidWorksSettingsResponse = CommandResponse & { options?: SolidWorksOptions | null };
type DrawingCad = "solidworks" | "kompas";
type DrawingScope = "assembly" | "parts" | "parts_and_assembly";
type ExportResult = {
  target: "КОМПАС-3D" | "SolidWorks" | "Чертежи SolidWorks" | "Чертежи КОМПАС-3D";
  ok: boolean;
  message: string;
};

const SOLIDWORKS_OPTIONS_KEY = "palletlab.web.solidworks-options.v1";
const HISTORY_LIMIT = 50;

function copyProject(project: Project): Project {
  return JSON.parse(JSON.stringify(project)) as Project;
}

function projectsMatch(first: Project, second: Project): boolean {
  return JSON.stringify(first) === JSON.stringify(second);
}

function storedSolidWorksOptions(): SolidWorksOptions | null {
  try {
    const raw = window.localStorage.getItem(SOLIDWORKS_OPTIONS_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<SolidWorksOptions>;
    return typeof value.partTemplate === "string"
      && typeof value.assemblyTemplate === "string"
      && typeof value.drawingTemplate === "string"
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
        copy_text: (value: string) => Promise<CommandResponse>;
        open_contact: (kind: "repository" | "email", value: string) => Promise<CommandResponse>;
        default_project: () => Promise<object>;
        application_settings: () => Promise<AppSettings>;
        recovery_project: () => Promise<Project | null>;
        save_recovery_project: (project: Project) => Promise<{ ok: boolean }>;
        clear_recovery_project: () => Promise<{ ok: boolean }>;
        save_application_settings: (settings: AppSettings) => Promise<{ ok: boolean }>;
        save_program_settings: (settings: AppSettings, solidworks: SolidWorksOptions | null) => Promise<CommandResponse>;
        solidworks_materials: (library: string) => Promise<SolidWorksMaterialsResponse>;
        discover_cad_templates: (current: SolidWorksOptions) => Promise<{ ok: boolean; partTemplate: string | null; assemblyTemplate: string | null; drawingTemplate: string | null; materialLibrary: string | null; materials: string[]; sources: Record<string, string>; configuredPaths: Record<string, string>; error?: string }>;
        calculate: (project: object) => Promise<CalculationResponse>;
        duplicate_layer: (project: object, layerId: string) => Promise<CalculationResponse>;
        materials: () => Promise<Material[]>;
        check_update: (manual?: boolean) => Promise<UpdateStatus>;
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
          history: ProjectHistory,
        ) => Promise<{ ok: boolean; cancelled?: boolean; error?: string }>;
        open_project: () => Promise<{
          ok: boolean;
          cancelled?: boolean;
          error?: string;
          project?: Project;
          history?: ProjectHistory | null;
          history_warning?: boolean;
        }>;
        choose_export_directory: () => Promise<CommandResponse & { path?: string }>;
        export_kompas: (
          project: Project,
          includeAssembly?: boolean,
          parentDirectory?: string,
          includeExportModel?: boolean,
        ) => Promise<CommandResponse>;
        select_solidworks_template: (kind: "part" | "assembly" | "drawing") => Promise<SolidWorksTemplateResponse>;
        select_solidworks_material_library: () => Promise<SolidWorksMaterialsResponse>;
        solidworks_export_settings: () => Promise<SolidWorksSettingsResponse>;
        save_solidworks_export_settings: (options: SolidWorksOptions) => Promise<CommandResponse>;
        export_solidworks: (
          project: Project,
          options: SolidWorksOptions,
          includeAssembly?: boolean,
          parentDirectory?: string,
          includeExportModel?: boolean,
        ) => Promise<CommandResponse>;
        create_drawings: (
          project: Project,
          cad: DrawingCad,
          scope: DrawingScope,
          template: string | null,
          modelDirectory?: string,
          includeExportModel?: boolean,
        ) => Promise<CommandResponse>;
        import_step_model: () => Promise<StepImportOperation>;
        restore_step_model: (path: string) => Promise<StepImportOperation>;
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsInitialSection, setSettingsInitialSection] = useState<"general" | "cad">("general");
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const projectBaseline = useRef<string | null>(null);
  const closeSettings = useCallback(() => setSettingsOpen(false), []);
  const [calculation, setCalculation] = useState<CalculationResponse | null>(
    null,
  );
  const [calculationError, setCalculationError] = useState<string | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const currentProject = useRef(project);
  currentProject.current = project;
  const duplicatingLayer = useRef(false);
  const [duplicateBusy, setDuplicateBusy] = useState(false);
  const [savedProject, setSavedProject] = useState<string | null>(null);
  const [savedHistory, setSavedHistory] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [update, setUpdate] = useState<UpdateStatus>({ state: "idle" });
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [lastUpdateCheck, setLastUpdateCheck] = useState<string | null>(null);
  const [distanceText, setDistanceText] = useState<Record<string, string>>({});
  const [marginDrafts, setMarginDrafts] = useState<Partial<Record<MarginIndex, string>>>({});
  const [selectedLayerId, setSelectedLayerId] = useState<string | null>(null);
  const [expandedLayerId, setExpandedLayerId] = useState<string | null>(null);
  const [draggedLayer, setDraggedLayer] = useState<{
    id: string;
    startIndex: number;
    targetIndex: number;
    left: number;
    top: number;
    width: number;
    height: number;
  } | null>(null);
  const layerCardRefs = useRef(new Map<string, HTMLElement>());
  const layerPlaceholderRef = useRef<HTMLDivElement>(null);
  const floatingLayerRef = useRef<HTMLElement>(null);
  const directionsRef = useRef<HTMLDivElement>(null);
  const pendingSiblingTops = useRef<Map<string, number> | null>(null);
  const pendingDropRect = useRef<{ id: string; rect: DOMRect } | null>(null);
  const layerFlipAnimations = useRef(new Map<string, Animation>());
  const [hiddenLayerIds, setHiddenLayerIds] = useState<string[]>([]);
  const [camera, setCamera] = useState<CameraPreset>("isometric");
  const [cameraMenuOpen, setCameraMenuOpen] = useState(false);
  const [viewportExpanded, setViewportExpanded] = useState(false);
  const [toolbarManualExpanded, setToolbarManualExpanded] = useState<boolean | null>(null);
  const toolbarExpanded = toolbarManualExpanded ?? viewportExpanded;
  const toolbarChevronRef = useRef<SVGSVGElement | null>(null);
  const toolbarChevronAnimation = useRef<Animation | null>(null);
  const prevToolbarExpandedRef = useRef<boolean | null>(null);
  useLayoutEffect(() => {
    const chevron = toolbarChevronRef.current;
    if (!chevron) return;
    if (prevToolbarExpandedRef.current === null) {
      prevToolbarExpandedRef.current = toolbarExpanded;
      chevron.style.transform = `rotate(${toolbarExpanded ? 180 : 0}deg)`;
      return;
    }
    if (prevToolbarExpandedRef.current === toolbarExpanded) return;
    prevToolbarExpandedRef.current = toolbarExpanded;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      toolbarChevronAnimation.current?.cancel();
      toolbarChevronAnimation.current = null;
      chevron.style.transform = `rotate(${toolbarExpanded ? 180 : 0}deg)`;
      return;
    }
    const matrix = new DOMMatrixReadOnly(window.getComputedStyle(chevron).transform);
    let fromDeg = Math.atan2(matrix.b, matrix.a) * 180 / Math.PI;
    if (fromDeg < -90) fromDeg += 360;
    toolbarChevronAnimation.current?.cancel();
    const toDeg = toolbarExpanded ? 180 : 0;
    const spring = toolbarExpanded ? TOOLBAR_EXPAND_SPRING : TOOLBAR_COLLAPSE_SPRING;
    const duration = toolbarExpanded ? TOOLBAR_EXPAND_DURATION_MS : TOOLBAR_COLLAPSE_DURATION_MS;
    const anim = chevron.animate(
      spring.map((p) => ({ transform: `rotate(${(fromDeg + (toDeg - fromDeg) * p).toFixed(2)}deg)` })),
      { duration, easing: "linear", fill: "forwards" },
    );
    toolbarChevronAnimation.current = anim;
    anim.onfinish = () => {
      if (toolbarChevronAnimation.current !== anim) return;
      toolbarChevronAnimation.current = null;
      anim.cancel();
      chevron.style.transform = `rotate(${toDeg}deg)`;
    };
  }, [toolbarExpanded]);
  const [viewportTransition, setViewportTransition] = useState<"none" | "expanding" | "collapsing">("none");
  const [summaryHeight, setSummaryHeight] = useState(0);
  const [editorWidth, setEditorWidth] = useState(512);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const editorPanelRef = useRef<HTMLElement>(null);
  const summaryTransitionRef = useRef<HTMLDivElement>(null);
  const activeViewportAnimations = useRef<Animation[]>([]);
  const pendingViewportFlip = useRef<{
    expanding: boolean;
    wasTransitioning: boolean;
    fromRightInset: number;
    fromBottomInset: number;
    editorOpacity: number;
    summaryOpacity: number;
    editorDeltaX: number | null;
    summaryDeltaY: number | null;
  } | null>(null);
  const hasPalletSummary = Boolean(calculation?.ok && calculation.snapshot?.pallet);
  const collapsedRightInset = editorWidth + 8;
  const collapsedBottomInset = hasPalletSummary && summaryHeight > 0 ? summaryHeight : 0;
  const visibleRightInset = viewportExpanded ? 0 : collapsedRightInset;
  const visibleBottomInset = viewportExpanded ? 0 : collapsedBottomInset;

  useLayoutEffect(() => {
    const editor = editorPanelRef.current;
    if (editor) {
      const measureEditor = () => {
        const width = editor.offsetWidth;
        if (width > 0) setEditorWidth((current) => (current === width ? current : width));
      };
      measureEditor();
      if (typeof ResizeObserver !== "undefined") {
        const observer = new ResizeObserver(measureEditor);
        observer.observe(editor);
        return () => observer.disconnect();
      }
    }
    return undefined;
  }, []);

  useLayoutEffect(() => {
    const summary = summaryTransitionRef.current;
    if (!summary || !hasPalletSummary) {
      setSummaryHeight(0);
      return undefined;
    }
    const measureSummary = () => {
      const height = summary.offsetHeight;
      if (height > 0) setSummaryHeight((current) => (current === height ? current : height));
    };
    measureSummary();
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(measureSummary);
      observer.observe(summary);
      return () => observer.disconnect();
    }
    return undefined;
  }, [hasPalletSummary]);

  const clearInlineViewportStyles = useCallback(() => {
    const workspace = workspaceRef.current;
    const viewport = workspace?.querySelector<HTMLElement>(".viewport");
    if (viewport) viewport.style.clipPath = "";
    const fitControl = workspace?.querySelector<HTMLElement>(".viewport-fit-control");
    if (fitControl) fitControl.style.transform = "";
    const navGuide = workspace?.querySelector<HTMLElement>(".viewport-navigation-guide");
    if (navGuide) navGuide.style.transform = "";
    const toolbarEnd = workspace?.querySelector<HTMLElement>(".viewport-toolbar-end");
    if (toolbarEnd) toolbarEnd.style.transform = "";
    const editor = editorPanelRef.current;
    if (editor) {
      editor.style.transform = "";
      editor.style.opacity = "";
    }
    const summary = summaryTransitionRef.current;
    if (summary) {
      summary.style.transform = "";
      summary.style.opacity = "";
    }
  }, []);
  const cancelViewportMotion = useCallback(() => {
    for (const animation of activeViewportAnimations.current) animation.cancel();
    activeViewportAnimations.current = [];
  }, []);
  useEffect(() => {
    if (viewportTransition === "none") return;
    const fallback = window.setTimeout(() => setViewportTransition("none"), 1000);
    return () => window.clearTimeout(fallback);
  }, [viewportTransition]);
  useLayoutEffect(() => {
    if (viewportTransition !== "none") return;
    cancelViewportMotion();
    clearInlineViewportStyles();
  }, [viewportTransition, cancelViewportMotion, clearInlineViewportStyles]);
  useLayoutEffect(() => {
    const flip = pendingViewportFlip.current;
    if (!flip) return;
    pendingViewportFlip.current = null;
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setViewportTransition("none");
      return;
    }
    const workspace = workspaceRef.current;
    const viewport = workspace?.querySelector<HTMLElement>(".viewport") ?? null;
    const fitControl = workspace?.querySelector<HTMLElement>(".viewport-fit-control") ?? null;
    const navGuide = workspace?.querySelector<HTMLElement>(".viewport-navigation-guide") ?? null;
    const toolbarEnd = workspace?.querySelector<HTMLElement>(".viewport-toolbar-end") ?? null;
    const editor = editorPanelRef.current;
    const summary = summaryTransitionRef.current;
    if (typeof viewport?.animate !== "function") {
      setViewportTransition("none");
      return;
    }
    const expandEasing = "cubic-bezier(0.16, 1, 0.3, 1)";
    const collapseEasing = "linear(0.000, 0.056 5%, 0.191 10%, 0.360 15%, 0.534 20%, 0.692 25%, 0.824 30%, 0.926 35%, 0.998 40%, 1.043 45%, 1.067 50%, 1.075 55%, 1.073 60%, 1.063 65%, 1.051 70%, 1.038 75%, 1.025 80%, 1.015 85%, 1.007 90%, 1.001 95%, 1.000)";
    const duration = flip.expanding ? 340 : 420;
    const easing = flip.expanding ? expandEasing : collapseEasing;
    const toRight = flip.expanding ? 0 : collapsedRightInset;
    const toBottom = flip.expanding ? 0 : collapsedBottomInset;

    const animations: Animation[] = [];
    animations.push(viewport.animate(
      [
        { clipPath: `inset(0px ${flip.fromRightInset}px ${flip.fromBottomInset}px 0px round 16px)` },
        { clipPath: `inset(0px ${toRight}px ${toBottom}px 0px round 16px)` },
      ],
      { duration, easing, fill: "both" },
    ));
    if (fitControl) {
      animations.push(fitControl.animate(
        [
          { transform: `translate3d(${-flip.fromRightInset}px, ${-flip.fromBottomInset}px, 0)` },
          { transform: `translate3d(${-toRight}px, ${-toBottom}px, 0)` },
        ],
        { duration, easing, fill: "both" },
      ));
    }
    if (navGuide) {
      animations.push(navGuide.animate(
        [
          { transform: `translate3d(0, ${-flip.fromBottomInset}px, 0)` },
          { transform: `translate3d(0, ${-toBottom}px, 0)` },
        ],
        { duration, easing, fill: "both" },
      ));
    }
    if (toolbarEnd) {
      animations.push(toolbarEnd.animate(
        [
          { transform: `translate3d(${toRight - flip.fromRightInset}px, 0, 0)` },
          { transform: "translate3d(0, 0, 0)" },
        ],
        { duration, easing },
      ));
    }
    if (editor) {
      const editorTravel = editorWidth + 24;
      if (flip.expanding) {
        const startX = flip.editorDeltaX ?? 0;
        animations.push(editor.animate(
          [
            { opacity: flip.editorOpacity, transform: `translate3d(${startX}px, 0, 0) scale(1)` },
            { opacity: 0.92, transform: `translate3d(${editorTravel * 0.45}px, 0, 0) scale(0.985)`, offset: 0.45 },
            { opacity: 0, transform: `translate3d(${editorTravel}px, 0, 0) scale(0.97)` },
          ],
          { duration, easing, fill: "both" },
        ));
      } else {
        const startX = flip.wasTransitioning && flip.editorDeltaX !== null ? flip.editorDeltaX : editorTravel;
        const startOpacity = flip.wasTransitioning ? flip.editorOpacity : 0;
        animations.push(editor.animate(
          [
            { opacity: startOpacity, transform: `translate3d(${startX}px, 0, 0) scale(0.97)` },
            { opacity: 1, offset: 0.35 },
            { opacity: 1, transform: "translate3d(0, 0, 0) scale(1)" },
          ],
          { duration, easing },
        ));
      }
    }
    if (summary && collapsedBottomInset > 0) {
      const summaryTravel = collapsedBottomInset + 24;
      if (flip.expanding) {
        const startY = flip.summaryDeltaY ?? 0;
        animations.push(summary.animate(
          [
            { opacity: flip.summaryOpacity, transform: `translate3d(0, ${startY}px, 0) scale(1)` },
            { opacity: 0.92, transform: `translate3d(0, ${summaryTravel * 0.45}px, 0) scale(0.985)`, offset: 0.45 },
            { opacity: 0, transform: `translate3d(0, ${summaryTravel}px, 0) scale(0.97)` },
          ],
          { duration, easing, fill: "both" },
        ));
      } else {
        const startY = flip.wasTransitioning && flip.summaryDeltaY !== null ? flip.summaryDeltaY : summaryTravel;
        const startOpacity = flip.wasTransitioning ? flip.summaryOpacity : 0;
        animations.push(summary.animate(
          [
            { opacity: startOpacity, transform: `translate3d(0, ${startY}px, 0) scale(0.97)` },
            { opacity: 1, offset: 0.35 },
            { opacity: 1, transform: "translate3d(0, 0, 0) scale(1)" },
          ],
          { duration, easing },
        ));
      }
    }
    activeViewportAnimations.current = animations;
    void Promise.allSettled(animations.map((animation) => animation.finished)).then(() => {
      if (activeViewportAnimations.current === animations) setViewportTransition("none");
    });
  }, [viewportExpanded, collapsedRightInset, collapsedBottomInset, editorWidth]);
  function toggleViewportExpanded() {
    const next = !viewportExpanded;
    const workspace = workspaceRef.current;
    const viewport = workspace?.querySelector<HTMLElement>(".viewport") ?? null;
    const fitControl = workspace?.querySelector<HTMLElement>(".viewport-fit-control") ?? null;
    const editor = editorPanelRef.current;
    const summary = summaryTransitionRef.current;
    let fromRightInset = viewportExpanded ? 0 : collapsedRightInset;
    let fromBottomInset = viewportExpanded ? 0 : collapsedBottomInset;
    if (fitControl && viewport) {
      const fitRect = fitControl.getBoundingClientRect();
      const vpRect = viewport.getBoundingClientRect();
      if (vpRect.width > 0 && vpRect.height > 0) {
        fromRightInset = Math.max(0, (vpRect.right - 16) - fitRect.right);
        fromBottomInset = Math.max(0, (vpRect.bottom - 16) - fitRect.bottom);
      }
    }
    let editorDeltaX: number | null = null;
    if (editor && workspace) {
      const editorRect = editor.getBoundingClientRect();
      const wsRect = workspace.getBoundingClientRect();
      editorDeltaX = editorRect.right - (wsRect.right - 8);
    }
    let summaryDeltaY: number | null = null;
    if (summary && workspace) {
      const summaryRect = summary.getBoundingClientRect();
      const wsRect = workspace.getBoundingClientRect();
      summaryDeltaY = summaryRect.bottom - (wsRect.bottom - 8);
    }
    pendingViewportFlip.current = {
      expanding: next,
      wasTransitioning: viewportTransition !== "none",
      fromRightInset,
      fromBottomInset,
      editorOpacity: editor ? Number(getComputedStyle(editor).opacity) : 1,
      summaryOpacity: summary ? Number(getComputedStyle(summary).opacity) : 1,
      editorDeltaX,
      summaryDeltaY,
    };
    cancelViewportMotion();
    clearInlineViewportStyles();
    setViewportExpanded(next);
    setViewportTransition(next ? "expanding" : "collapsing");
  }
  const [cameraRequest, setCameraRequest] = useState(0);
  const [fitRequest, setFitRequest] = useState(0);
  const [stepImport, setStepImport] = useState<StepImportOperation | null>(null);
  const stepImportStartedAt = useRef(0);
  const [stepModel, setStepModel] = useState<StepModelSnapshot | null>(null);
  // Bumped every time a model is loaded into the scene, so the viewport can
  // reset its scene display settings for the fresh model.
  const [stepModelGeneration, setStepModelGeneration] = useState(0);
  const [selectedStepFace, setSelectedStepFace] = useState<number | null>(null);
  const [stepPalletBuilt, setStepPalletBuilt] = useState(false);
  const [solidWorksOptions, setSolidWorksOptions] = useState<SolidWorksOptions | null>(storedSolidWorksOptions);
  const [exporting, setExporting] = useState<DrawingCad | null>(null);
  const [exportStage, setExportStage] = useState<"models" | "drawings">("models");
  const [exportCancelling, setExportCancelling] = useState(false);
  const exportCancelRequested = useRef(false);
  const requestCancelExport = useCallback(() => {
    exportCancelRequested.current = true;
    setExportCancelling(true);
  }, []);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [exportSetupOpen, setExportSetupOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const closeReset = useCallback(() => setResetOpen(false), []);
  const exportDialog = useRef<HTMLElement>(null);
  const [exportCadSystem, setExportCadSystem] = useState<DrawingCad>("solidworks");
  const [exportDirectory, setExportDirectory] = useState("");
  const [exportDirectoryError, setExportDirectoryError] = useState<string | null>(null);
  useEffect(() => {
    if (!exportSetupOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    exportDialog.current?.focus();
    const handleDialogKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopImmediatePropagation(); setExportSetupOpen(false); }
      if (event.key !== "Tab" || !exportDialog.current) return;
      const elements = Array.from(exportDialog.current.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex='0']"));
      const first = elements[0], last = elements[elements.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && (document.activeElement === first || document.activeElement === exportDialog.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", handleDialogKey, true);
    return () => { window.removeEventListener("keydown", handleDialogKey, true); previousFocus?.focus(); };
  }, [exportSetupOpen]);
  const [includePalletModel, setIncludePalletModel] = useState(true);
  const [includePartModels, setIncludePartModels] = useState(true);
  const [includePalletDrawing, setIncludePalletDrawing] = useState(true);
  const [includePartDrawings, setIncludePartDrawings] = useState(false);
  const [includeExportModel, setIncludeExportModel] = useState(false);
  const [includePackagingDrawing, setIncludePackagingDrawing] = useState(false);
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
  const [manualReferenceMode, setManualReferenceMode] = useState<"base" | "face" | "between">("base");
  const [manualReference, setManualReference] = useState<ViewportBeam | null>(null);
  const [manualReferenceFace, setManualReferenceFace] = useState<BeamReferenceFace>("x_min");
  const [manualSecondReference, setManualSecondReference] = useState<BeamReference | null>(null);
  const firstManualReference = manualReference ? { beam: manualReference, face: manualReferenceFace } : null;
  function manualSectionFor(beam: ViewportBeam | null | undefined): BeamSection {
    return manualSectionForSupport(project?.pallet.layers ?? [], beam, section);
  }
  const manualBeamSection = manualSectionFor(manualSupports[0]?.beam);
  const manualBetween = firstManualReference && manualSecondReference
    ? betweenFaces(firstManualReference, manualSecondReference, manualBeamSection.width) : null;
  const manualBeamInFlight = useRef(false);
  const [viewportToolError, setViewportToolError] = useState<string | null>(null);
  const [viewportToolErrorVersion, setViewportToolErrorVersion] = useState(0);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [recoveryNotice, setRecoveryNotice] = useState<string | null>(null);
  const [historyReadErrorOpen, setHistoryReadErrorOpen] = useState(false);
  const undoStack = useRef<Project[]>([]);
  const redoStack = useRef<Project[]>([]);
  const currentHistory = useMemo(
    () => JSON.stringify({ undo: undoStack.current, redo: redoStack.current }),
    [historyVersion],
  );
  const hasBuiltStepModel = Boolean(
    stepPalletBuilt
    && project?.step_model?.source
    && project.step_model.transform.length === 16,
  );
  useEffect(() => {
    if (!hasBuiltStepModel) {
      setIncludeExportModel(false);
      setIncludePackagingDrawing(false);
    }
  }, [hasBuiltStepModel]);
  const hasUnsavedChanges = project !== null && (
    JSON.stringify(project) !== savedProject || currentHistory !== savedHistory
  );
  const formEditStart = useRef<Project | null>(null);
  const viewportToolErrorTimeout = useRef<number | null>(null);
  const lastNotifiedCalculationError = useRef<string | null>(null);
  const connectionStarted = useRef(false);
  const calculatedInitialProject = useRef<Project | null>(null);
  const stepPlacement = useRef<{ transform: number[]; starts: [number, number] } | null>(null);
  // Set by a project reset and consumed by the first calculation that lands
  // afterwards, so the isometric preset applies with the fresh bounds.
  const resetCameraPending = useRef(false);
  const stepRestoreGeneration = useRef(0);
  const [stepRestoreError, setStepRestoreError] = useState<string | null>(null);

  async function restoreProjectStep(nextProject: Project) {
    const generation = ++stepRestoreGeneration.current;
    const model = nextProject.step_model;
    setStepModel(null);
    setStepImport(null);
    setSelectedStepFace(null);
    setStepPalletBuilt(false);
    setStepRestoreError(null);
    stepPlacement.current = null;
    if (!model) return;
    stepImportStartedAt.current = performance.now();
    stepPlacement.current = { transform: model.transform, starts: model.starts };
    setStepPalletBuilt(true);
    setIncludeExportModel(true);
    setIncludePackagingDrawing(true);
    try {
      const response = await window.pywebview!.api!.restore_step_model(model.source);
      if (generation !== stepRestoreGeneration.current) return;
      if (!response.ok) {
        setStepRestoreError(`Не удалось восстановить STEP-модель: ${response.error ?? "файл недоступен"}`);
        return;
      }
      setStepImport(response);
    } catch {
      if (generation === stepRestoreGeneration.current) setStepRestoreError("Не удалось восстановить STEP-модель из файла проекта.");
    }
  }

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

  function applyProject(nextProject: Project, expandTopLayer = false) {
    const topLayerId = nextProject.pallet.layers.at(-1)?.id ?? null;
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
    setSelectedLayerId((current) => expandTopLayer
      ? topLayerId
      : nextProject.pallet.layers.some((layer) => layer.id === current) ? current : null);
    setExpandedLayerId((current) => expandTopLayer
      ? topLayerId
      : nextProject.pallet.layers.some((layer) => layer.id === current) ? current : null);
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
    if (JSON.stringify(project.step_model) !== JSON.stringify(previous.step_model)) void restoreProjectStep(previous);
    applyProject(previous);
    clearInteractionState();
    setHistoryVersion((value) => value + 1);
  }

  function redo() {
    finishFormEdit();
    const next = redoStack.current.pop();
    if (!project || !next) return;
    undoStack.current.push(copyProject(project));
    if (JSON.stringify(project.step_model) !== JSON.stringify(next.step_model)) void restoreProjectStep(next);
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
      if (resetCameraPending.current) {
        // A project reset replaced the whole scene: return the camera to the
        // default isometric view once the reset snapshot has rendered, exactly
        // like building a pallet from a model does.
        resetCameraPending.current = false;
        setCameraRequest((value) => value + 1);
      }
    } else {
      resetCameraPending.current = false;
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
      if (!api || typeof api.status !== "function") return;
      connectionStarted.current = true;
      setRecoveryNotice(null);
      try {
        reportStartupStage("мост Python подключён");
        const [nextStatus, defaultProject, loadedSettings, updateState] = await Promise.all([
          api.status(), api.default_project(), api.application_settings(), api.update_status(),
        ]);
        setUpdate(updateState);
        setLastUpdateCheck(updateState.lastCheckedAt ?? null);
        setSettings(loadedSettings);
        const defaultWithSettings = projectWithDefaults(defaultProject as Project, loadedSettings);
        const recovered = loadedSettings.autosaveEnabled ? (await api.recovery_project()) : null;
        const initialProject = recovered ?? defaultWithSettings;
        const initialCalculation = await api.calculate(initialProject);
        reportStartupStage("первый расчёт завершён");
        if (recovered) {
          if (initialCalculation.ok && initialCalculation.snapshot) {
            calculatedInitialProject.current = initialCalculation.snapshot.project;
            applyProject(initialCalculation.snapshot.project, true);
            applyCalculation(initialCalculation);
            void restoreProjectStep(initialCalculation.snapshot.project);
            setRecoveryNotice("Восстановлен последний автосохранённый проект.");
          } else {
            void api.clear_recovery_project();
            projectBaseline.current = JSON.stringify(defaultWithSettings);
            applyProject(defaultWithSettings, true);
          }
        } else {
          if (initialCalculation.ok && initialCalculation.snapshot) {
            calculatedInitialProject.current = initialCalculation.snapshot.project;
            projectBaseline.current = JSON.stringify(initialCalculation.snapshot.project);
            applyProject(initialCalculation.snapshot.project, true);
            applyCalculation(initialCalculation);
          } else {
            projectBaseline.current = JSON.stringify(defaultWithSettings);
            applyProject(defaultWithSettings, true);
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
      } catch (error) {
        console.error("[PalletLab] Ошибка запуска:", error);
        setStatus(null);
        setRecoveryNotice(`Не удалось загрузить проект: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    window.addEventListener("pywebviewready", connect, { once: true });
    void connect();
    const poll = window.setInterval(() => {
      if (connectionStarted.current) {
        window.clearInterval(poll);
        return;
      }
      void connect();
    }, 100);
    return () => {
      window.clearInterval(poll);
      window.removeEventListener("pywebviewready", connect);
    };
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

  async function checkForUpdates(manual: boolean) {
    const api = window.pywebview?.api;
    if (!api) return;
    try {
      const result = await api.check_update(manual);
      setUpdate(result);
      if (result.lastCheckedAt) setLastUpdateCheck(result.lastCheckedAt);
      if (manual) setUpdateDismissed(false);
    } catch {
      setUpdate({ state: "check_failed" });
    }
  }

  useEffect(() => {
    if (!status || !settings.checkUpdates) return undefined;
    const timeout = window.setTimeout(() => {
      void checkForUpdates(false);
    }, 1500);
    return () => window.clearTimeout(timeout);
  }, [status]);

  useEffect(() => {
    if (update.state !== "checking" && update.state !== "downloading") return undefined;
    const timer = window.setInterval(() => {
      void window.pywebview?.api?.update_status().then((result) => { setUpdate(result); if (result.lastCheckedAt) setLastUpdateCheck(result.lastCheckedAt); }).catch(() => undefined);
    }, 500);
    return () => window.clearInterval(timer);
  }, [update.state]);

  useEffect(() => {
    if (!status || !settings.autosaveEnabled) return;
    const timer = window.setInterval(() => {
      if (!currentProject.current) return;
      const serialized = JSON.stringify(currentProject.current);
      if (serialized === projectBaseline.current || serialized === savedProject) return;
      void window.pywebview?.api?.save_recovery_project(currentProject.current).catch(() => undefined);
    }, settings.autosaveMinutes * 60_000);
    return () => window.clearInterval(timer);
  }, [status, settings.autosaveEnabled, settings.autosaveMinutes, savedProject]);

  async function saveApplicationSettings(next: AppSettings, solidworks: SolidWorksOptions | null): Promise<boolean> {
    const api = window.pywebview?.api;
    if (!api) return false;
    const response = await api.save_program_settings(next, solidworks);
    if (!response.ok) return false;
    if (solidworks) {
      setSolidWorksOptions(solidworks);
      try { window.localStorage.setItem(SOLIDWORKS_OPTIONS_KEY, JSON.stringify(solidworks)); } catch { /* Optional cache. */ }
    }
    setSettings(next);
    const current = currentProject.current;
    const updated = current ? applyDefaultsIfUnmodified(current, projectBaseline.current, settings, next) : null;
    if (current && updated) {
      projectBaseline.current = JSON.stringify(updated);
      applyProject(updated);
      if (current.view.camera !== updated.view.camera) setCameraRequest((value) => value + 1);
    }
    return true;
  }

  async function saveProject(saveAs = false) {
    if (!project || saving) return;
    const savedVersion = JSON.stringify(project);
    const history = {
      undo: undoStack.current.map(copyProject),
      redo: redoStack.current.map(copyProject),
    };
    const savedHistoryVersion = JSON.stringify(history);
    setSaving(true);
    let response: { ok: boolean; cancelled?: boolean; error?: string };
    try {
      response = await window.pywebview!.api!.save_project(project, saveAs, history);
    } catch {
      setCalculationError("Не удалось сохранить проект.");
      return;
    } finally {
      setSaving(false);
    }
    if (response.ok) {
      setSavedProject(savedVersion);
      setSavedHistory(savedHistoryVersion);
      void window.pywebview?.api?.clear_recovery_project();
      setRecoveryNotice(null);
    } else if (!response.cancelled)
      setCalculationError(response.error ?? "Не удалось сохранить проект.");
  }
  async function openProject() {
    const response = await window.pywebview!.api!.open_project();
    if (response.project) {
      void restoreProjectStep(response.project);
      projectBaseline.current = JSON.stringify(response.project);
      applyProject(response.project, true);
      setSavedProject(JSON.stringify(response.project));
      setCalculationError(null);
      undoStack.current = response.history?.undo ?? [];
      redoStack.current = response.history?.redo ?? [];
      setSavedHistory(response.history_warning === true ? null : JSON.stringify({
        undo: undoStack.current,
        redo: redoStack.current,
      }));
      void window.pywebview?.api?.clear_recovery_project();
      setRecoveryNotice(null);
      setHistoryReadErrorOpen(response.history_warning === true);
      setHistoryVersion((value) => value + 1);
    } else if (!response.cancelled) {
      setCalculationError(response.error ?? "Не удалось открыть проект.");
    }
  }

  function openExportSetup() {
    setExportDirectory(settings.exportDirectory);
    setExportDirectoryError(null);
    setExportSetupOpen(true);
  }

  function changePartModels(enabled: boolean) {
    setIncludePartModels(enabled);
    if (!enabled) {
      setIncludePalletModel(false);
      setIncludePalletDrawing(false);
      setIncludePartDrawings(false);
      setIncludeExportModel(false);
      setIncludePackagingDrawing(false);
    }
  }

  function changePalletModel(enabled: boolean) {
    setIncludePalletModel(enabled);
    if (!enabled) {
      setIncludePalletDrawing(false);
      setIncludeExportModel(false);
      setIncludePackagingDrawing(false);
    }
  }

  async function browseExportDirectory() {
    const api = window.pywebview?.api;
    if (!api) return;
    setExportDirectoryError(null);
    try {
      const response = await api.choose_export_directory();
      if (response.cancelled) return;
      if (!response.ok || !response.path) {
        setExportDirectoryError(response.error ?? "Не удалось выбрать папку экспорта.");
        return;
      }
      setExportDirectory(response.path);
    } catch (error) {
      setExportDirectoryError(error instanceof Error ? error.message : "Не удалось выбрать папку экспорта.");
    }
  }

  async function exportCad() {
    const api = window.pywebview?.api;
    if (!api || !project || !includePartModels) return;
    if (includeExportModel && !hasBuiltStepModel) {
      setExportDirectoryError("Чтобы создать модель упаковки, сначала постройте поддон по STEP-модели.");
      return;
    }
    if (!exportDirectory.trim()) {
      setExportDirectoryError("Укажите папку для сохранения экспорта.");
      return;
    }
    const cad = exportCadSystem;
    const options = solidWorksOptions;
    if (cad === "solidworks" && (!options
      || !options.partTemplate.trim()
      || !options.assemblyTemplate.trim()
      || !options.drawingTemplate.trim()
      || !options.materialLibrary.trim()
      || !options.materialName.trim())) {
      setExportSetupOpen(false);
      setSettingsInitialSection("cad");
      setSettingsOpen(true);
      return;
    }

    setExportSetupOpen(false);
    exportCancelRequested.current = false;
    setExportCancelling(false);
    setExportStage("models");
    setExporting(cad);
    await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    const target = cad === "kompas" ? "КОМПАС-3D" : "SolidWorks";
    let modelOutput: string | null = null;
    try {
      let models: CommandResponse;
      if (cad === "kompas") {
        models = await api.export_kompas(
          project, includePalletModel, exportDirectory.trim(), includeExportModel,
        );
      } else if (options) {
        models = await api.export_solidworks(
          project, options, includePalletModel, exportDirectory.trim(), includeExportModel,
        );
      } else {
        throw new Error("Сначала настройте экспорт SolidWorks.");
      }
      if (models.cancelled) return;
      if (!models.ok || !models.output) {
        setExportResult({
          target,
          ok: false,
          message: models.error ?? "Экспорт моделей не выполнен.",
        });
        return;
      }
      modelOutput = models.output;

      const drawingScope: DrawingScope | null = includePalletDrawing && includePartDrawings
        ? "parts_and_assembly"
        : includePalletDrawing
          ? "assembly"
          : includePartDrawings
            ? "parts"
            : null;
      const drawingJobs: { scope: DrawingScope; exportModel: boolean }[] = [];
      if (drawingScope) drawingJobs.push({ scope: drawingScope, exportModel: false });
      if (includePackagingDrawing) drawingJobs.push({ scope: "assembly", exportModel: true });
      if (exportCancelRequested.current) {
        setExportResult({
          target,
          ok: false,
          message: drawingJobs.length > 0
            ? `Экспорт прерван пользователем.\nМодели сохранены в папке:\n${models.output}`
            : `Экспорт прерван пользователем.\nМодели уже были сформированы в папке:\n${models.output}`,
        });
        return;
      }
      let drawingsOutput: string | null = null;
      for (const job of drawingJobs) {
        setExportStage("drawings");
        const drawings = await api.create_drawings(
          project,
          cad,
          job.scope,
          cad === "solidworks" ? options?.drawingTemplate || null : null,
          models.output,
          job.exportModel,
        );
        if (exportCancelRequested.current) {
          setExportResult({
            target,
            ok: false,
            message: `Экспорт прерван пользователем.\nМодели сохранены в папке:\n${models.output}`,
          });
          return;
        }
        if (drawings.cancelled || !drawings.ok) {
          setExportResult({
            target,
            ok: false,
            message: `Модели сохранены в папке:\n${models.output}\n\nЧертежи не созданы: ${drawings.error ?? "операция отменена."}`,
          });
          return;
        }
        drawingsOutput = drawings.output ?? drawingsOutput;
      }
      setExportResult({
        target,
        ok: true,
        message: drawingsOutput && drawingsOutput !== models.output
          ? `Модели сохранены в папке:\n${models.output}\n\nЧертежи сохранены в папке:\n${drawingsOutput}`
          : `Папка экспорта сохранена тут:\n${models.output}`,
      });
    } catch (error) {
      setExportResult({
        target,
        ok: false,
        message: modelOutput
          ? `Модели сохранены в папке:\n${modelOutput}\n\nНе удалось создать чертежи: ${error instanceof Error ? error.message : "ошибка CAD-экспорта."}`
          : error instanceof Error ? error.message : "Не удалось выполнить экспорт CAD.",
      });
    } finally {
      exportCancelRequested.current = false;
      setExportCancelling(false);
      setExporting(null);
    }
  }

  async function importStepModel() {
    const api = window.pywebview?.api;
    if (!api) return;
    const response = await api.import_step_model();
    if (response.cancelled) return;
    if (!response.ok) {
      setCalculationError(response.error ?? "Не удалось импортировать STEP-модель.");
      return;
    }
    stepImportStartedAt.current = performance.now();
    stepRestoreGeneration.current += 1;
    setStepRestoreError(null);
    if (project?.step_model) {
      const { step_model: _previousModel, ...withoutModel } = project;
      updateProject(withoutModel);
    }
    setStepModel(null);
    setSelectedStepFace(null);
    setStepPalletBuilt(false);
    setBuildingStepPallet(false);
    setStepImport(response);
  }

  async function cancelStepImport() {
    if (!stepImport) return;
    if (stepImport.state === "completed") {
      stepRestoreGeneration.current += 1;
      setStepImport(null);
      setStepRestoreError(null);
      return;
    }
    const api = window.pywebview?.api;
    if (!api || !stepImport.operationId) return;
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
      if (stepPalletBuilt) setStepRestoreError(`Не удалось восстановить STEP-модель: ${stepImport.error ?? "ошибка импорта"}`);
    }
  }, [stepImport?.error, stepImport?.state, stepPalletBuilt]);

  useEffect(() => {
    let cancelled = false;
    let preparationWorker: Worker | null = null;
    async function loadPreparedModel() {
      const api = window.pywebview?.api;
      if (!api || !stepImport?.operationId || stepImport.state !== "completed") return;
      try {
        const response = await api.step_model_snapshot(stepImport.operationId);
        if (response.ok && response.assetUrl) {
          const assetUrl = response.assetUrl;
          if (cancelled) return;
          preparationWorker = new Worker(new URL("./stepModelPreparation.worker.ts", import.meta.url), { type: "module" });
          const prepared = await new Promise<StepModelSnapshot>((resolve, reject) => {
            preparationWorker!.onmessage = (event: MessageEvent<{ model?: StepModelSnapshot; error?: string }>) => {
              if (event.data.model) resolve(event.data.model);
              else reject(new Error(event.data.error ?? "Не удалось подготовить STEP-модель для просмотра."));
            };
            preparationWorker!.onerror = () => reject(new Error("Не удалось подготовить STEP-модель для просмотра."));
            preparationWorker!.onmessageerror = () => reject(new Error("Не удалось получить подготовленную STEP-модель."));
            preparationWorker!.postMessage({ assetUrl } satisfies StepModelPayload);
          });
          preparationWorker.terminate();
          preparationWorker = null;
          const remaining = remainingImportFeedback(stepImportStartedAt.current, performance.now());
          if (remaining > 0) await new Promise<void>((resolve) => window.setTimeout(resolve, remaining));
          if (cancelled) return;
          setStepModel(prepared);
          setStepModelGeneration((value) => value + 1);
          setFitRequest((value) => value + 1);
        } else {
          if (!cancelled) setStepRestoreError(response.error ?? "Не удалось подготовить STEP-модель для просмотра.");
        }
      } catch (error) {
        preparationWorker?.terminate();
        preparationWorker = null;
        if (!cancelled) setStepRestoreError(error instanceof Error ? error.message : "Не удалось подготовить STEP-модель для просмотра.");
      }
    }
    void loadPreparedModel();
    return () => { cancelled = true; preparationWorker?.terminate(); };
  }, [stepImport?.operationId, stepImport?.state]);

  async function buildStepPallet(faceIndex = selectedStepFace) {
    const api = window.pywebview?.api;
    if (!api || !project || !stepImport?.operationId || faceIndex === null || buildingStepPallet) return;
    setBuildingStepPallet(true);
    try {
      const response = await api.build_step_pallet(stepImport.operationId, project, faceIndex);
      if (response.ok && response.snapshot && response.modelTransform && stepImport.path && !response.placementMatrix) {
        setCalculationError("Не удалось определить матрицу размещения STEP-модели.");
        return;
      }
      applyCalculation(response);
      if (response.ok && response.snapshot && response.modelTransform && response.placementMatrix && stepImport.path) {
        const placementMatrix = response.placementMatrix;
        const margins = palletMargins(response.snapshot.project);
        stepPlacement.current = {
          transform: response.modelTransform,
          starts: [margins[0], margins[2]],
        };
        const nextProject: Project = {
          ...response.snapshot.project,
          step_model: {
            source: stepImport.path,
            transform: response.modelTransform,
            starts: [margins[0], margins[2]],
            placement_matrix: placementMatrix,
          },
          view: { ...response.snapshot.project.view, camera: "isometric" },
        };
        updateHistory(project, nextProject);
        applyProject(nextProject);
        setStepModel((model) => model ? { ...model, transform: response.modelTransform! } : model);
        setSelectedStepFace(null);
        setStepPalletBuilt(true);
        setIncludeExportModel(true);
        setIncludePackagingDrawing(true);
        setCameraRequest((value) => value + 1);
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
    const defaultProject = projectWithDefaults((await api.default_project()) as Project, settings);
    // The desktop reset restores the example geometry but intentionally keeps
    // the material selection, so both frontends have the same semantics.
    const nextProject = {
      ...defaultProject,
      pallet: { ...defaultProject.pallet, material_id: project.pallet.material_id },
    };
    updateProject(nextProject);
    projectBaseline.current = JSON.stringify(nextProject);
    // The reset recalculation is debounced; the camera command is consumed by
    // the first calculation that lands afterwards.
    resetCameraPending.current = true;
    stepRestoreGeneration.current += 1;
    setStepRestoreError(null);
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
    return Number(((alongX ? support.point[0] : support.point[2]) * 1000 - manualSectionFor(support.beam).width / 2).toFixed(2));
  }

  function isLocked(layerId: string) {
    return project?.view.locked_layer_ids?.includes(layerId) ?? false;
  }

  function toggleLayerLock(layerId: string) {
    if (!project) return;
    const locked = project.view.locked_layer_ids ?? [];
    const next = locked.includes(layerId) ? locked.filter((id) => id !== layerId) : [...locked, layerId];
    clearInteractionState();
    updateProject({ ...project, view: { ...project.view, locked_layer_ids: next } });
  }

  function toggleBeam(beam: ViewportBeam, point?: ViewportPoint, normal?: ViewportFaceNormal) {
    if (!insertionMode && isLocked(beam.physicalLayerId)) {
      showViewportToolError("Слой заблокирован. Сначала разблокируйте его.");
      return;
    }
    if (insertionMode) {
      if ((manualReferenceMode === "face" || manualReferenceMode === "between") && manualSupports.length === 2) {
        const support = manualSupports[0].beam;
        const alongX = support.size[0] >= support.size[1];
        const directionalNormal = alongX ? normal?.[0] : normal?.[2];
        if (directionalNormal === undefined || Math.abs(directionalNormal) < 0.9) {
          showViewportToolError("Выберите боковую грань бруса в направлении нового бруса.");
          return;
        }
        const face: BeamReferenceFace = alongX
          ? directionalNormal > 0 ? "x_max" : "x_min"
          : directionalNormal > 0 ? "y_max" : "y_min";
        if (manualReferenceMode === "between" && manualReference) {
          const candidate = { beam, face };
          if (!betweenFaces({ beam: manualReference, face: manualReferenceFace }, candidate, manualBeamSection.width)) {
            showViewportToolError("Выберите противоположную грань другого бруса, чтобы новый брус поместился между ними.");
            return;
          }
          setManualSecondReference(candidate);
          return;
        }
        setManualReference(beam);
        setManualReferenceFace(face);
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
    if (!api || !project || selectedBeams.length === 0 || selectedBeams.some((beam) => isLocked(beam.physicalLayerId))) return;
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
    if (!api || !project || selectedBeams.length === 0 || selectedBeams.some((beam) => isLocked(beam.physicalLayerId))) return;
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
    const beam = calculation?.snapshot?.pallet?.beams.find((item) => item.layerId === dimension.layerId && item.layerIndex === dimension.index);
    if (isLocked(beam?.physicalLayerId ?? dimension.layerId)) {
      showViewportToolError("Слой заблокирован. Сначала разблокируйте его.");
      return;
    }
    setSelectedDimension(dimension);
    setDistanceValue(dimension.editValue ?? dimension.value);
  }

  async function changeSelectedDistance() {
    const api = window.pywebview?.api;
    if (!api || !project || !selectedDimension) return;
    const beam = calculation?.snapshot?.pallet?.beams.find((item) => item.layerId === selectedDimension.layerId && item.layerIndex === selectedDimension.index);
    if (isLocked(beam?.physicalLayerId ?? selectedDimension.layerId)) return;
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
    setManualSecondReference(null);
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
      if (manualSecondReference) {
        setManualSecondReference(null);
        return;
      }
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
    if (!api || !project || !selectedSlot || isLocked(selectedSlot.layerId)) return;
    const response = await api.insert_beam(project, selectedSlot, insertionGap);
    applyCalculation(response);
    if (response.ok && response.snapshot) {
      updateHistory(project, response.snapshot.project);
      applyProject(response.snapshot.project);
      setSelectedSlot(null);
    }
  }

  function selectInsertion(marker: ViewportInsertionMarker) {
    if (isLocked(marker.slot.layerId)) {
      showViewportToolError("Слой заблокирован. Сначала разблокируйте его.");
      return;
    }
    setSelectedSlot(marker.slot);
    setInsertionGap(marker.slot.suggestedClearGap);
  }

  async function addManualBeam() {
    const api = window.pywebview?.api;
    if (!api || !project || manualSupports.length !== 2
        || (manualReferenceMode === "face" && !manualReference)
        || (manualReferenceMode === "between" && !manualBetween)
        || manualBeamInFlight.current) return;
    const supportIndex = project.pallet.layers.findIndex((layer) => layer.id === manualSupports[0].beam.physicalLayerId);
    const targetLayer = project.pallet.layers[supportIndex + 1];
    if (supportIndex >= 0 && targetLayer && isLocked(targetLayer.id)) {
      showViewportToolError("Слой для нового бруса заблокирован. Сначала разблокируйте его.");
      return;
    }
    manualBeamInFlight.current = true;
    try {
      const response = await api.add_manual_beam(
        project,
        manualSupports.map(({ beam }) => ({
          layerId: beam.layerId,
          layerIndex: beam.layerIndex,
        })),
        {
          distance: manualReferenceMode === "between" ? manualBetween!.baseDistance : manualDistance,
          section: manualBeamSection,
          reference: manualReference ? { layerId: manualReference.layerId, layerIndex: manualReference.layerIndex } : undefined,
          referenceFace: manualReference ? manualReferenceFace : undefined,
          secondReference: manualReferenceMode === "between" && manualSecondReference
            ? { layerId: manualSecondReference.beam.layerId, layerIndex: manualSecondReference.beam.layerIndex } : undefined,
          secondReferenceFace: manualReferenceMode === "between" ? manualSecondReference?.face : undefined,
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
        setManualSecondReference(null);
        setSelectedBeams([]);
      }
    } finally {
      manualBeamInFlight.current = false;
    }
  }

  useEffect(() => {
    const handleKeyboardShortcut = (event: KeyboardEvent) => {
      if (settingsOpen || exportSetupOpen || resetOpen) return;
      if (exporting) {
        if (event.key === "Escape" && !exportCancelling) {
          event.preventDefault();
          requestCancelExport();
        }
        return;
      }
      if (exportResult) {
        if (event.key === "Escape") {
          event.preventDefault();
          setExportResult(null);
        }
        return;
      }
      if (stepImport && stepImportPhase(stepImport.state, stepModel !== null, stepRestoreError !== null)) {
        if (event.key === "Escape" && stepImport.state !== "cancelling") {
          event.preventDefault();
          void cancelStepImport();
        }
        return;
      }
      if (event.key === "Escape" && event.target instanceof Element && event.target.closest(".scene-settings-anchor")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        stopDimensionEditing();
        stopInsertion();
        setBeamTool("none");
        setSelectedBeams([]);
        return;
      }
      if (event.key === "Enter") {
        // Handled here in the capture phase so confirming works no matter
        // which element holds focus; the HUD inputs no longer confirm
        // themselves, which also keeps a focused input from double-firing.
        const inHud = event.target instanceof HTMLElement
          && event.target.closest(".manual-hud") !== null
          && event.target.closest(".scene-settings-panel") === null;
        const editable = event.target instanceof HTMLInputElement
          || event.target instanceof HTMLSelectElement
          || event.target instanceof HTMLTextAreaElement;
        if (insertionMode && manualSupports.length === 2) {
          const ready = !(manualReferenceMode === "face" && !manualReference)
            && !(manualReferenceMode === "between" && !manualBetween);
          if (ready && !(event.target instanceof HTMLButtonElement) && (inHud || !editable)) {
            event.preventDefault();
            void addManualBeam();
          }
          return;
        }
        if (!dimensionEditing && !(event.target instanceof HTMLButtonElement)) {
          if (beamTool === "delete" && selectedBeams.length > 0) {
            event.preventDefault();
            void deleteSelectedBeams();
          } else if (beamTool === "section" && selectedBeams.length > 0) {
            event.preventDefault();
            void changeSelectedBeamSections();
          }
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
    if (!layer || isLocked(layer.id)) return;
    const updatedDirection = { ...layer.direction, ...patch } as Direction;
    const targetRawSize = rawPalletSize(updatedDirection);
    if (project.pallet.layers.some((item) => item.id !== layer.id && item.axis === layer.axis && isLocked(item.id)
      && Math.abs(rawPalletSize(updatedDirection) - rawPalletSize(item.direction)) > 0.000001)) {
      setDistanceText((current) => ({ ...current, [layer.id]: layer.direction.support_distances.join(" ") }));
      showViewportToolError("Изменение затрагивает заблокированный слой. Сначала разблокируйте его.");
      return;
    }
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
    setProject(changeIndependentPalletMargin(project, index, next));
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
    if (!project || isLocked(project.pallet.layers[index]?.id)) return;
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
    setSelectedLayerId(layerId);
  }

  async function duplicateLayer() {
    const api = window.pywebview?.api;
    if (!api || !project || !selectedLayerId || duplicatingLayer.current) return;
    duplicatingLayer.current = true;
    setDuplicateBusy(true);
    try {
      const response = await api.duplicate_layer(project, selectedLayerId);
      if (!response.ok || !response.snapshot || !response.layerId) {
        showViewportToolError(response.error ?? "Не удалось продублировать слой.");
        return;
      }
      if (currentProject.current !== project) {
        showViewportToolError("Проект изменился во время дублирования. Повторите действие.");
        return;
      }
      clearInteractionState();
      updateHistory(project, response.snapshot.project);
      applyProject(response.snapshot.project);
      applyCalculation(response);
      setSelectedLayerId(response.layerId);
      setExpandedLayerId(response.layerId);
    } catch {
      showViewportToolError("Не удалось продублировать слой.");
    } finally {
      duplicatingLayer.current = false;
      setDuplicateBusy(false);
    }
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
    if (manualSecondReference?.beam.layerId === layerId) setManualSecondReference(null);
  }

  function reorderLayerToVisualIndex(sourceId: string, targetVisualIndex: number) {
    if (!project) return;
    if (isLocked(sourceId)) {
      showViewportToolError("Слой заблокирован. Сначала разблокируйте его.");
      return;
    }
    const source = project.pallet.layers.find((layer) => layer.id === sourceId);
    const layers = project.pallet.layers.filter((layer) => layer.id !== sourceId);
    if (!source) return;
    const insertAt = Math.max(0, Math.min(layers.length, layers.length - targetVisualIndex));
    layers.splice(insertAt, 0, source);
    updateProject({ ...project, pallet: { ...project.pallet, layers } });
  }

  useLayoutEffect(() => {
    const prevTops = pendingSiblingTops.current;
    if (prevTops) {
      pendingSiblingTops.current = null;
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (!reducedMotion) {
        for (const [id, prevTop] of prevTops) {
          const element = layerCardRefs.current.get(id);
          if (!element) continue;
          const nextTop = element.getBoundingClientRect().top;
          const deltaY = prevTop - nextTop;
          if (Math.abs(deltaY) < 0.5) continue;
          layerFlipAnimations.current.get(id)?.cancel();
          const anim = element.animate(
            [{ transform: `translate3d(0, ${deltaY}px, 0)` }, { transform: "translate3d(0, 0, 0)" }],
            { duration: 240, easing: "cubic-bezier(0.2, 0, 0, 1)" },
          );
          layerFlipAnimations.current.set(id, anim);
          void anim.finished.then(() => {
            if (layerFlipAnimations.current.get(id) === anim) layerFlipAnimations.current.delete(id);
          }).catch(() => undefined);
        }
      }
    }
    const drop = pendingDropRect.current;
    if (drop) {
      pendingDropRect.current = null;
      const element = layerCardRefs.current.get(drop.id);
      const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      if (element && !reducedMotion && typeof element.animate === "function") {
        const nextRect = element.getBoundingClientRect();
        const dx = drop.rect.left - nextRect.left;
        const dy = drop.rect.top - nextRect.top;
        layerFlipAnimations.current.get(drop.id)?.cancel();
        const anim = element.animate(
          [
            {
              transform: `translate3d(${dx}px, ${dy}px, 0) scale(1.02)`,
              boxShadow: "0 14px 32px rgb(0 0 0 / 16%), 0 0 0 1px var(--color-blue-400)",
            },
            {
              transform: "translate3d(0, 0, 0) scale(1)",
              boxShadow: "0 0 0 0 transparent",
            },
          ],
          { duration: 220, easing: "cubic-bezier(0.2, 0, 0, 1)" },
        );
        layerFlipAnimations.current.set(drop.id, anim);
        void anim.finished.then(() => {
          if (layerFlipAnimations.current.get(drop.id) === anim) layerFlipAnimations.current.delete(drop.id);
        }).catch(() => undefined);
      }
    }
  }, [draggedLayer?.id, draggedLayer?.targetIndex, project?.pallet.layers]);

  function startLayerDrag(event: React.PointerEvent<HTMLElement>, layerId: string) {
    if (event.button !== 0 || !project) return;
    if (isLocked(layerId)) {
      showViewportToolError("Слой заблокирован. Сначала разблокируйте его.");
      return;
    }
    const card = layerCardRefs.current.get(layerId);
    if (!card) return;
    event.preventDefault();
    event.stopPropagation();

    const reversed = [...project.pallet.layers].reverse();
    const startIndex = reversed.findIndex((item) => item.id === layerId);
    if (startIndex < 0) return;

    const cardRect = card.getBoundingClientRect();
    const startClientY = event.clientY;
    let currentTargetIndex = startIndex;
    let lastClientY = startClientY;
    let scrollFrame = 0;

    const captureSiblingTops = () => {
      const tops = new Map<string, number>();
      for (const [id, el] of layerCardRefs.current) {
        if (id !== layerId) tops.set(id, el.getBoundingClientRect().top);
      }
      pendingSiblingTops.current = tops;
    };

    const updateOrderForPointer = (clientY: number) => {
      const floating = floatingLayerRef.current;
      if (floating) {
        floating.style.transform = `translate3d(0, ${clientY - startClientY}px, 0) scale(1.02)`;
      }
      const otherLayers = reversed.filter((item) => item.id !== layerId);
      let nextIndex = currentTargetIndex;
      // Compare pointer Y against adjacent siblings' layout midpoints to avoid
      // oscillation when dragging across cards of different heights.
      while (nextIndex > 0) {
        const prevLayer = otherLayers[nextIndex - 1];
        const prevEl = prevLayer ? layerCardRefs.current.get(prevLayer.id) : null;
        if (!prevEl) break;
        const rect = prevEl.getBoundingClientRect();
        if (clientY < rect.top + rect.height / 2) nextIndex -= 1;
        else break;
      }
      while (nextIndex < otherLayers.length) {
        const nextLayer = otherLayers[nextIndex];
        const nextEl = nextLayer ? layerCardRefs.current.get(nextLayer.id) : null;
        if (!nextEl) break;
        const rect = nextEl.getBoundingClientRect();
        if (clientY > rect.top + rect.height / 2) nextIndex += 1;
        else break;
      }
      if (nextIndex !== currentTargetIndex) {
        currentTargetIndex = nextIndex;
        captureSiblingTops();
        setDraggedLayer((current) => (current ? { ...current, targetIndex: nextIndex } : current));
      }
    };

    const autoScrollStep = () => {
      const container = directionsRef.current;
      if (!container) { scrollFrame = 0; return; }
      const rect = container.getBoundingClientRect();
      const threshold = 44;
      let delta = 0;
      if (lastClientY < rect.top + threshold) {
        delta = -Math.ceil(((rect.top + threshold - lastClientY) / threshold) * 10);
      } else if (lastClientY > rect.bottom - threshold) {
        delta = Math.ceil(((lastClientY - (rect.bottom - threshold)) / threshold) * 10);
      }
      if (delta !== 0) {
        container.scrollTop += delta;
        updateOrderForPointer(lastClientY);
        scrollFrame = window.requestAnimationFrame(autoScrollStep);
      } else {
        scrollFrame = 0;
      }
    };

    const handlePointerMove = (moveEvent: PointerEvent) => {
      lastClientY = moveEvent.clientY;
      updateOrderForPointer(moveEvent.clientY);
      if (!scrollFrame) scrollFrame = window.requestAnimationFrame(autoScrollStep);
    };

    const finishDrag = (commit: boolean) => {
      if (scrollFrame) window.cancelAnimationFrame(scrollFrame);
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerCancel);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      const floating = floatingLayerRef.current;
      if (floating) pendingDropRect.current = { id: layerId, rect: floating.getBoundingClientRect() };
      if (commit && currentTargetIndex !== startIndex) {
        reorderLayerToVisualIndex(layerId, currentTargetIndex);
      }
      setDraggedLayer(null);
    };

    const handlePointerUp = () => finishDrag(true);
    const handlePointerCancel = () => finishDrag(false);

    document.body.style.cursor = "grabbing";
    document.body.style.userSelect = "none";
    setSelectedLayerId(layerId);
    setDraggedLayer({
      id: layerId,
      startIndex,
      targetIndex: startIndex,
      left: cardRect.left,
      top: cardRect.top,
      width: cardRect.width,
      height: cardRect.height,
    });
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    window.addEventListener("pointercancel", handlePointerCancel);
  }

  function removeLayer(layerId: string) {
    if (!project || project.pallet.layers.length <= 2) return;
    const index = project.pallet.layers.findIndex((layer) => layer.id === layerId);
    if (index < 0 || isLocked(layerId)) return;
    const removedLayerId = layerId;
    const manual = project.pallet.manual_beams ?? [];
    const physical = new Map(project.pallet.layers.map((layer) => [layer.id, layer.id]));
    for (const beam of manual) {
      const support = physical.get(beam.first[0]);
      const supportIndex = project.pallet.layers.findIndex((layer) => layer.id === support);
      const target = beam.physical_layer_id ?? (supportIndex >= 0 ? project.pallet.layers[supportIndex + (beam.first_face === "bottom" ? -1 : 1)]?.id : undefined);
      if (target) physical.set(beam.id, target);
    }
    const removedManual = new Set(manual.filter((beam) => physical.get(beam.id) === removedLayerId).map((beam) => beam.id));
    if (manual.some((beam) => !removedManual.has(beam.id)
      && [beam.first, beam.second, beam.reference, beam.second_reference]
        .some((key) => key && (key[0] === removedLayerId || removedManual.has(key[0]))))) {
      showViewportToolError("На брусья этого слоя опираются другие брусья. Сначала удалите зависимые брусья.");
      return;
    }
    setCustomLayerSectionIds((current) => current.filter((id) => id !== removedLayerId));
    updateProject({
      ...project,
      pallet: {
        ...project.pallet,
        manual_beams: manual.filter((beam) => !removedManual.has(beam.id)),
        layer_sections: project.pallet.layer_sections?.filter((section) => section.layer_id !== removedLayerId),
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
    <Hud title="Добавить брус" actions={<><Button onClick={addManualBeam} disabled={(manualReferenceMode === "face" && !manualReference) || (manualReferenceMode === "between" && !manualBetween)}>Добавить</Button><Button variant="ghost" onClick={stopInsertion}>Отмена</Button></>}>
      <label>
        Отсчёт расстояния
        <Combobox
          value={manualReferenceMode}
          options={[
            { value: "base", label: "От нулевой точки" },
            { value: "face", label: "От выбранной грани" },
            { value: "between", label: "Между двух граней" },
          ]}
          onChange={(mode) => {
            setManualReferenceMode(mode);
            setManualReference(null);
            setManualSecondReference(null);
            setManualDistance(mode === "base" ? basePointDistance(manualSupports[0]) : 0);
          }}
        />
      </label>
      <label>
        {manualReferenceMode === "between" ? "От нулевой точки, мм" : "Расстояние, мм"}
        <input
          type="number"
          aria-describedby="manual-distance-hint"
          value={manualReferenceMode === "between" ? (manualBetween ? Number(manualBetween.baseDistance.toFixed(2)) : "") : manualDistance}
          disabled={manualReferenceMode === "between"}
          onChange={(event) => setManualDistance(Number(event.target.value))}
        />
      </label>
      <HudHint id="manual-distance-hint">Расстояние задаёт положение бруса вдоль выбранных опор.</HudHint>
    </Hud>
  ) : null;
  const dimensionHud: ReactNode = dimensionEditing && selectedDimension ? (
    <Hud title="Изменить расстояние" actions={<><Button onClick={changeSelectedDistance}>Изменить</Button><Button variant="ghost" onClick={stopDimensionEditing}>Отмена</Button></>}>
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
    </Hud>
  ) : null;
  const sectionHud: ReactNode = beamTool === "section" && selectedBeams.length > 0 ? (
    <Hud className="section-hud" title={<>Изменить сечение{selectedBeams.length > 1 ? ` · ${selectedBeams.length}` : ""}</>} actions={<><Button onClick={() => void changeSelectedBeamSections()}>Применить</Button><Button variant="ghost" onClick={() => { setBeamTool("none"); setSelectedBeams([]); }}>Отмена</Button></>}>
      <label>
        Стандартное сечение
        <Combobox
          value={sectionPreset}
          options={SECTION_PRESETS.map((preset) => ({ value: preset.id, label: preset.label }))}
          onChange={(presetId) => {
            setSectionPreset(presetId);
            const preset = SECTION_PRESETS.find((item) => item.id === presetId);
            if (preset && "height" in preset && "width" in preset) {
              setSection({ height: preset.height, width: preset.width });
            }
          }}
        />
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
    </Hud>
  ) : null;
  const renderToolbarLabel = (text: string) => (
    <ExpandableLabel text={text} expanded={toolbarExpanded} />
  );
  const viewportToolbar: ReactNode = (
    <>
      <div className={`viewport-toolbar-bar${toolbarExpanded ? " is-expanded" : ""}`}>
        {viewportExpanded ? (
          <Tooltip content="Добавить новый слой поддона">
            <button
              type="button"
              className="viewport-toolbar-btn viewport-toolbar-standalone"
              onClick={addLayer}
              disabled={!project}
              aria-label="Добавить слой"
            >
              <LayersPlus size={16} />{renderToolbarLabel("Добавить слой")}
            </button>
          </Tooltip>
        ) : null}
        <div className="viewport-tools-pill" role="toolbar" aria-label="Инструменты области просмотра">
          <Tooltip content="Отменить последнее действие">
            <button
              type="button"
              className="viewport-toolbar-btn"
              onClick={undo}
              disabled={!project || undoStack.current.length === 0}
              aria-label="Отменить"
            >
              <Undo size={16} />{renderToolbarLabel("Отменить")}
            </button>
          </Tooltip>
          <Tooltip content="Вернуть отменённое действие">
            <button
              type="button"
              className="viewport-toolbar-btn"
              onClick={redo}
              disabled={!project || redoStack.current.length === 0}
              aria-label="Вернуть"
            >
              <Redo size={16} />{renderToolbarLabel("Вернуть")}
            </button>
          </Tooltip>
          <Tooltip content="Добавить новый брус">
            <button
              type="button"
              className={`viewport-toolbar-btn is-selectable${insertionMode ? " is-selected" : ""}`}
              aria-pressed={insertionMode}
              aria-label="Добавить брус"
              onClick={() => insertionMode ? stopInsertion() : activateInsertion()}
            >
              <Plus size={16} />{renderToolbarLabel("Добавить брус")}
            </button>
          </Tooltip>
          <Tooltip content="Выбрать и удалить брусья со сцены">
            <button
              type="button"
              className={`viewport-toolbar-btn is-selectable${beamTool === "delete" ? " is-selected" : ""}`}
              aria-pressed={beamTool === "delete"}
              aria-label="Удалить брус"
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
              <Trash2 size={16} />{renderToolbarLabel(beamTool === "delete" ? `Удалить (${selectedBeams.length})` : "Удалить брус")}
            </button>
          </Tooltip>
          <Tooltip content="Изменить размеры сечения выбранных брусьев">
            <button
              type="button"
              className={`viewport-toolbar-btn is-selectable${beamTool === "section" ? " is-selected" : ""}`}
              aria-pressed={beamTool === "section"}
              aria-label="Изменить сечение"
              onClick={() => beamTool === "section" ? (setBeamTool("none"), setSelectedBeams([])) : activateBeamTool("section")}
            >
              <SquareDimensions size={16} />{renderToolbarLabel("Изменить сечение")}
            </button>
          </Tooltip>
          <Tooltip content="Изменить расстояние между опорами">
            <button
              type="button"
              className={`viewport-toolbar-btn is-selectable${dimensionEditing ? " is-selected" : ""}`}
              aria-pressed={dimensionEditing}
              aria-label="Изменить расстояние"
              onClick={() => dimensionEditing ? stopDimensionEditing() : activateDimensionEditing()}
            >
              <RulerDimensionLine size={16} />{renderToolbarLabel("Изменить расстояние")}
            </button>
          </Tooltip>
        </div>
        <Tooltip content={toolbarExpanded ? "Свернуть панель инструментов" : "Развернуть панель инструментов"}>
          <button
            type="button"
            className="viewport-toolbar-btn viewport-toolbar-standalone viewport-toolbar-toggle"
            onClick={() => setToolbarManualExpanded(nextToolbarManualExpanded(toolbarExpanded, viewportExpanded))}
            aria-expanded={toolbarExpanded}
            aria-label={toolbarExpanded ? "Свернуть панель" : "Развернуть панель"}
          >
            <ChevronRight ref={toolbarChevronRef} size={16} className="viewport-toolbar-chevron" aria-hidden="true" />
          </button>
        </Tooltip>
      </div>
      {viewportExpanded && calculation?.snapshot?.pallet ? (
        <span className="viewport-toolbar-summary">
          <span>Длина: {formatMillimetres(calculation.snapshot.pallet.size.length)} мм</span><span aria-hidden="true">•</span>
          <span>Ширина: {formatMillimetres(calculation.snapshot.pallet.size.width)} мм</span><span aria-hidden="true">•</span>
          <span>Высота: {formatMillimetres(calculation.snapshot.pallet.size.height)} мм</span><span aria-hidden="true">•</span>
          <span>Масса: {formatKilograms(calculation.snapshot.pallet.massKg)} кг</span><span aria-hidden="true">•</span>
          <span>{detailCount(calculation.snapshot.pallet.beams.length)}</span>
        </span>
      ) : <div className="viewport-tool-spacer" />}
      <div className="viewport-toolbar-end">
        <Tooltip content="Выбрать стандартный ракурс камеры" disabled={cameraMenuOpen}>
          <Combobox
            variant="surface"
            value={camera}
            ariaLabel="Вид камеры"
            disabled={!project}
            onOpenChange={setCameraMenuOpen}
            options={[
              { value: "isometric", label: "Изометрия" },
              { value: "top", label: "Сверху" },
              { value: "front", label: "Спереди" },
              { value: "side", label: "Сбоку" },
            ]}
            onChange={(preset) => {
              if (!project) return;
              setCamera(preset);
              setCameraRequest((value) => value + 1);
              updateProject({ ...project, view: { ...project.view, camera: preset } });
            }}
          />
        </Tooltip>
        <Tooltip content={viewportExpanded ? "Свернуть область просмотра в обычный режим" : "Развернуть область просмотра на весь экран"}>
          <button
            type="button"
            className="viewport-toolbar-btn viewport-toolbar-standalone"
            onClick={toggleViewportExpanded}
            aria-pressed={viewportExpanded}
            aria-label={viewportExpanded ? "Свернуть область просмотра" : "Развернуть область просмотра"}
          >
            {viewportExpanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </Tooltip>
      </div>
    </>
  );

  return (
    <TooltipProvider delay={0}>
    <main className="app-shell">
      <header className="app-header">
        <img className="app-brand" src={logo} alt="Pallet Lab" />
        <nav className="app-actions" aria-label="Действия с проектом">
          <Tooltip content="Открыть сохранённый проект поддона">
            <Button variant="ghost" onClick={openProject} disabled={!status}><FolderOpen className="header-icon header-icon--folder-open" size={16} aria-hidden="true" /> Открыть</Button>
          </Tooltip>
          <Tooltip content="Сохранить изменения в текущем проекте">
            <Button variant="ghost" onClick={() => void saveProject()} disabled={!project || saving || !hasUnsavedChanges}><Save className="header-icon header-icon--save" size={16} aria-hidden="true" /> Сохранить</Button>
          </Tooltip>
          <Tooltip content="Сохранить проект в новый файл">
            <Button variant="ghost" onClick={() => void saveProject(true)} disabled={!project || saving}><SavePen className="header-icon header-icon--save-pen" size={16} aria-hidden="true" /> Сохранить как</Button>
          </Tooltip>
          <span className="app-header-separator" aria-hidden="true" />
          <Tooltip content="Загрузить 3D-модель изделия в формате STEP для создания поддона">
            <Button
              variant="ghost"
              onClick={() => void importStepModel()}
              disabled={!status || stepImportPhase(stepImport?.state, stepModel !== null, stepRestoreError !== null) !== null}
            >
              <FolderInput className="header-icon header-icon--folder-input" size={16} aria-hidden="true" /> Импорт модели…
            </Button>
          </Tooltip>
          <span className="app-header-separator" aria-hidden="true" />
          <Tooltip content="Настроить и выполнить экспорт поддона и чертежей">
            <Button variant="ghost" onClick={openExportSetup} disabled={!project || exporting !== null}>
              <FolderOutput className="header-icon header-icon--folder-output" size={16} aria-hidden="true" /> Экспорт…
            </Button>
          </Tooltip>
        </nav>
        {updateDismissed && ["available", "ready", "failed"].includes(update.state) ? (
          <Tooltip content="Открыть окно с доступным обновлением">
            <button type="button" className="secondary" onClick={() => setUpdateDismissed(false)}>Доступно обновление</button>
          </Tooltip>
        ) : null}
        <Tooltip content="Открыть настройки программы, 3D-вида и шаблонов CAD" className="app-settings-button">
          <Button variant="ghost" onClick={() => { setSettingsInitialSection("general"); setSettingsOpen(true); }} disabled={!status}><Settings className="header-icon header-icon--settings" size={16} aria-hidden="true" /> Настройки</Button>
        </Tooltip>
      </header>
      {settingsOpen ? <SettingsDialog version={status?.version} settings={settings} solidworks={solidWorksOptions} initialSection={settingsInitialSection} update={update} lastUpdateCheck={lastUpdateCheck} onCheckUpdates={() => checkForUpdates(true)} onClose={closeSettings} onSave={saveApplicationSettings} /> : null}
      {resetOpen ? <ResetDialog onClose={closeReset} onConfirm={resetProject} /> : null}
      <div ref={workspaceRef} className={`workspace${viewportExpanded ? " is-viewport-expanded" : ""}${viewportTransition !== "none" ? ` is-viewport-${viewportTransition}` : ""}`}>
        <aside ref={editorPanelRef} className="editor-panel" aria-label="Редактор поддона" aria-hidden={viewportExpanded} inert={viewportExpanded}>
          <div className="editor-heading">
            <h1>Редактор</h1>
            <p>Выберите сечение брусьев, введите расстояния между опорами, габаритами и отступы.</p>
          </div>
          {recoveryNotice ? <p className="recovery-notice" role="alert">{recoveryNotice}</p> : null}
          {stepRestoreError ? <p className="error" role="alert">{stepRestoreError}</p> : null}
        {project ? (
          <div className="editor-scroll-frame">
          <div ref={directionsRef} className="directions">
            <section className="layer-stack" aria-label="Слои поддона">
              <div className="layer-stack-heading">
                <h2>Слои поддона</h2>
                <div className="layer-toolbar" role="toolbar" aria-label="Инструменты слоёв">
                  <Tooltip content="Создать копию выбранного слоя">
                    <button type="button" className="ui-button--ghost" aria-label="Дублировать слой" disabled={!selectedLayerId || duplicateBusy} onClick={() => void duplicateLayer()}>
                      <Copy size={16} />
                    </button>
                  </Tooltip>
                  <Tooltip content={selectedLayerId && isLocked(selectedLayerId) ? "Разблокировать выбранный слой" : "Заблокировать выбранный слой"}>
                    <button type="button" className="ui-button--ghost" disabled={!selectedLayerId}
                      aria-label={selectedLayerId && isLocked(selectedLayerId) ? "Разблокировать слой" : "Заблокировать слой"}
                      aria-pressed={selectedLayerId ? isLocked(selectedLayerId) : false}
                      onClick={() => {
                        if (selectedLayerId) toggleLayerLock(selectedLayerId);
                      }}>
                      {selectedLayerId && isLocked(selectedLayerId) ? <LockKeyholeOpen size={16} /> : <LockKeyhole size={16} />}
                    </button>
                  </Tooltip>
                  <Tooltip content="Удалить выбранный слой из поддона">
                    <button
                      type="button"
                      className="ui-button--ghost"
                      aria-label="Удалить слой"
                      disabled={!selectedLayerId || project.pallet.layers.length <= 2 || isLocked(selectedLayerId)}
                      onClick={() => {
                        if (selectedLayerId) removeLayer(selectedLayerId);
                      }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </Tooltip>
                </div>
              </div>
              <Tooltip content="Добавить новый слой поверх остальных слоёв поддона" className="ui-tooltip-trigger--full">
                <button type="button" className="secondary layer-add-button" onClick={addLayer}>
                  <Plus size={24} /> Добавить новый слой
                </button>
              </Tooltip>
              <div className="layer-stack-list">
              {(() => {
                const reversed = [...project.pallet.layers].reverse();
                const displayLayers = (() => {
                  if (!draggedLayer) return reversed;
                  const source = reversed.find((item) => item.id === draggedLayer.id);
                  if (!source) return reversed;
                  const rest = reversed.filter((item) => item.id !== draggedLayer.id);
                  rest.splice(Math.max(0, Math.min(rest.length, draggedLayer.targetIndex)), 0, source);
                  return rest;
                })();
                return displayLayers.map((layer) => {
                  const index = project.pallet.layers.findIndex((item) => item.id === layer.id);
                  const isFloatingDragged = draggedLayer?.id === layer.id;
                  const cardNode = (
                    <section
                      ref={(node) => {
                        if (isFloatingDragged) {
                          floatingLayerRef.current = node;
                        } else if (node) {
                          layerCardRefs.current.set(layer.id, node);
                        } else {
                          layerCardRefs.current.delete(layer.id);
                        }
                      }}
                      className={`layer-card${selectedLayerId === layer.id ? " is-selected" : ""}${isLocked(layer.id) ? " is-locked" : ""}${hiddenLayerIds.includes(layer.id) ? " is-hidden" : ""}${expandedLayerId === layer.id ? " is-expanded" : ""}${isFloatingDragged ? " is-dragging-floating" : ""}`}
                      key={layer.id}
                      style={isFloatingDragged && draggedLayer ? {
                        left: draggedLayer.left,
                        top: draggedLayer.top,
                        width: draggedLayer.width,
                        height: draggedLayer.height,
                      } : undefined}
                      onClick={() => setSelectedLayerId(layer.id)}
                    >
                      <div className="layer-card-header">
                        <span
                          className="layer-drag-handle"
                          role="button"
                          tabIndex={-1}
                          aria-label={`Перетащить слой ${layerNumber(layer, index)}`}
                          onPointerDown={(event) => startLayerDrag(event, layer.id)}
                        >
                          <GripVertical size={24} />
                        </span>
                    <button
                      type="button"
                      className="layer-toggle"
                      aria-expanded={expandedLayerId === layer.id}
                      onClick={() =>
                        setExpandedLayerId((current) => current === layer.id ? null : layer.id)
                      }
                    >
                      <span>Слой {layerNumber(layer, index)}{isLocked(layer.id) ? <span className="sr-only"> · Заблокирован</span> : null}</span>
                      <small>{layer.axis === "length" ? "Продольный" : "Поперечный"}{calculation?.snapshot?.pallet ? ` • ${calculation.snapshot.pallet.beams.filter((beam) => (beam.physicalLayerId ?? beam.layerId) === layer.id).length} шт` : ""}</small>
                    </button>
                    {isLocked(layer.id) ? (
                      <Tooltip content="Разрешить редактирование слоя">
                        <button
                          type="button"
                          className="layer-lock-indicator"
                          aria-label={`Разблокировать слой ${layerNumber(layer, index)}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            toggleLayerLock(layer.id);
                          }}>
                          <LockKeyhole size={16} aria-hidden="true" />
                        </button>
                      </Tooltip>
                    ) : null}
                    <Tooltip content={hiddenLayerIds.includes(layer.id) ? "Показать слой в области просмотра" : "Скрыть слой в области просмотра"}>
                      <button
                        type="button"
                        className="layer-visibility"
                        aria-label={hiddenLayerIds.includes(layer.id) ? `Показать слой ${layerNumber(layer, index)}` : `Скрыть слой ${layerNumber(layer, index)}`}
                        onClick={() => toggleLayerVisibility(layer.id)}
                        aria-pressed={hiddenLayerIds.includes(layer.id)}
                      >
                        {hiddenLayerIds.includes(layer.id) ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                    </Tooltip>
                    <Tooltip content={expandedLayerId === layer.id ? "Свернуть параметры слоя" : "Развернуть параметры слоя"}>
                      <button type="button" className="layer-expand" aria-label={`${expandedLayerId === layer.id ? "Свернуть" : "Развернуть"} слой ${layerNumber(layer, index)}`}
                        aria-expanded={expandedLayerId === layer.id} onClick={() => setExpandedLayerId((current) => current === layer.id ? null : layer.id)}>
                        <ChevronDown size={16} aria-hidden="true" />
                      </button>
                    </Tooltip>
                  </div>
                  {expandedLayerId === layer.id ? (
                    <fieldset className="layer-card-content" disabled={isLocked(layer.id)}>
                      <div className="layer-direction-field layer-field-wide">
                        <span>Расположение брусьев</span>
                        <SegmentedControl label={`Расположение брусьев слоя ${layerNumber(layer, index)}`} value={layer.axis}
                          options={[{ value: "length", label: "Продольные" }, { value: "width", label: "Поперечные" }]}
                          disabled={isLocked(layer.id)} onChange={(axis) => updateLayerAxis(index, axis)} />
                      </div>
                      <label className="layer-field-wide">
                        Сечение брусьев (по умолчанию)
                        <Combobox
                          value={layerSectionPreset(layer)}
                          disabled={isLocked(layer.id)}
                          options={SECTION_PRESETS.map((preset) => ({ value: preset.id, label: preset.label }))}
                          onChange={(presetId) => {
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
                        />
                      </label>
                      <div className="layer-section-dimensions">
                        <label>
                          Ширина
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
                          <span className="layer-dimension-unit" aria-hidden="true">мм</span>
                        </label>
                        <label>
                          Высота
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
                          <span className="layer-dimension-unit" aria-hidden="true">мм</span>
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
                      <p className="layer-input-hint layer-field-wide"><Info size={16} aria-hidden="true" /> Введите расстояния в миллиметрах через пробел</p>
                    </fieldset>
                  ) : null}
                </section>
                  );
                  if (isFloatingDragged && draggedLayer) {
                    return (
                      <div key={layer.id} ref={layerPlaceholderRef} className="layer-card-placeholder"
                        style={{ height: draggedLayer.height }} aria-hidden="true">
                        {createPortal(cardNode, document.body)}
                      </div>
                    );
                  }
                  return cardNode;
                });
              })()}
              </div>
            </section>
              {project ? <fieldset className="pallet-margins">
                <h2>Отступы поддона</h2>
                <p>Введите отступы от краёв поддона до размещаемого объекта</p>
                {MARGIN_PAIRS.flatMap(({ first, second, labels }) => [first, second].map((index, position) =>
                  <label key={index}>{labels[position].replace(", мм", "")}
                    <input type="number" min="0" value={marginDrafts[index] ?? palletMargins(project)[index]}
                      onFocus={() => { beginFormEdit(); setMarginDrafts((drafts) => ({ ...drafts, [index]: String(palletMargins(project)[index]) })); }}
                      onBlur={() => { setMarginDrafts((drafts) => { const next = { ...drafts }; delete next[index]; return next; }); finishFormEdit(); }}
                      onChange={(event) => { setMarginDrafts((drafts) => ({ ...drafts, [index]: event.target.value })); updatePalletMargin(index, event.target.value); }} />
                    <span className="pallet-margin-unit" aria-hidden="true">мм</span>
                  </label>))}
              </fieldset> : null}
              <fieldset className="rounding">
                <h2>Округление габаритов поддона</h2>
                <p>Выберите, до какого значения округлять габариты поддона.</p>
                <SegmentedControl label="Округление габаритов поддона" value={rounding}
                  options={[{ value: "50", label: "До 50 мм" }, { value: "5", label: "До 5 мм" }, { value: "none", label: "Не округлять" }]}
                  onChange={setRounding} />
              </fieldset>
              <div className="layer-stack-footer">
                <p><Info size={16} aria-hidden="true" /> Все размеры указаны в миллиметрах</p>
                <Tooltip content="Вернуть конфигурацию поддона к параметрам по умолчанию" side="top">
                  <button type="button" className="ui-button--tertiary" onClick={() => setResetOpen(true)}>
                    Сбросить конфигурацию
                  </button>
                </Tooltip>
              </div>
          </div>
          <Scrollbar orientation="vertical" targetRef={directionsRef} ariaLabel="Прокрутка редактора" />
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
                stepModelGeneration={stepModelGeneration}
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
                dimensionsVisible={project?.view.show_length_dimensions ?? true}
                gridVisible={project?.view.show_grid ?? true}
                onDimensionsVisibleChange={(value) => { if (project) updateProject({ ...project, view: { ...project.view, show_length_dimensions: value, show_width_dimensions: value } }); }}
                onGridVisibleChange={(value) => { if (project) updateProject({ ...project, view: { ...project.view, show_grid: value } }); }}
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
                manualSection={manualBeamSection}
                manualReference={manualReference ? { beam: manualReference, face: manualReferenceFace } : null}
                manualSecondReference={manualReferenceMode === "between" ? manualSecondReference : null}
                manualBetweenMode={manualReferenceMode === "between"}
                manualDistance={manualDistance}
                manualHud={manualHud}
                dimensionHud={dimensionHud}
                sectionHud={sectionHud}
                toolbar={viewportToolbar}
                fitViewControl={
                  <Tooltip content="Поместить поддон и модель целиком в центр кадра" side="top">
                    <button
                      type="button"
                      className="secondary viewport-fit-action"
                      aria-label="Вписать поддон в область просмотра"
                      onClick={() => setFitRequest((value) => value + 1)}
                    >
                      <ScanSquare size={16} aria-hidden="true" />
                      <ExpandableLabel text="Вписать" expanded={viewportExpanded} animate={false} />
                    </button>
                  </Tooltip>
                }
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
                        : (manualReferenceMode === "face" && !manualReference) || (manualReferenceMode === "between" && (!manualReference || !manualSecondReference))
                          ? `Выберите ${manualReferenceMode === "between" ? (manualReference ? "вторую" : "первую") : "боковую"} грань для отсчёта\nПКМ — отменить последний выбор`
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
                toolHintCanExit={insertionMode || beamTool !== "none" || dimensionEditing}
                toolErrorVersion={viewportToolErrorVersion}
                onFirstFrame={reportFirstViewportFrame}
                visibleRightInset={visibleRightInset}
                visibleBottomInset={visibleBottomInset}
                animateInsets={viewportTransition !== "none"}
                insetsExpanding={viewportExpanded}
                insetsDurationMs={viewportExpanded ? 340 : 420}
                onUndoToolSelection={
                  (!stepPalletBuilt && !buildingStepPallet && stepModel !== null) || insertionMode || beamTool !== "none" || dimensionEditing
                    ? undoLastToolSelection
                    : undefined
                }
                beamSelectionEnabled={insertionMode || beamTool !== "none"}
              />
            </Suspense>
            <div ref={summaryTransitionRef} className="pallet-summary-transition" aria-hidden={viewportExpanded} inert={viewportExpanded}>
              <PalletSummary size={calculation.snapshot.pallet.size} mass={calculation.snapshot.pallet.massKg}
                details={palletDetails(calculation.snapshot.pallet.beams)} millimetres={formatMillimetres} kilograms={formatKilograms} />
            </div>
          </>
        ) : null}
        </section>
      </div>
      {!settingsOpen && !updateDismissed && ["available", "downloading", "ready", "failed", "installing"].includes(update.state) ? (
        <div className="modal-backdrop">
          <section className="modal progress-modal" role="dialog" aria-modal="true" aria-labelledby="update-title" aria-live="polite">
            <h2 id="update-title">Обновление PalletLab</h2>
            {update.state === "available" ? <p>Доступна версия {update.version}.{update.manualOnly ? " Для этой версии приложения скачайте обновление вручную со страницы релизов." : ""}</p> : null}
            {update.state === "downloading" ? <>
              <ProgressIndicator label="Скачивание и проверка обновления…" value={update.total ? update.received ?? 0 : undefined} max={update.total || 100} />
            </> : null}
            {update.state === "ready" ? <>
              <p>Версия {update.version} готова к установке. Приложение закроется.</p>
              {hasUnsavedChanges ? <p>Несохранённые изменения могут быть потеряны. Вы можете сохранить проект перед установкой.</p> : null}
            </> : null}
            {update.state === "installing" ? <p>Запускается установка обновления…</p> : null}
            {update.error ? <p className="error">{update.error}</p> : null}
            <footer className="modal-actions">
              {update.state !== "downloading" && update.state !== "installing" ? <button type="button" className="secondary" onClick={() => setUpdateDismissed(true)}>Позже</button> : null}
              {(update.state === "available" && !update.manualOnly) || update.state === "failed" ? <button type="button" onClick={() => void window.pywebview?.api?.download_update().then(setUpdate)}>Скачать</button> : null}
              {update.state === "ready" && hasUnsavedChanges ? <button type="button" disabled={saving} onClick={() => void saveProject()}>Сохранить проект</button> : null}
              {update.state === "ready" ? <button type="button" disabled={saving} onClick={() => void window.pywebview?.api?.install_update().then(setUpdate)}>{hasUnsavedChanges ? "Установить без сохранения" : "Установить"}</button> : null}
            </footer>
          </section>
        </div>
      ) : null}
      {exportSetupOpen ? createPortal(
        <div className="modal-backdrop" role="presentation">
          <section ref={exportDialog} tabIndex={-1} className="modal export-modal" role="dialog" aria-modal="true" aria-labelledby="export-title">
            <header className="export-header"><h2 id="export-title">Экспорт поддона</h2><Button variant="ghost" aria-label="Закрыть экспорт" onClick={() => setExportSetupOpen(false)}><X size={16} aria-hidden="true" /></Button></header>
            <div className="export-cad-field"><span>CAD-система</span>
              <SegmentedControl label="CAD-система" value={exportCadSystem} options={[{ value: "solidworks", label: "SolidWorks" }, { value: "kompas", label: "КОМПАС-3D" }]} onChange={setExportCadSystem} />
            </div>
            <fieldset className="export-options">
              <legend>Что экспортируем</legend>
              <div className="export-checkboxes">
              <div className="export-option-group">
              <label className="export-checkbox">
                <Checkbox
                  checked={includePalletModel}
                  disabled={!includePartModels}
                  onChange={(event) => changePalletModel(event.target.checked)}
                />
                Модель поддона
              </label>
              <label className="export-checkbox">
                <Checkbox
                  checked={includePartModels}
                  onChange={(event) => changePartModels(event.target.checked)}
                />
                Модели деталей
              </label>
              </div>
              <div className="export-option-group">
              <label className="export-checkbox">
                <Checkbox
                  checked={includePalletDrawing}
                  disabled={!includePartModels || !includePalletModel}
                  onChange={(event) => setIncludePalletDrawing(event.target.checked)}
                />
                Чертёж поддона
              </label>
              <label className="export-checkbox">
                <Checkbox
                  checked={includePartDrawings}
                  disabled={!includePartModels}
                  onChange={(event) => setIncludePartDrawings(event.target.checked)}
                />
                Чертежи деталей
              </label>
              </div>
              {hasBuiltStepModel ? (
                <div className="export-option-group">
                <label className="export-checkbox">
                  <Checkbox
                    checked={includeExportModel}
                    disabled={!includePartModels || !includePalletModel}
                    onChange={(event) => {
                      setIncludeExportModel(event.target.checked);
                      if (!event.target.checked) setIncludePackagingDrawing(false);
                    }}
                  />
                  Модель упаковки
                </label>
                <label className="export-checkbox">
                  <Checkbox
                    checked={includePackagingDrawing}
                    disabled={
                      !includeExportModel
                      || !includePartModels
                      || !includePalletModel
                    }
                    onChange={(event) => setIncludePackagingDrawing(event.target.checked)}
                  />
                  Упаковочный чертёж
                </label>
                </div>
              ) : null}
              </div>
              {hasBuiltStepModel && includeExportModel && exportCadSystem === "solidworks" ? (
                <p className="modal-hint">Если SolidWorks не сможет прочитать исходный STEP, будет создана совместимая копия геометрии. Имена и цвета компонентов могут не сохраниться; копия может быть значительно больше оригинала и потребовать много памяти при импорте. Исходный STEP останется в папке экспорта.</p>
              ) : null}
            </fieldset>
            <label className="file-field export-directory-field">
              Путь сохранения (по умолчанию сохранение на рабочий стол)
              <div className="file-field-control">
                <input
                  type="text"
                  value={exportDirectory}
                  placeholder="Путь к папке экспорта"
                  aria-label="Путь сохранения экспорта"
                  onChange={(event) => {
                    setExportDirectory(event.target.value);
                    setExportDirectoryError(null);
                  }}
                />
                <Button variant="secondary" onClick={() => void browseExportDirectory()}>
                  Обзор
                </Button>
              </div>
            </label>
            {exportDirectoryError ? <p className="error" role="alert">{exportDirectoryError}</p> : null}
            <footer className="modal-actions">
              <Button variant="secondary" onClick={() => setExportSetupOpen(false)}>Отменить</Button>
              <Button
                disabled={!includePartModels || !exportDirectory.trim() || exporting !== null}
                onClick={() => void exportCad()}
              >
                Экспортировать
              </Button>
            </footer>
          </section>
        </div>, document.body
      ) : null}
      {exporting ? (
        <div className="modal-backdrop" role="presentation">
          <section className="modal progress-modal" role="dialog" aria-modal="true" aria-live="polite" aria-labelledby="export-progress-title">
            <header className="progress-header">
              <h2 id="export-progress-title">Экспорт поддона</h2>
              <Button variant="ghost" aria-label="Отменить экспорт" disabled={exportCancelling} onClick={requestCancelExport}>
                <X size={16} aria-hidden="true" />
              </Button>
            </header>
            <ProgressIndicator
              label={
                exportCancelling
                  ? "Отменяем экспорт…"
                  : exportStage === "drawings"
                    ? "Создание чертежей..."
                    : exporting === "solidworks"
                      ? includeExportModel
                        ? "SolidWorks импортирует STEP-модель и формирует упаковочную сборку..."
                        : "SolidWorks создаёт модели..."
                      : includeExportModel
                        ? "КОМПАС-3D импортирует STEP-модель и формирует упаковочную сборку..."
                        : "КОМПАС-3D создаёт модели..."
              }
            />
            <footer className="modal-actions">
              <Button variant="secondary" disabled={exportCancelling} onClick={requestCancelExport}>
                {exportCancelling ? "Отменяем…" : "Отменить"}
              </Button>
            </footer>
          </section>
        </div>
      ) : null}
      {exportResult ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal result-modal"
            role={exportResult.ok ? "dialog" : "alertdialog"}
            aria-modal="true"
            aria-labelledby="export-result-title"
          >
            <header className="result-header">
              <h2 id="export-result-title">{exportResult.ok ? "Экспорт поддона завершён" : "Ошибка экспорта"}</h2>
              <Button variant="ghost" aria-label="Закрыть" onClick={() => setExportResult(null)}>
                <X size={16} aria-hidden="true" />
              </Button>
            </header>
            <MessageBox
              variant={exportResult.ok ? "success" : "error"}
              title={exportResult.ok ? "Экспорт успешно завершён" : "Не удалось экспортировать поддон"}
              text={exportResult.message}
            />
            <footer className="modal-actions">
              <Button onClick={() => setExportResult(null)}>
                {exportResult.ok ? "Хорошо, продолжить!" : "Закрыть"}
              </Button>
            </footer>
          </section>
        </div>
      ) : null}
      {stepImport && stepImportPhase(stepImport.state, stepModel !== null, stepRestoreError !== null) ? (
        <div className="modal-backdrop" role="presentation">
          <section className="modal progress-modal" role="dialog" aria-modal="true" aria-live="polite" aria-labelledby="step-import-title">
            <header className="progress-header">
              <h2 id="step-import-title">Импорт модели</h2>
              <Button variant="ghost" aria-label="Отменить импорт" disabled={stepImport.state === "cancelling"} onClick={() => void cancelStepImport()}>
                <X size={16} aria-hidden="true" />
              </Button>
            </header>
            <ProgressIndicator
              label={stepImport.state === "completed" ? "Подготавливаем модель..." : stepImport.label ?? "Подготавливаем STEP-модель…"}
              value={stepImport.state === "running" && stepImport.phase === "faces" ? stepImport.phaseProgress ?? undefined : undefined}
            />
          </section>
        </div>
      ) : null}
      {historyReadErrorOpen ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal result-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="history-read-error-title"
            aria-describedby="history-read-error-message"
          >
            <h2 id="history-read-error-title">История изменений недоступна</h2>
            <p id="history-read-error-message" className="error">
              Не удалось прочитать историю изменений. Проект открыт без истории Undo/Redo.
            </p>
            <footer className="modal-actions">
              <button type="button" onClick={() => setHistoryReadErrorOpen(false)}>Понятно</button>
            </footer>
          </section>
        </div>
      ) : null}
    </main>
    </TooltipProvider>
  );
}
