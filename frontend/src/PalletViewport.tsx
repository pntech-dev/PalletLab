// Import only the helpers used by the viewport. The package entrypoint also
// re-exports optional tooling that is irrelevant to a pallet preview.
import { OrbitControls } from "@react-three/drei/core/OrbitControls";
import { Line } from "@react-three/drei/core/Line";
import { Html } from "@react-three/drei/web/Html";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  CanvasTexture,
  LinearFilter,
  MathUtils,
  PerspectiveCamera,
  Vector3,
} from "three";
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import type { StepModelGeometry as StepModelSnapshot } from "./stepModelGeometry";
import SceneSettings from "./SceneSettings";
import { Tooltip } from "./design/Tooltip";
import { BadgeAlert, Minus, Mouse, MouseLeft, MouseRight, Plus, X } from "lucide-react";
import { ViewportTip } from "./design/ViewportTip";
import { placeViewportHint, type Rect } from "./viewportHintPlacement";
import { betweenFaces } from "./manualBeamBetween";
export type { StepModelGeometry as StepModelSnapshot } from "./stepModelGeometry";

const StepModelViewport = lazy(() => import("./StepModelViewport"));

const DEFAULT_MODEL_TRANSPARENCY = 80;

export type ViewportBeam = {
  index: number;
  layerId: string;
  physicalLayerId: string;
  layerIndex: number;
  orientation: string;
  center: [number, number, number];
  size: [number, number, number];
};
export type ViewportPoint = [number, number, number];
export type ViewportFaceNormal = [number, number, number];
export type CameraPreset = "isometric" | "top" | "front" | "side";
export type ViewportDimension = {
  layerId: string;
  axis: "length" | "width";
  index: number;
  editValue: number | null;
  editable: boolean;
  value: number;
  start: [number, number, number];
  end: [number, number, number];
  startExtension: [number, number, number] | null;
  endExtension: [number, number, number] | null;
};
export type ViewportInsertionMarker = {
  slot: {
    axis: "length" | "width";
    layerId: string;
    afterBeamIndex: number;
    maximumClearGap: number;
    suggestedClearGap: number;
  };
  center: [number, number, number];
  size: number;
  preview: { center: [number, number, number]; size: [number, number, number] };
};
type ManualBeamSection = { height: number; width: number };
type BeamReferenceFace = "x_min" | "x_max" | "y_min" | "y_max";
type ManualReference = { beam: ViewportBeam; face: BeamReferenceFace };

function DirectionCompassUpdater({ compass }: { compass: RefObject<SVGSVGElement | null> }) {
  const direction = useMemo(() => new Vector3(), []);
  useFrame(({ camera }) => {
    const axes = [
      ["x", 1, 0, 0],
      ["y", 0, 0, 1],
      ["z", 0, 1, 0],
    ] as const;
    for (const [name, x, y, z] of axes) {
      direction.set(x, y, z).applyQuaternion(camera.quaternion.clone().invert());
      const endX = 40 + direction.x * 25;
      const endY = 40 - direction.y * 25;
      const line = compass.current?.querySelector(`[data-axis-line="${name}"]`);
      const label = compass.current?.querySelector(`[data-axis-label="${name}"]`);
      line?.setAttribute("x2", String(endX));
      line?.setAttribute("y2", String(endY));
      label?.setAttribute("x", String(40 + direction.x * 33));
      label?.setAttribute("y", String(40 - direction.y * 33));
    }
  });
  return null;
}

function CameraZoom({ command, fitRequest, presetRequest, onChange }: {
  command: RefObject<((factor: number) => void) | null>;
  fitRequest: number;
  presetRequest: number;
  onChange: (value: number) => void;
}) {
  const { camera, controls, invalidate } = useThree();
  const referenceDistance = useRef<number | null>(null);
  const lastPercent = useRef<number | null>(null);
  const orbit = controls as { target: Vector3; update: () => void } | null;
  useEffect(() => {
    referenceDistance.current = null;
    invalidate();
  }, [fitRequest, presetRequest, invalidate]);
  useEffect(() => {
    if (!orbit) return;
    command.current = (factor) => {
      const offset = camera.position.clone().sub(orbit.target);
      const nextDistance = Math.max(0.05, Math.min(10000, offset.length() * factor));
      if (offset.lengthSq() === 0) return;
      camera.position.copy(orbit.target).add(offset.setLength(nextDistance));
      orbit.update();
      invalidate();
    };
    return () => { command.current = null; };
  }, [camera, orbit, command, invalidate]);
  useFrame(() => {
    if (!orbit) return;
    const distance = camera.position.distanceTo(orbit.target);
    if (distance <= 0) return;
    referenceDistance.current ??= distance;
    const percent = Math.round(referenceDistance.current / distance * 100);
    if (percent !== lastPercent.current) {
      lastPercent.current = percent;
      onChange(percent);
    }
  });
  return null;
}

function FirstFrameReporter({ onFirstFrame }: { onFirstFrame?: () => void }) {
  const reported = useRef(false);
  useFrame(() => {
    if (reported.current) return;
    reported.current = true;
    onFirstFrame?.();
  });
  return null;
}

function springProgress(raw: number, durationSeconds: number, stiffness: number, damping: number): number {
  if (raw <= 0) return 0;
  if (raw >= 1) return 1;
  const t = raw * durationSeconds;
  const w0 = Math.sqrt(stiffness);
  const zeta = damping / (2 * w0);
  if (zeta >= 1) {
    return 1 - (1 + w0 * t) * Math.exp(-w0 * t);
  }
  const wd = w0 * Math.sqrt(1 - zeta * zeta);
  return 1 - Math.exp(-zeta * w0 * t) * (Math.cos(wd * t) + ((zeta * w0) / wd) * Math.sin(wd * t));
}

function ViewOffsetAnimator({
  rightInset,
  bottomInset,
  animate,
  expanding,
  durationMs,
}: {
  rightInset: number;
  bottomInset: number;
  animate: boolean;
  expanding: boolean;
  durationMs: number;
}) {
  const { camera, size, invalidate } = useThree();
  const current = useRef<{ x: number; y: number } | null>(null);
  const start = useRef({ x: 0, y: 0 });
  const target = useRef({ x: 0, y: 0 });
  const startedAt = useRef<number | null>(null);

  const applyOffset = useCallback((right: number, bottom: number) => {
    const perspective = camera as PerspectiveCamera;
    if (size.width <= 0 || size.height <= 0) return;
    if (Math.abs(right) < 0.25 && Math.abs(bottom) < 0.25) {
      if (perspective.view?.enabled) perspective.clearViewOffset();
    } else {
      perspective.setViewOffset(size.width, size.height, right / 2, bottom / 2, size.width, size.height);
    }
  }, [camera, size.height, size.width]);

  useLayoutEffect(() => {
    if (size.width <= 0 || size.height <= 0) return;
    if (current.current === null || !animate) {
      current.current = { x: rightInset, y: bottomInset };
      target.current = { x: rightInset, y: bottomInset };
      startedAt.current = null;
      applyOffset(rightInset, bottomInset);
      invalidate();
      return;
    }
    start.current = { ...current.current };
    target.current = { x: rightInset, y: bottomInset };
    startedAt.current = performance.now();
    invalidate();
  }, [animate, applyOffset, bottomInset, invalidate, rightInset, size.height, size.width]);

  useFrame(() => {
    if (startedAt.current === null) return;
    const elapsed = performance.now() - startedAt.current;
    const raw = Math.min(1, elapsed / durationMs);
    const eased = expanding
      ? 1 - Math.pow(1 - raw, 3)
      : springProgress(raw, durationMs / 1000, 300, 22);
    const x = start.current.x + (target.current.x - start.current.x) * eased;
    const y = start.current.y + (target.current.y - start.current.y) * eased;
    current.current = { x, y };
    applyOffset(x, y);
    if (raw >= 1) {
      startedAt.current = null;
      current.current = { ...target.current };
      applyOffset(target.current.x, target.current.y);
      return;
    }
    invalidate();
  });
  return null;
}

function transformedStepBounds(model: StepModelSnapshot): [ViewportPoint, ViewportPoint] {
  const [xMin, xMax, yMin, yMax, zMin, zMax] = model.bounds;
  const matrix = model.transform;
  const minimum: ViewportPoint = [Infinity, Infinity, Infinity];
  const maximum: ViewportPoint = [-Infinity, -Infinity, -Infinity];
  for (const x of [xMin, xMax]) for (const y of [yMin, yMax]) for (const z of [zMin, zMax]) {
    const sourceX = x / 1000;
    const sourceY = z / 1000;
    const sourceZ = y / 1000;
    const reciprocalW = 1 / (matrix[3] * sourceX + matrix[7] * sourceY + matrix[11] * sourceZ + matrix[15]);
    const point: ViewportPoint = [
      (matrix[0] * sourceX + matrix[4] * sourceY + matrix[8] * sourceZ + matrix[12]) * reciprocalW,
      (matrix[1] * sourceX + matrix[5] * sourceY + matrix[9] * sourceZ + matrix[13]) * reciprocalW,
      (matrix[2] * sourceX + matrix[6] * sourceY + matrix[10] * sourceZ + matrix[14]) * reciprocalW,
    ];
    minimum[0] = Math.min(minimum[0], point[0]);
    minimum[1] = Math.min(minimum[1], point[1]);
    minimum[2] = Math.min(minimum[2], point[2]);
    maximum[0] = Math.max(maximum[0], point[0]);
    maximum[1] = Math.max(maximum[1], point[1]);
    maximum[2] = Math.max(maximum[2], point[2]);
  }
  return [minimum, maximum];
}

function point([x, y, z]: [number, number, number]): [number, number, number] {
  return [x / 1000, z / 1000, y / 1000];
}

type ViewportBounds = {
  center: [number, number, number];
  span: number;
  min: [number, number, number];
  max: [number, number, number];
};

function ViewportOrbitControls({ bounds }: { bounds: ViewportBounds }) {
  const canvas = useThree((state) => state.gl.domElement);
  return <OrbitControls makeDefault domElement={canvas} target={bounds.center} minPolarAngle={0.03} maxPolarAngle={Math.PI - 0.03} />;
}

function Camera({
  preset,
  presetRequest,
  bounds,
}: {
  preset: CameraPreset;
  presetRequest: number;
  bounds: ViewportBounds;
}) {
  const { camera } = useThree();
  useEffect(() => {
    const [x, y, z] = bounds.center;
    const distance = Math.max(3, bounds.span * 1.45);
    const positions: Record<CameraPreset, [number, number, number]> = {
      // A slightly closer default makes the pallet easier to inspect without
      // sacrificing the breathing room needed for dimensions.
      isometric: [x + distance * 0.9, y + distance * 0.675, z + distance * 0.9],
      // Do not place the camera exactly at the orbit pole. At the pole an
      // orbit has no horizontal direction, so a left-drag can appear locked to
      // one axis. This remains visually a top view while preserving full orbit.
      top: [x, y + distance * 1.35, z + distance * 0.08],
      // Keep the eye level with the pallet centre for a true end elevation.
      // The frontend's mapped axes put the longitudinal view on world Z.
      front: [x, y, z + distance],
      side: [x + distance, y, z],
    };
    if (preset === "top") camera.up.set(0, 0, -1);
    else camera.up.set(0, 1, 0);
    camera.position.set(...positions[preset]);
    camera.lookAt(x, y, z);
    // Recalculation changes pallet bounds after every editor command. Do not
    // treat that as a camera command: retain the user's current orbit until a
    // preset is explicitly selected.
  }, [camera, preset, presetRequest]);
  return null;
}

function FitCamera({
  fitRequest,
  bounds,
  visibleRightInset,
  visibleBottomInset,
}: {
  fitRequest: number;
  bounds: ViewportBounds;
  visibleRightInset: number;
  visibleBottomInset: number;
}) {
  const { camera, size } = useThree();
  const previousRequest = useRef<number | null>(null);
  const latestSize = useRef(size);
  latestSize.current = size;
  const latestInsets = useRef({ right: visibleRightInset, bottom: visibleBottomInset });
  latestInsets.current = { right: visibleRightInset, bottom: visibleBottomInset };
  const sizeReady = size.width > 0 && size.height > 0;

  useEffect(() => {
    const currentSize = latestSize.current;
    if (!sizeReady || currentSize.width <= 0 || currentSize.height <= 0) return;
    const requestedExplicitly = fitRequest !== previousRequest.current;
    previousRequest.current = fitRequest;

    const visibleWidth = Math.max(1, currentSize.width - latestInsets.current.right);
    const visibleHeight = Math.max(1, currentSize.height - latestInsets.current.bottom);
    const perspective = camera as PerspectiveCamera;
    const fullVerticalFov = MathUtils.degToRad(perspective.fov);
    const verticalFov = 2 * Math.atan(
      Math.tan(fullVerticalFov / 2) * (visibleHeight / Math.max(1, currentSize.height)),
    );
    const horizontalFov = 2 * Math.atan(
      Math.tan(fullVerticalFov / 2) * (visibleWidth / Math.max(1, currentSize.height)),
    );
    const direction = new Vector3();
    camera.getWorldDirection(direction);
    const right = new Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
    const up = new Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
    const target = new Vector3(...bounds.center);
    const horizontalTangent = Math.tan(horizontalFov / 2);
    const verticalTangent = Math.tan(verticalFov / 2);
    let distance = 0;
    for (const x of [bounds.min[0], bounds.max[0]]) {
      for (const y of [bounds.min[1], bounds.max[1]]) {
        for (const z of [bounds.min[2], bounds.max[2]]) {
          const offset = new Vector3(x, y, z).sub(target);
          const depthOffset = offset.dot(direction);
          distance = Math.max(
            distance,
            Math.abs(offset.dot(right)) / horizontalTangent - depthOffset,
            Math.abs(offset.dot(up)) / verticalTangent - depthOffset,
          );
        }
      }
    }
    // Keep only a small edge margin; the fit should fill the available view.
    distance = Math.max(0.3, distance * 1.04);
    // An explicit command always recentres the viewport. During ordinary
    // recalculation, however, retain the user's direction and only pull back
    // when the new model no longer fits in the current frame.
    if (!requestedExplicitly && camera.position.distanceTo(target) >= distance) return;
    camera.position.copy(target.addScaledVector(direction, -distance));
    camera.lookAt(...bounds.center);
  }, [bounds, camera, fitRequest, sizeReady]);

  return null;
}

function DimensionHitArea({
  dimension,
  start,
  end,
  middle,
  onSelect,
  onHover,
}: {
  dimension: ViewportDimension;
  start: [number, number, number];
  end: [number, number, number];
  middle: [number, number, number];
  onSelect: (dimension: ViewportDimension) => void;
  onHover: (dimension: ViewportDimension | null) => void;
}) {
  const length = Math.hypot(
    end[0] - start[0],
    end[1] - start[1],
    end[2] - start[2],
  );
  // Keep the hit target narrower than the 50 mm minimum spacing between
  // dimension lines so neighbouring dimensions cannot capture the same point.
  const size: [number, number, number] =
    dimension.axis === "length" ? [length, 0.04, 0.04] : [0.04, 0.04, length];
  return (
    <mesh
      position={middle}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(dimension);
      }}
      onPointerOver={(event) => {
        event.stopPropagation();
        onHover(dimension);
      }}
      onPointerOut={() => onHover(null)}
    >
      <boxGeometry args={size} />
      <meshBasicMaterial transparent opacity={0} depthWrite={false} />
    </mesh>
  );
}

function DimensionLabel({
  value,
  position,
  dimension,
  canEdit,
  onSelect,
  onHover,
}: {
  value: number;
  position: [number, number, number];
  dimension: ViewportDimension;
  canEdit: boolean;
  onSelect: (dimension: ViewportDimension) => void;
  onHover: (dimension: ViewportDimension | null) => void;
}) {
  const texture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 112;
    canvas.height = 42;
    const context = canvas.getContext("2d");
    if (!context)
      throw new Error("Невозможно создать подписи размеров.");
    context.fillStyle = "rgba(255, 255, 255, 0.76)";
    context.roundRect(2, 2, 108, 38, 6);
    context.fill();
    context.fillStyle = "#183f52";
    context.font = "600 21px system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(value.toFixed(0), 56, 22);
    const result = new CanvasTexture(canvas);
    result.minFilter = LinearFilter;
    return result;
  }, [value]);
  useEffect(() => () => texture.dispose(), [texture]);
  return (
    <sprite
      position={position}
      scale={[0.235, 0.09, 1]}
      renderOrder={10}
      onClick={(event) => {
        event.stopPropagation();
        if (canEdit && dimension.editable) onSelect(dimension);
      }}
      onPointerOver={(event) => {
        if (canEdit && dimension.editable) {
          event.stopPropagation();
          onHover(dimension);
        }
      }}
      onPointerOut={() => onHover(null)}
    >
      <spriteMaterial
        map={texture}
        transparent
        depthTest={false}
        depthWrite={false}
      />
    </sprite>
  );
}

function BeamFaceOverlay({ reference }: { reference: ManualReference }) {
  const { beam, face } = reference;
  const center: ViewportPoint = [beam.center[0] / 1000, beam.center[2] / 1000, beam.center[1] / 1000];
  const sizeX = beam.size[0] / 1000;
  const sizeY = beam.size[2] / 1000;
  const sizeZ = beam.size[1] / 1000;
  const thickness = 0.006;
  const isX = face === "x_min" || face === "x_max";
  const maximum = face === "x_max" || face === "y_max";
  const position: ViewportPoint = isX
    ? [center[0] + (maximum ? 1 : -1) * (sizeX / 2 + thickness / 2), center[1], center[2]]
    : [center[0], center[1], center[2] + (maximum ? 1 : -1) * (sizeZ / 2 + thickness / 2)];
  return (
    <mesh position={position} renderOrder={20}>
      <boxGeometry args={isX ? [thickness, sizeY, sizeZ] : [sizeX, sizeY, thickness]} />
      <meshBasicMaterial color="#e07822" transparent opacity={0.82} depthTest={false} depthWrite={false} />
    </mesh>
  );
}

export default function PalletViewport({
  beams,
  dimensions,
  preset,
  presetRequest,
  fitRequest,
  stepModel,
  stepModelGeneration = 0,
  selectedStepFace,
  onSelectStepFace,
  stepFaceSelectionEnabled = false,
  showPallet = true,
  hiddenLayerIds = [],
  dimensionsVisible, gridVisible, onDimensionsVisibleChange, onGridVisibleChange,
  selectedBeams,
  dimensionEditing,
  hoveredDimension,
  selectedDimension,
  onToggleBeam,
  onSelectDimension,
  onHoverDimension,
  insertionMarkers,
  insertionMode,
  selectedSlot,
  onSelectInsertion,
  manualSupports = [],
    manualSection,
  manualReference,
  manualSecondReference,
  manualBetweenMode = false,
  manualDistance = 0,
  manualHud,
  dimensionHud,
  sectionHud,
  toolbar,
  fitViewControl,
  toolHint,
  toolHintCanExit = false,
  toolError,
  toolErrorVersion = 0,
  onFirstFrame,
  visibleRightInset = 0,
  visibleBottomInset = 0,
  animateInsets = false,
  insetsExpanding = false,
  insetsDurationMs = 400,
  onUndoToolSelection,
  beamSelectionEnabled,
}: {
  beams: ViewportBeam[];
  dimensions: ViewportDimension[];
  preset: CameraPreset;
  presetRequest: number;
    fitRequest: number;
    stepModel?: StepModelSnapshot | null;
    stepModelGeneration?: number;
    selectedStepFace?: number | null;
    onSelectStepFace?: (faceId: number) => void;
    stepFaceSelectionEnabled?: boolean;
    showPallet?: boolean;
  hiddenLayerIds?: string[];
  dimensionsVisible: boolean;
  gridVisible: boolean;
  onDimensionsVisibleChange: (value: boolean) => void;
  onGridVisibleChange: (value: boolean) => void;
  selectedBeams: string[];
  dimensionEditing: boolean;
  hoveredDimension: string | null;
  selectedDimension?: { layerId: string; index: number } | null;
  onToggleBeam: (beam: ViewportBeam, point?: ViewportPoint, normal?: ViewportFaceNormal) => void;
  onSelectDimension: (dimension: ViewportDimension) => void;
  onHoverDimension: (dimension: ViewportDimension | null) => void;
  insertionMarkers: ViewportInsertionMarker[];
  insertionMode: boolean;
  selectedSlot: { layerId: string; afterBeamIndex: number } | null;
  onSelectInsertion: (marker: ViewportInsertionMarker) => void;
  manualSupports?: { beam: ViewportBeam; point: ViewportPoint }[];
    manualSection?: ManualBeamSection;
  manualReference?: ManualReference | null;
  manualSecondReference?: ManualReference | null;
  manualBetweenMode?: boolean;
  manualDistance?: number;
  manualHud?: ReactNode;
  dimensionHud?: ReactNode;
  sectionHud?: ReactNode;
  toolbar?: ReactNode;
  fitViewControl?: ReactNode;
  toolHint?: string | null;
  toolHintCanExit?: boolean;
  toolError?: string | null;
  toolErrorVersion?: number;
  onFirstFrame?: () => void;
  visibleRightInset?: number;
  visibleBottomInset?: number;
  animateInsets?: boolean;
  insetsExpanding?: boolean;
  insetsDurationMs?: number;
  onUndoToolSelection?: () => void;
  beamSelectionEnabled: boolean;
}) {
  const viewportElement = useRef<HTMLDivElement>(null);
  const [navigationButtons, setNavigationButtons] = useState(0);
  const hintElement = useRef<HTMLDivElement>(null);
  const hintCardElement = useRef<HTMLDivElement>(null);
  const cursor = useRef<[number, number] | null>(null);
  const pointerInViewport = useRef(false);
  const layoutDirtyRef = useRef(true);
  const wakeHintRef = useRef<(() => void) | null>(null);
  const visibleInsetsRef = useRef({ right: visibleRightInset, bottom: visibleBottomInset });
  visibleInsetsRef.current = { right: visibleRightInset, bottom: visibleBottomInset };
  const hasHint = Boolean(toolHint);

  useEffect(() => {
    const buttonMask = (button: number) => button === 0 ? 1 : button === 1 ? 4 : button === 2 ? 2 : 0;
    const press = (event: MouseEvent) => {
      if (!(event.target instanceof HTMLCanvasElement) || !viewportElement.current?.contains(event.target)) return;
      setNavigationButtons((buttons) => buttons | buttonMask(event.button));
    };
    const release = (event: MouseEvent) => setNavigationButtons((buttons) => buttons & ~buttonMask(event.button));
    const reset = () => setNavigationButtons(0);
    document.addEventListener("mousedown", press);
    document.addEventListener("mouseup", release);
    document.addEventListener("pointercancel", reset);
    window.addEventListener("blur", reset);
    return () => {
      document.removeEventListener("mousedown", press);
      document.removeEventListener("mouseup", release);
      document.removeEventListener("pointercancel", reset);
      window.removeEventListener("blur", reset);
    };
  }, []);

  const updateViewportPointer = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - box.left;
    const y = event.clientY - box.top;
    const inside =
      x >= 0 &&
      y >= 0 &&
      x <= box.width - visibleInsetsRef.current.right &&
      y <= box.height - visibleInsetsRef.current.bottom;
    const visibilityChanged = pointerInViewport.current !== inside;
    pointerInViewport.current = inside;
    if (inside) {
      cursor.current = [x, y];
    }
    if (inside || visibilityChanged) {
      wakeHintRef.current?.();
    }
  }, []);

  useEffect(() => {
    const hidePointer = () => {
      if (!pointerInViewport.current) return;
      pointerInViewport.current = false;
      wakeHintRef.current?.();
    };
    window.addEventListener("blur", hidePointer);
    document.addEventListener("mouseleave", hidePointer);
    return () => {
      window.removeEventListener("blur", hidePointer);
      document.removeEventListener("mouseleave", hidePointer);
    };
  }, []);

  useLayoutEffect(() => {
    if (!hasHint) {
      wakeHintRef.current = null;
      return;
    }
    let frame = 0;
    let enterFrame1 = 0;
    let enterFrame2 = 0;
    let mountedPaintReady = false;
    let lastVisible = false;
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const spring = {
      x: 0,
      y: 0,
      vx: 0,
      vy: 0,
      initialized: false,
      lastTime: performance.now(),
    };
    let layoutCache: {
      size: { width: number; height: number };
      bounds: Rect;
      obstacles: Rect[];
    } | null = null;
    const posStiffness = 500;
    const posDamping = 50;

    const readLayout = (viewport: HTMLDivElement, card: HTMLDivElement) => {
      if (!layoutDirtyRef.current && layoutCache) return layoutCache;
      layoutDirtyRef.current = false;
      const outer = viewport.getBoundingClientRect();
      const relative = (rect: DOMRect): Rect => ({
        left: rect.left - outer.left,
        top: rect.top - outer.top,
        right: rect.right - outer.left,
        bottom: rect.bottom - outer.top,
      });
      const toolbar = viewport.querySelector<HTMLElement>(".viewport-floating-toolbar")?.getBoundingClientRect();
      const footer = Array.from(
        viewport.querySelectorAll<HTMLElement>(".viewport-fit-control, .viewport-navigation-help"),
        (el) => relative(el.getBoundingClientRect()),
      );
      const bounds: Rect = {
        left: 16,
        top: toolbar ? toolbar.bottom - outer.top + 16 : 16,
        right: outer.width - visibleInsetsRef.current.right - 16,
        bottom: footer.length
          ? Math.min(...footer.map((rect) => rect.top)) - 16
          : outer.height - visibleInsetsRef.current.bottom - 16,
      };
      const obstacles = [
        ...Array.from(
          viewport.querySelectorAll<HTMLElement>(".manual-hud:not([aria-hidden='true']):not([inert]), .viewport-error-toast"),
          (el) => relative(el.getBoundingClientRect()),
        ),
        ...Array.from(
          document.querySelectorAll<HTMLElement>(".ui-combobox-menu[data-in-viewport='true']"),
          (el) => relative(el.getBoundingClientRect()),
        ),
      ];
      layoutCache = {
        size: { width: card.offsetWidth, height: card.offsetHeight },
        bounds,
        obstacles,
      };
      return layoutCache;
    };

    const setCardVisible = (card: HTMLDivElement, visible: boolean) => {
      card.classList.toggle("is-visible", visible);
    };

    const step = (now: number) => {
      frame = 0;
      const viewport = viewportElement.current;
      const layer = hintElement.current;
      const card = hintCardElement.current;
      if (!viewport || !layer || !card) return;

      const elapsed = now - spring.lastTime;
      const dt = elapsed > 100 ? 1 / 60 : Math.min(0.05, Math.max(0.001, elapsed / 1000));
      spring.lastTime = now;

      const isVisible = pointerInViewport.current && cursor.current !== null;
      let settled = true;

      if (isVisible && cursor.current) {
        if (!lastVisible) layoutDirtyRef.current = true;
        const layout = readLayout(viewport, card);
        const [targetX, targetY] = placeViewportHint(cursor.current, layout.size, layout.bounds, layout.obstacles);

        if (reducedMotion || !spring.initialized || (!lastVisible && mountedPaintReady)) {
          spring.x = targetX;
          spring.y = targetY;
          spring.vx = 0;
          spring.vy = 0;
          spring.initialized = true;
        } else {
          const substeps = Math.max(1, Math.ceil(dt * 120));
          const subDt = dt / substeps;
          for (let i = 0; i < substeps; i += 1) {
            const ax = (targetX - spring.x) * posStiffness - spring.vx * posDamping;
            const ay = (targetY - spring.y) * posStiffness - spring.vy * posDamping;
            spring.vx += ax * subDt;
            spring.vy += ay * subDt;
            spring.x += spring.vx * subDt;
            spring.y += spring.vy * subDt;
          }
          settled =
            Math.abs(targetX - spring.x) < 0.1 &&
            Math.abs(targetY - spring.y) < 0.1 &&
            Math.hypot(spring.vx, spring.vy) < 0.5;
          if (settled) {
            spring.x = targetX;
            spring.y = targetY;
            spring.vx = 0;
            spring.vy = 0;
          }
        }
        layer.style.transform = `translate3d(${spring.x.toFixed(2)}px, ${spring.y.toFixed(2)}px, 0)`;
      }

      if (mountedPaintReady && isVisible !== lastVisible) {
        lastVisible = isVisible;
        setCardVisible(card, isVisible);
      }

      if (isVisible && !settled) {
        frame = window.requestAnimationFrame(step);
      }
    };

    const wake = () => {
      if (frame !== 0) return;
      spring.lastTime = performance.now();
      frame = window.requestAnimationFrame(step);
    };
    wakeHintRef.current = wake;
    layoutDirtyRef.current = true;
    step(performance.now());

    if (reducedMotion) {
      mountedPaintReady = true;
      const card = hintCardElement.current;
      const isVisible = pointerInViewport.current && cursor.current !== null;
      if (card && isVisible) {
        lastVisible = true;
        setCardVisible(card, true);
      }
    } else {
      enterFrame1 = window.requestAnimationFrame(() => {
        enterFrame2 = window.requestAnimationFrame(() => {
          mountedPaintReady = true;
          const isVisible = pointerInViewport.current && cursor.current !== null;
          if (hintCardElement.current && isVisible !== lastVisible) {
            lastVisible = isVisible;
            setCardVisible(hintCardElement.current, isVisible);
          }
        });
      });
    }

    const viewport = viewportElement.current;
    const resizeObserver = typeof ResizeObserver === "function"
      ? new ResizeObserver(() => {
        layoutDirtyRef.current = true;
        wake();
      })
      : null;
    if (resizeObserver) {
      if (viewport) resizeObserver.observe(viewport);
      if (hintCardElement.current) resizeObserver.observe(hintCardElement.current);
    }

    const mutationObserver = typeof MutationObserver === "function" && viewport
      ? new MutationObserver((mutations) => {
        const relevant = mutations.some((mutation) => !hintElement.current?.contains(mutation.target));
        if (!relevant) return;
        layoutDirtyRef.current = true;
        wake();
      })
      : null;
    mutationObserver?.observe(viewport!, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-hidden", "inert", "class"],
    });

    const handleTransitionEnd = (event: TransitionEvent) => {
      if (event.target instanceof Node && hintElement.current?.contains(event.target)) return;
      layoutDirtyRef.current = true;
      wake();
    };
    viewport?.addEventListener("transitionend", handleTransitionEnd);

    const hasViewportMenu = (nodes: NodeList) =>
      Array.from(nodes).some((node) => node instanceof Element && node.matches(".ui-combobox-menu[data-in-viewport='true']"));

    const bodyObserver = typeof MutationObserver === "function"
      ? new MutationObserver((mutations) => {
        if (!mutations.some((m) => hasViewportMenu(m.addedNodes) || hasViewportMenu(m.removedNodes))) return;
        layoutDirtyRef.current = true;
        wake();
      })
      : null;
    bodyObserver?.observe(document.body, { childList: true });

    const handleDocumentPointerMove = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const inMenu = Boolean(target.closest(".ui-combobox-menu[data-in-viewport='true']"));
      if (inMenu) {
        const box = viewportElement.current?.getBoundingClientRect();
        if (!box) return;
        pointerInViewport.current = true;
        cursor.current = [event.clientX - box.left, event.clientY - box.top];
        wake();
      } else if (pointerInViewport.current && !viewportElement.current?.contains(target)) {
        pointerInViewport.current = false;
        wake();
      }
    };
    document.addEventListener("pointermove", handleDocumentPointerMove);

    return () => {
      wakeHintRef.current = null;
      if (frame !== 0) window.cancelAnimationFrame(frame);
      if (enterFrame1 !== 0) window.cancelAnimationFrame(enterFrame1);
      if (enterFrame2 !== 0) window.cancelAnimationFrame(enterFrame2);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
      bodyObserver?.disconnect();
      viewport?.removeEventListener("transitionend", handleTransitionEnd);
      document.removeEventListener("pointermove", handleDocumentPointerMove);
    };
  }, [hasHint]);
  const [hoveredBeam, setHoveredBeam] = useState<string | null>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const [showDetails, setShowDetails] = useState(false);
  const [modelVisible, setModelVisible] = useState(true);
  const [modelTransparency, setModelTransparency] = useState(DEFAULT_MODEL_TRANSPARENCY);
  // A freshly imported or restored model must show up visible with the
  // default scene display settings, whatever the previous model used.
  useEffect(() => {
    setModelVisible(true);
    setModelTransparency(DEFAULT_MODEL_TRANSPARENCY);
  }, [stepModelGeneration]);
  const [errorPresentation, setErrorPresentation] = useState<{
    message: string;
    version: number;
    leaving: boolean;
  } | null>(null);
  const stepPicker = useRef<((clientX: number, clientY: number, bounds: DOMRect) => void) | null>(null);
  const pointerDown = useRef<[number, number] | null>(null);
  const compass = useRef<SVGSVGElement>(null);
  const zoomCommand = useRef<((factor: number) => void) | null>(null);
  const detailsFrame = useRef<number | null>(null);
  const revealDetailsAfterFirstFrame = useCallback(() => {
    onFirstFrame?.();
    detailsFrame.current = window.requestAnimationFrame(() => {
      detailsFrame.current = null;
      setShowDetails(true);
    });
  }, [onFirstFrame]);
  useEffect(() => () => {
    if (detailsFrame.current !== null) window.cancelAnimationFrame(detailsFrame.current);
  }, []);
  useEffect(() => {
    if (toolError) {
      setErrorPresentation({ message: toolError, version: toolErrorVersion, leaving: false });
      return undefined;
    }
    setErrorPresentation((current) => current ? { ...current, leaving: true } : null);
    const timeout = window.setTimeout(() => {
      setErrorPresentation((current) => current?.leaving ? null : current);
    }, 220);
    return () => window.clearTimeout(timeout);
  }, [toolError, toolErrorVersion]);
  useEffect(() => {
    if (!hasHint) return;
    layoutDirtyRef.current = true;
    wakeHintRef.current?.();
  }, [hasHint, toolHint, manualHud, dimensionHud, sectionHud, errorPresentation, visibleRightInset, visibleBottomInset]);
  const bounds = useMemo(() => {
    const min = [Infinity, Infinity, Infinity];
    const max = [-Infinity, -Infinity, -Infinity];
    for (const beam of beams) {
      const center: [number, number, number] = [
        beam.center[0] / 1000,
        beam.center[2] / 1000,
        beam.center[1] / 1000,
      ];
      const size: [number, number, number] = [
        beam.size[0] / 1000,
        beam.size[2] / 1000,
        beam.size[1] / 1000,
      ];
      for (let axis = 0; axis < 3; axis += 1) {
        min[axis] = Math.min(min[axis], center[axis] - size[axis] / 2);
        max[axis] = Math.max(max[axis], center[axis] + size[axis] / 2);
      }
    }
    if (stepModel) {
      const [modelMin, modelMax] = transformedStepBounds(stepModel);
      for (let axis = 0; axis < 3; axis += 1) {
        min[axis] = Math.min(min[axis], modelMin[axis]);
        max[axis] = Math.max(max[axis], modelMax[axis]);
      }
    }
    const center = min.map((value, axis) => (value + max[axis]) / 2) as [
      number,
      number,
      number,
    ];
    return {
      center,
      span: Math.max(...max.map((value, axis) => value - min[axis])),
        min: min as [number, number, number],
        max: max as [number, number, number],
    };
    }, [beams, stepModel]);
    const grid = useMemo(() => {
    const section = 0.5;
    const size = Math.max(
      10,
        Math.ceil((bounds.span + section * 4) / section) * section,
    );
    return {
      size,
      divisions: Math.round(size / section),
        position: [bounds.center[0], bounds.min[1] - 0.01, bounds.center[2]] as [number, number, number],
    };
    }, [bounds]);
  const manualPreview = useMemo(() => {
    if (manualSupports.length !== 2 || !manualSection) return null;
    const [first, second] = manualSupports;
    if (manualBetweenMode && (!manualReference || !manualSecondReference)) return null;
    const alongX = first.beam.size[0] >= first.beam.size[1];
    const firstCenter = alongX
      ? first.beam.center[1] / 1000
      : first.beam.center[0] / 1000;
    const secondCenter = alongX
      ? second.beam.center[1] / 1000
      : second.beam.center[0] / 1000;
    const firstHalfSize = alongX
      ? first.beam.size[1] / 2000
      : first.beam.size[0] / 2000;
    const secondHalfSize = alongX
      ? second.beam.size[1] / 2000
      : second.beam.size[0] / 2000;
    // The persisted beam spans the outer faces of both supports. The preview
    // deliberately uses exactly the same rule, regardless of click position.
    const start = Math.min(firstCenter - firstHalfSize, secondCenter - secondHalfSize);
    const end = Math.max(firstCenter + firstHalfSize, secondCenter + secondHalfSize);
    const length = end - start;
    if (length < 0.001) return null;
    const thickness = manualSection.width / 1000;
    const height = manualSection.height / 1000;
    const bearing = Math.max(
      first.beam.center[2] + first.beam.size[2] / 2,
      second.beam.center[2] + second.beam.size[2] / 2,
    ) / 1000;
    let lateral = alongX ? first.point[0] : first.point[2];
    if (manualBetweenMode && manualReference && manualSecondReference) {
      const placement = betweenFaces(manualReference, manualSecondReference, manualSection.width);
      if (!placement) return null;
      lateral = placement.center / 1000;
    } else if (manualReference) {
      const reference = manualReference.beam;
      const referenceCentre = alongX ? reference.center[0] / 1000 : reference.center[1] / 1000;
      const referenceHalfSize = alongX ? reference.size[0] / 2000 : reference.size[1] / 2000;
      const gap = manualDistance / 1000;
      const maximum = manualReference.face === "x_max" || manualReference.face === "y_max";
      if (gap >= 0) lateral = referenceCentre + (maximum ? 1 : -1) * (referenceHalfSize + gap + thickness / 2);
      else lateral = referenceCentre - (maximum ? 1 : -1) * (referenceHalfSize - gap + thickness / 2);
    }
    return {
      position: (alongX
        ? [lateral, bearing + height / 2, (start + end) / 2]
        : [(start + end) / 2, bearing + height / 2, lateral]) as ViewportPoint,
      size: alongX ? [thickness, height, length] as [number, number, number] : [length, height, thickness] as [number, number, number],
    };
  }, [manualBetweenMode, manualDistance, manualReference, manualSecondReference, manualSection, manualSupports]);
  const sectionHudAnchor = useMemo<ViewportPoint | null>(() => {
    if (selectedBeams.length === 0) return null;
    const selected = beams.filter((beam) =>
      selectedBeams.includes(`${beam.layerId}:${beam.layerIndex}`),
    );
    if (selected.length === 0) return null;
    const center = selected.reduce(
      (sum, beam) => [
        sum[0] + beam.center[0] / 1000,
        sum[1] + beam.center[2] / 1000 + beam.size[2] / 2000,
        sum[2] + beam.center[1] / 1000,
      ] as ViewportPoint,
      [0, 0, 0] as ViewportPoint,
    );
    return [
      center[0] / selected.length,
      center[1] / selected.length + 0.16,
      center[2] / selected.length,
    ];
  }, [beams, selectedBeams]);
  return (
    <div
      className="viewport"
      ref={viewportElement}
      style={{
        "--viewport-right-inset": `${visibleRightInset}px`,
        "--viewport-bottom-inset": `${visibleBottomInset}px`,
      } as CSSProperties}
      onPointerDown={(event) => {
        updateViewportPointer(event);
        if (stepFaceSelectionEnabled) {
          pointerDown.current = [event.clientX, event.clientY];
        }
      }}
      onPointerEnter={updateViewportPointer}
      onPointerMove={updateViewportPointer}
      onPointerLeave={(event) => {
        if (!pointerInViewport.current) return;
        if (event.relatedTarget instanceof Element && event.relatedTarget.closest(".ui-combobox-menu[data-in-viewport='true']")) {
          return;
        }
        pointerInViewport.current = false;
        wakeHintRef.current?.();
      }}
      onContextMenu={onUndoToolSelection ? (event) => {
        event.preventDefault();
        onUndoToolSelection();
      } : undefined}
      onClick={stepFaceSelectionEnabled ? (event) => {
        const down = pointerDown.current;
        pointerDown.current = null;
        if (!down || Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 4) return;
        stepPicker.current?.(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect());
      } : undefined}
    >
      <Canvas
        frameloop="demand"
        resize={{ scroll: false, debounce: 0, offsetSize: true }}
        camera={{ position: [5, 4, 5], fov: 42 }}
      >
          <FirstFrameReporter onFirstFrame={revealDetailsAfterFirstFrame} />
          <ViewOffsetAnimator
            rightInset={visibleRightInset}
            bottomInset={visibleBottomInset}
            animate={animateInsets}
            expanding={insetsExpanding}
            durationMs={insetsDurationMs}
          />
          <DirectionCompassUpdater compass={compass} />
          <Camera preset={preset} presetRequest={presetRequest} bounds={bounds} />
          <FitCamera
            fitRequest={fitRequest}
            bounds={bounds}
            visibleRightInset={visibleRightInset}
            visibleBottomInset={visibleBottomInset}
          />
          <CameraZoom command={zoomCommand} fitRequest={fitRequest} presetRequest={presetRequest} onChange={setZoomPercent} />
        <color attach="background" args={["#edf1f3"]} />
        <ambientLight intensity={1.5} />
        <directionalLight position={[5, 8, 4]} intensity={2} castShadow />
        {showDetails && gridVisible ? (
          <gridHelper
            args={[grid.size, grid.divisions, "#aab9c1", "#d9e1e5"]}
            position={grid.position}
          />
        ) : null}
          {showPallet ? beams.filter((beam) => !hiddenLayerIds.includes(beam.layerId)).map((beam) => (
          <mesh
            key={`${beam.layerId}:${beam.index}`}
            position={[
              beam.center[0] / 1000,
              beam.center[2] / 1000,
              beam.center[1] / 1000,
            ]}
            onClick={(event) => {
              event.stopPropagation();
              const point: ViewportPoint = [
                event.point.x,
                event.point.y,
                event.point.z,
              ];
              const normal = event.face?.normal;
              onToggleBeam(
                beam,
                point,
                normal ? [normal.x, normal.y, normal.z] : undefined,
              );
            }}
            onPointerOver={(event) => { if (beamSelectionEnabled) { event.stopPropagation(); setHoveredBeam(`${beam.layerId}:${beam.layerIndex}`); } }}
            onPointerOut={() => setHoveredBeam(null)}
          >
            <boxGeometry
              args={[
                beam.size[0] / 1000,
                beam.size[2] / 1000,
                beam.size[1] / 1000,
              ]}
            />
            <meshStandardMaterial
              color={
                selectedBeams.includes(`${beam.layerId}:${beam.layerIndex}`)
                  ? "#d83a3a"
                  : hoveredBeam === `${beam.layerId}:${beam.layerIndex}`
                    ? "#d9a56f"
                  : "#b88254"
              }
              roughness={0.72}
            />
          </mesh>
          )) : null}
          {showDetails && showPallet ? manualSupports.slice(0, 1).map(({ beam, point }) => (
          <mesh
            key={`manual-point:${beam.layerId}:${beam.layerIndex}`}
            position={[point[0], point[1] + 0.08, point[2]]}
            renderOrder={20}
          >
            <sphereGeometry args={[0.07, 16, 12]} />
            <meshStandardMaterial color="#e07822" emissive="#7a3307" depthTest={false} />
          </mesh>
          )) : null}
          {showDetails && showPallet && manualReference ? <BeamFaceOverlay reference={manualReference} /> : null}
          {showDetails && showPallet && manualSecondReference ? <BeamFaceOverlay reference={manualSecondReference} /> : null}
          {showDetails && showPallet && manualPreview ? <mesh position={manualPreview.position}>
          <boxGeometry args={manualPreview.size} />
          <meshStandardMaterial color="#36b778" transparent opacity={0.42} depthWrite={false} />
        </mesh> : null}
        {false
          ? insertionMarkers.map((marker) => {
              const selected =
                selectedSlot?.layerId === marker.slot.layerId &&
                selectedSlot?.afterBeamIndex === marker.slot.afterBeamIndex;
              return (
                <group
                  key={`${marker.slot.layerId}:${marker.slot.afterBeamIndex}`}
                >
                  <mesh
                    position={[
                      marker.center[0] / 1000,
                      marker.center[2] / 1000,
                      marker.center[1] / 1000,
                    ]}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelectInsertion(marker);
                    }}
                  >
                    <sphereGeometry args={[marker.size / 1000, 16, 12]} />
                    <meshStandardMaterial
                      color={selected ? "#e07822" : "#269e6b"}
                      emissive={selected ? "#7a3307" : "#0e5638"}
                    />
                  </mesh>
                  {selected ? (
                    <mesh
                      position={[
                        marker.preview.center[0] / 1000,
                        marker.preview.center[2] / 1000,
                        marker.preview.center[1] / 1000,
                      ]}
                    >
                      <boxGeometry
                        args={[
                          marker.preview.size[0] / 1000,
                          marker.preview.size[2] / 1000,
                          marker.preview.size[1] / 1000,
                        ]}
                      />
                      <meshStandardMaterial
                        color="#269e6b"
                        transparent
                        opacity={0.45}
                      />
                    </mesh>
                  ) : null}
                </group>
              );
            })
          : null}
          {showDetails && showPallet && dimensionsVisible ? dimensions.map((dimension, index) => {
          const dimensionKey = `${dimension.layerId}:${dimension.index}`;
          const isHovered =
            dimensionEditing && hoveredDimension === dimensionKey;
          const isSelected = selectedDimension?.layerId === dimension.layerId
            && selectedDimension.index === dimension.index;
          const start = point(dimension.start);
          const end = point(dimension.end);
          const middle: [number, number, number] = [
            (start[0] + end[0]) / 2,
            (start[1] + end[1]) / 2,
            (start[2] + end[2]) / 2,
          ];
          const length = Math.hypot(
            end[0] - start[0],
            end[1] - start[1],
            end[2] - start[2],
          );
          const arrowLength = Math.min(0.08, length / 8);
          const arrowHalfWidth = arrowLength * 0.25;
          const unit: [number, number, number] = [
            (end[0] - start[0]) / length,
            (end[1] - start[1]) / length,
            (end[2] - start[2]) / length,
          ];
          const side: [number, number, number] =
            Math.abs(unit[1]) < 0.9
              ? [-unit[2], 0, unit[0]]
              : [unit[1], -unit[0], 0];
          const arrow = (origin: [number, number, number], direction: number) =>
            [
              [
                origin[0] + unit[0] * direction * arrowLength + side[0] * arrowHalfWidth,
                origin[1] + unit[1] * direction * arrowLength + side[1] * arrowHalfWidth,
                origin[2] + unit[2] * direction * arrowLength + side[2] * arrowHalfWidth,
              ],
              origin,
              [
                origin[0] + unit[0] * direction * arrowLength - side[0] * arrowHalfWidth,
                origin[1] + unit[1] * direction * arrowLength - side[1] * arrowHalfWidth,
                origin[2] + unit[2] * direction * arrowLength - side[2] * arrowHalfWidth,
              ],
            ] as [number, number, number][];
          const defaultExtension = (endpoint: [number, number, number]) =>
            dimension.axis === "length"
              ? [endpoint[0], endpoint[1], 0] as [number, number, number]
              : [0, endpoint[1], endpoint[2]] as [number, number, number];
          const startExtension = dimension.startExtension
            ? point(dimension.startExtension)
            : defaultExtension(start);
          const endExtension = dimension.endExtension
            ? point(dimension.endExtension)
            : defaultExtension(end);
          const dimensionColor = isHovered
            ? "#e07822"
            : dimension.editable
              ? "#315b6c"
              : "#718087";
          return (
            <group key={index}>
              <Line
                points={[startExtension, start]}
                color={dimensionColor}
                lineWidth={1}
              />
              <Line
                points={[endExtension, end]}
                color={dimensionColor}
                lineWidth={1}
              />
              <Line
                points={[start, end]}
                color={dimensionColor}
                lineWidth={isHovered ? 3 : dimension.editable ? 2 : 1.5}
              />
              <Line points={arrow(start, 1)} color={dimensionColor} lineWidth={1.5} />
              <Line points={arrow(end, -1)} color={dimensionColor} lineWidth={1.5} />
              {dimensionEditing && dimension.editable ? (
                <DimensionHitArea
                  dimension={dimension}
                  start={start}
                  end={end}
                  middle={middle}
                  onSelect={onSelectDimension}
                  onHover={onHoverDimension}
                />
              ) : null}
              {!isSelected ? (
                <DimensionLabel
                  value={dimension.value}
                  position={middle}
                  dimension={dimension}
                  canEdit={dimensionEditing}
                  onSelect={onSelectDimension}
                  onHover={onHoverDimension}
                />
              ) : null}
              {isSelected && dimensionHud ? <Html position={middle} center>{dimensionHud}</Html> : null}
            </group>
          );
          }) : null}
        {showDetails && manualHud && manualSupports[0] ? <Html position={[manualSupports[0].point[0], manualSupports[0].point[1] + 0.24, manualSupports[0].point[2]]} center>{manualHud}</Html> : null}
          {showDetails && sectionHud && sectionHudAnchor ? <Html position={sectionHudAnchor} center>{sectionHud}</Html> : null}
          <ViewportOrbitControls key={preset} bounds={bounds} />
          {stepModel && modelVisible && modelTransparency < 100 ? (
            <Suspense fallback={null}>
              <StepModelViewport
                model={stepModel}
                selectedFace={selectedStepFace ?? null}
                onSelectFace={(faceId) => onSelectStepFace?.(faceId)}
                selectionEnabled={stepFaceSelectionEnabled}
                pickerRef={stepPicker}
                opacity={1 - modelTransparency / 100}
              />
            </Suspense>
          ) : null}
      </Canvas>
      <div className="viewport-navigation-guide">
        <svg ref={compass} className="viewport-compass" viewBox="0 0 80 80" role="img" aria-label="Направления осей X, Y и Z">
          <circle cx="40" cy="40" r="2.5" fill="#6d7b80" />
          {(["x", "y", "z"] as const).map((axis) => (
            <g key={axis} className={`viewport-compass-${axis}`}>
              <line data-axis-line={axis} x1="40" y1="40" x2="40" y2="40" />
              <text data-axis-label={axis} x="40" y="40">{axis.toUpperCase()}</text>
            </g>
          ))}
        </svg>
        <div className="viewport-navigation-help">
          <div className={`viewport-navigation-tip${navigationButtons & 1 ? " is-active" : ""}`}><MouseLeft size={16} aria-hidden="true" /><span>ЛКМ (зажать) – вращать</span></div>
          <div className={`viewport-navigation-tip${navigationButtons & 4 ? " is-active" : ""}`}><Mouse size={16} aria-hidden="true" /><span>Колёсико мыши (зажать) – изменить масштаб</span></div>
          <div className={`viewport-navigation-tip${navigationButtons & 2 ? " is-active" : ""}`}><MouseRight size={16} aria-hidden="true" /><span>ПКМ (зажать) – двигать</span></div>
        </div>
      </div>
      {toolbar ? <div className="viewport-floating-toolbar">{toolbar}</div> : null}
      <div className={`viewport-fit-control${insetsExpanding ? " is-expanded" : ""}`}>
        <SceneSettings hasModel={!!stepModel} modelVisible={modelVisible} setModelVisible={setModelVisible}
          transparency={modelTransparency} setTransparency={setModelTransparency}
          dimensionsVisible={dimensionsVisible} setDimensionsVisible={onDimensionsVisibleChange}
          gridVisible={gridVisible} setGridVisible={onGridVisibleChange} expanded={insetsExpanding} />
        {fitViewControl}
        <div className="viewport-zoom-control" aria-label="Масштаб просмотра">
          <Tooltip content="Отдалить камеру (уменьшить масштаб)" side="top">
            <button type="button" onClick={() => zoomCommand.current?.(1.2)} aria-label="Уменьшить масштаб"><Minus size={16} aria-hidden="true" /></button>
          </Tooltip>
          <span className="viewport-zoom-value" aria-live="polite">{zoomPercent}%</span>
          <Tooltip content="Приблизить камеру (увеличить масштаб)" side="top">
            <button type="button" onClick={() => zoomCommand.current?.(1 / 1.2)} aria-label="Увеличить масштаб"><Plus size={16} aria-hidden="true" /></button>
          </Tooltip>
        </div>
      </div>
      {toolHint ? (
        <div
          className="viewport-hint-layer"
          ref={hintElement}
        >
          <div className="viewport-hint" ref={hintCardElement}>
            <ViewportTip text={toolHint} canExit={toolHintCanExit} />
          </div>
        </div>
      ) : null}
      {errorPresentation ? (
        <div
          key={`tool-error-${errorPresentation.version}`}
          className={`viewport-error-toast${errorPresentation.leaving ? " is-leaving" : ""}`}
          role="alert"
        >
          <BadgeAlert size={16} aria-hidden="true" /> <span>{errorPresentation.message}</span>
          <button type="button" className="viewport-error-dismiss" aria-label="Закрыть уведомление" onClick={() => setErrorPresentation(null)}><X size={16} aria-hidden="true" /></button>
        </div>
      ) : null}
    </div>
  );
}
