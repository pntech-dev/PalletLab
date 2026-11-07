import { Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import {
  BufferGeometry,
  CanvasTexture,
  Float32BufferAttribute,
  LinearFilter,
  Matrix4,
  MathUtils,
  Mesh,
  PerspectiveCamera,
  Raycaster,
  Uint32BufferAttribute,
  Vector3,
  Vector2,
} from "three";
import { useEffect, useMemo, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import type { StepModelGeometry as StepModelSnapshot } from "./stepModelGeometry";
export type { StepModelGeometry as StepModelSnapshot } from "./stepModelGeometry";

export type ViewportBeam = {
  index: number;
  layerId: string;
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

function transformedStepBounds(model: StepModelSnapshot): [ViewportPoint, ViewportPoint] {
  const [xMin, xMax, yMin, yMax, zMin, zMax] = model.bounds;
  const matrix = new Matrix4().fromArray(model.transform);
  const minimum: ViewportPoint = [Infinity, Infinity, Infinity];
  const maximum: ViewportPoint = [-Infinity, -Infinity, -Infinity];
  for (const x of [xMin, xMax]) for (const y of [yMin, yMax]) for (const z of [zMin, zMax]) {
    const point = new Vector3(x / 1000, z / 1000, y / 1000).applyMatrix4(matrix);
    minimum[0] = Math.min(minimum[0], point.x);
    minimum[1] = Math.min(minimum[1], point.y);
    minimum[2] = Math.min(minimum[2], point.z);
    maximum[0] = Math.max(maximum[0], point.x);
    maximum[1] = Math.max(maximum[1], point.y);
    maximum[2] = Math.max(maximum[2], point.z);
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
      isometric: [x + distance, y + distance * 0.75, z + distance],
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

function FitCamera({ fitRequest, bounds }: { fitRequest: number; bounds: ViewportBounds }) {
  const { camera, size } = useThree();
  const previousRequest = useRef<number | null>(null);

  useEffect(() => {
    if (size.width <= 0 || size.height <= 0) return;
    if (fitRequest === previousRequest.current) return;
    previousRequest.current = fitRequest;

    const perspective = camera as PerspectiveCamera;
    const verticalFov = MathUtils.degToRad(perspective.fov);
    const horizontalFov = 2 * Math.atan(
      Math.tan(verticalFov / 2) * (size.width / Math.max(1, size.height)),
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
    camera.position.copy(target.addScaledVector(direction, -distance));
    camera.lookAt(...bounds.center);
  }, [bounds, camera, fitRequest, size.height, size.width]);

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
  // The rendered line is intentionally thin. This invisible cuboid covers its
  // full length and gives it a reliable 160 mm hit target on every DPI scale.
  const size: [number, number, number] =
    dimension.axis === "length" ? [length, 0.16, 0.16] : [0.16, 0.16, length];
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
    canvas.width = 144;
    canvas.height = 56;
    const context = canvas.getContext("2d");
    if (!context)
      throw new Error("Canvas 2D is unavailable for dimension labels.");
    context.fillStyle = "rgba(255, 255, 255, 0.76)";
    context.roundRect(2, 2, 140, 52, 7);
    context.fill();
    context.fillStyle = "#183f52";
    context.font = "600 27px system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(value.toFixed(0), 72, 29);
    const result = new CanvasTexture(canvas);
    result.minFilter = LinearFilter;
    return result;
  }, [value]);
  useEffect(() => () => texture.dispose(), [texture]);
  return (
    <sprite
      position={position}
      scale={[0.3, 0.12, 1]}
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

function StepModel({
  model,
  selectedFace,
  onSelectFace,
  selectionEnabled,
  pickerRef,
}: {
  model: StepModelSnapshot;
  selectedFace: number | null;
  onSelectFace: (faceId: number) => void;
  selectionEnabled: boolean;
  pickerRef: MutableRefObject<((clientX: number, clientY: number, bounds: DOMRect) => void) | null>;
}) {
  const meshRef = useRef<Mesh>(null);
  const { camera } = useThree();
  const transform = useMemo(() => new Matrix4().fromArray(model.transform), [model.transform]);
  const geometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(model.displayPositions, 3));
    result.setIndex(new Uint32BufferAttribute(model.indices, 1));
    result.computeVertexNormals();
    result.computeBoundingSphere();
    return result;
  }, [model.displayPositions, model.indices]);

  const edgeGeometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(model.displayEdgePositions, 3));
    result.setIndex(new Uint32BufferAttribute(model.edgeIndices, 1));
    result.computeBoundingSphere();
    return result;
  }, [model.displayEdgePositions, model.edgeIndices]);

  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => () => edgeGeometry.dispose(), [edgeGeometry]);
  useEffect(() => {
    if (!selectionEnabled) {
      pickerRef.current = null;
      return undefined;
    }
    const selectable = new Set(model.selectableFaceIds);
    const raycaster = new Raycaster();
    const pointer = new Vector2();
    pickerRef.current = (clientX, clientY, bounds) => {
      const mesh = meshRef.current;
      if (!mesh || bounds.width <= 0 || bounds.height <= 0) return;
      pointer.set(
        ((clientX - bounds.left) / bounds.width) * 2 - 1,
        -((clientY - bounds.top) / bounds.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(mesh, false)[0];
      const faceId = typeof hit?.faceIndex === "number" ? model.triangleFaceIds[hit.faceIndex] : undefined;
      if (faceId !== undefined && selectable.has(faceId)) onSelectFace(faceId);
    };
    return () => {
      pickerRef.current = null;
    };
  }, [camera, model.selectableFaceIds, model.triangleFaceIds, onSelectFace, pickerRef, selectionEnabled]);
  return (
    <group matrix={transform} matrixAutoUpdate={false}>
      <mesh ref={meshRef} geometry={geometry}>
        <meshStandardMaterial color="#b8c2cc" transparent opacity={0.2} depthWrite roughness={0.62} metalness={0.1} />
      </mesh>
      <lineSegments geometry={edgeGeometry} renderOrder={2}>
        <lineBasicMaterial color="#31414d" transparent opacity={1} depthTest={true} depthWrite={false} />
      </lineSegments>
      {selectedFace !== null ? (
        <StepFaceOverlay
          positions={model.displayPositions}
          indices={model.indices}
          triangleFaceIds={model.triangleFaceIds}
          faceId={selectedFace}
          selected
        />
      ) : null}
    </group>
  );
}

function StepFaceOverlay({
  positions,
  indices,
  triangleFaceIds,
  faceId,
  selected,
}: {
  positions: Float32Array;
  indices: Uint32Array;
  triangleFaceIds: Int32Array;
  faceId: number;
  selected: boolean;
}) {
  const geometry = useMemo(() => {
    let selectedCount = 0;
    for (const candidate of triangleFaceIds) if (candidate === faceId) selectedCount += 1;
    const selectedIndices = new Uint32Array(selectedCount * 3);
    let target = 0;
    for (let triangle = 0; triangle < triangleFaceIds.length; triangle += 1) {
      if (triangleFaceIds[triangle] !== faceId) continue;
      selectedIndices[target] = indices[triangle * 3];
      selectedIndices[target + 1] = indices[triangle * 3 + 1];
      selectedIndices[target + 2] = indices[triangle * 3 + 2];
      target += 3;
    }
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(positions, 3));
    result.setIndex(new Uint32BufferAttribute(selectedIndices, 1));
    return result;
  }, [faceId, indices, positions, triangleFaceIds]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <mesh geometry={geometry} renderOrder={3}>
      <meshBasicMaterial color={selected ? "#e64231" : "#f2ad2e"} transparent opacity={0.78} depthWrite={false} polygonOffset polygonOffsetFactor={-2} />
    </mesh>
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
  selectedStepFace,
  onSelectStepFace,
  stepFaceSelectionEnabled = false,
  showPallet = true,
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
  manualDistance = 0,
  manualHud,
  dimensionHud,
  sectionHud,
  toolbar,
  fitViewControl,
  toolHint,
  toolError,
  toolErrorVersion = 0,
  onUndoToolSelection,
  beamSelectionEnabled,
}: {
  beams: ViewportBeam[];
  dimensions: ViewportDimension[];
  preset: CameraPreset;
  presetRequest: number;
    fitRequest: number;
    stepModel?: StepModelSnapshot | null;
    selectedStepFace?: number | null;
    onSelectStepFace?: (faceId: number) => void;
    stepFaceSelectionEnabled?: boolean;
    showPallet?: boolean;
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
  manualDistance?: number;
  manualHud?: ReactNode;
  dimensionHud?: ReactNode;
  sectionHud?: ReactNode;
  toolbar?: ReactNode;
  fitViewControl?: ReactNode;
  toolHint?: string | null;
  toolError?: string | null;
  toolErrorVersion?: number;
  onUndoToolSelection?: () => void;
  beamSelectionEnabled: boolean;
}) {
  const [cursor, setCursor] = useState<[number, number]>([16, 16]);
  const [hoveredBeam, setHoveredBeam] = useState<string | null>(null);
  const stepPicker = useRef<((clientX: number, clientY: number, bounds: DOMRect) => void) | null>(null);
  const pointerDown = useRef<[number, number] | null>(null);
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
    if (manualReference) {
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
  }, [manualDistance, manualReference, manualSection, manualSupports]);
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
      onPointerDown={stepFaceSelectionEnabled ? (event) => {
        pointerDown.current = [event.clientX, event.clientY];
      } : undefined}
      onPointerMove={toolHint ? (event) => {
        const box = event.currentTarget.getBoundingClientRect();
        setCursor([
          Math.max(8, Math.min(event.clientX - box.left + 14, box.width - 328)),
          Math.max(8, Math.min(event.clientY - box.top + 14, box.height - 54)),
        ]);
      } : undefined}
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
        camera={{ position: [5, 4, 5], fov: 42 }}
      >
          <Camera preset={preset} presetRequest={presetRequest} bounds={bounds} />
          <FitCamera fitRequest={fitRequest} bounds={bounds} />
        <color attach="background" args={["#edf1f3"]} />
        <ambientLight intensity={1.5} />
        <directionalLight position={[5, 8, 4]} intensity={2} castShadow />
        <gridHelper
          args={[grid.size, grid.divisions, "#aab9c1", "#d9e1e5"]}
          position={grid.position}
        />
          {showPallet ? beams.map((beam) => (
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
          {showPallet ? manualSupports.slice(0, 1).map(({ beam, point }) => (
          <mesh
            key={`manual-point:${beam.layerId}:${beam.layerIndex}`}
            position={[point[0], point[1] + 0.08, point[2]]}
            renderOrder={20}
          >
            <sphereGeometry args={[0.07, 16, 12]} />
            <meshStandardMaterial color="#e07822" emissive="#7a3307" depthTest={false} />
          </mesh>
          )) : null}
          {showPallet && manualReference ? <BeamFaceOverlay reference={manualReference} /> : null}
          {showPallet && manualPreview ? <mesh position={manualPreview.position}>
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
          {showPallet ? dimensions.map((dimension, index) => {
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
          const scale = Math.min(0.06, length / 5);
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
                origin[0] + (unit[0] * direction + side[0]) * scale,
                origin[1] + (unit[1] * direction + side[1]) * scale,
                origin[2] + (unit[2] * direction + side[2]) * scale,
              ],
              origin,
              [
                origin[0] + (unit[0] * direction - side[0]) * scale,
                origin[1] + (unit[1] * direction - side[1]) * scale,
                origin[2] + (unit[2] * direction - side[2]) * scale,
              ],
            ] as [number, number, number][];
          return (
            <group key={index}>
              {dimension.startExtension ? (
                <Line
                  points={[point(dimension.startExtension), start]}
                  color="#315b6c"
                  lineWidth={1}
                />
              ) : null}
              {dimension.endExtension ? (
                <Line
                  points={[point(dimension.endExtension), end]}
                  color="#315b6c"
                  lineWidth={1}
                />
              ) : null}
              <Line
                points={[start, end]}
                color={
                  isHovered
                    ? "#e07822"
                    : dimension.editable
                      ? "#315b6c"
                      : "#718087"
                }
                lineWidth={isHovered ? 3 : dimension.editable ? 2 : 1.5}
              />
              <Line points={arrow(start, 1)} color="#315b6c" lineWidth={1.5} />
              <Line points={arrow(end, -1)} color="#315b6c" lineWidth={1.5} />
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
        {manualHud && manualSupports[0] ? <Html position={[manualSupports[0].point[0], manualSupports[0].point[1] + 0.24, manualSupports[0].point[2]]} center>{manualHud}</Html> : null}
          {sectionHud && sectionHudAnchor ? <Html position={sectionHudAnchor} center>{sectionHud}</Html> : null}
          <OrbitControls
            key={preset}
            makeDefault
            target={bounds.center}
            minPolarAngle={0.03}
            maxPolarAngle={Math.PI - 0.03}
          />
          {stepModel ? (
            <StepModel
              model={stepModel}
              selectedFace={selectedStepFace ?? null}
              onSelectFace={(faceId) => onSelectStepFace?.(faceId)}
              selectionEnabled={stepFaceSelectionEnabled}
              pickerRef={stepPicker}
            />
          ) : null}
      </Canvas>
      {toolbar ? <div className="viewport-floating-toolbar">{toolbar}</div> : null}
      {fitViewControl ? <div className="viewport-fit-control">{fitViewControl}</div> : null}
      {toolError || toolHint ? (
        <div
          key={toolError ? `tool-error-${toolErrorVersion}` : "tool-hint"}
          className={`viewport-hint${toolError ? " viewport-error" : ""}`}
          style={{ left: cursor[0], top: cursor[1] }}
        >
          {toolError ?? toolHint}
        </div>
      ) : null}
    </div>
  );
}
