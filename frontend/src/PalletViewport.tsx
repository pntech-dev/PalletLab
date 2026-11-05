import { Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import {
  BufferGeometry,
  CanvasTexture,
  Float32BufferAttribute,
  LinearFilter,
  MathUtils,
  PerspectiveCamera,
  Uint32BufferAttribute,
  Vector3,
} from "three";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

export type ViewportBeam = {
  index: number;
  layerId: string;
  layerIndex: number;
  orientation: string;
  center: [number, number, number];
  size: [number, number, number];
};
export type ViewportPoint = [number, number, number];
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
export type StepModelSnapshot = {
  encoding: "typed-buffer-v1";
  positions: string;
  indices: string;
  triangleFaceIds: string;
  selectableFaceIds: number[];
  edgePoints: string;
  edgeCells: string;
  bounds: [number, number, number, number, number, number];
};
type ManualBeamSection = { height: number; width: number };

type DecodedStepModel = {
  positions: Float32Array;
  indices: Uint32Array;
  triangleFaceIds: Int32Array;
  edgePoints: Float32Array;
  edgeCells: Uint32Array;
};

function decodeBase64(source: string): Uint8Array {
  const text = window.atob(source);
  const result = new Uint8Array(text.length);
  for (let index = 0; index < text.length; index += 1) result[index] = text.charCodeAt(index);
  return result;
}

function decodeTypedArray<T extends Float32Array | Uint32Array | Int32Array>(
  source: string,
  bytesPerValue: number,
  create: (buffer: ArrayBufferLike, byteOffset: number, length: number) => T,
): T {
  const bytes = decodeBase64(source);
  if (bytes.byteLength % bytesPerValue !== 0) throw new Error("Некорректный бинарный буфер STEP-модели.");
  return create(bytes.buffer, bytes.byteOffset, bytes.byteLength / bytesPerValue);
}

function decodeStepModel(model: StepModelSnapshot): DecodedStepModel {
  if (model.encoding !== "typed-buffer-v1") throw new Error("Неподдерживаемый формат STEP-модели.");
  return {
    positions: decodeTypedArray(model.positions, 4, (buffer, offset, length) => new Float32Array(buffer, offset, length)),
    indices: decodeTypedArray(model.indices, 4, (buffer, offset, length) => new Uint32Array(buffer, offset, length)),
    triangleFaceIds: decodeTypedArray(model.triangleFaceIds, 4, (buffer, offset, length) => new Int32Array(buffer, offset, length)),
    edgePoints: decodeTypedArray(model.edgePoints, 4, (buffer, offset, length) => new Float32Array(buffer, offset, length)),
    edgeCells: decodeTypedArray(model.edgeCells, 4, (buffer, offset, length) => new Uint32Array(buffer, offset, length)),
  };
}

function mapStepPositions(source: Float32Array): Float32Array {
  const positions = new Float32Array(source.length);
  for (let index = 0; index < source.length; index += 3) {
    positions[index] = source[index] / 1000;
    positions[index + 1] = source[index + 2] / 1000;
    positions[index + 2] = source[index + 1] / 1000;
  }
  return positions;
}

function edgeSegmentIndices(cells: Uint32Array): Uint32Array {
  let cursor = 0;
  let count = 0;
  while (cursor < cells.length) {
    const pointCount = cells[cursor];
    if (pointCount === undefined || cursor + pointCount >= cells.length) throw new Error("Некорректные рёбра STEP-модели.");
    count += Math.max(0, pointCount - 1);
    cursor += pointCount + 1;
  }
  const indices = new Uint32Array(count * 2);
  cursor = 0;
  let target = 0;
  while (cursor < cells.length) {
    const pointCount = cells[cursor];
    for (let offset = 1; offset < pointCount; offset += 1) {
      indices[target] = cells[cursor + offset];
      indices[target + 1] = cells[cursor + offset + 1];
      target += 2;
    }
    cursor += pointCount + 1;
  }
  return indices;
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
  bounds,
}: {
  preset: CameraPreset;
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
  }, [camera, preset]);
  return null;
}

function FitCamera({ fitRequest, bounds }: { fitRequest: number; bounds: ViewportBounds }) {
  const { camera, size } = useThree();
  const previousRequest = useRef(fitRequest);

  useEffect(() => {
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
  hoveredFace,
  selectedFace,
  onHoverFace,
  onSelectFace,
}: {
  model: StepModelSnapshot;
  hoveredFace: number | null;
  selectedFace: number | null;
  onHoverFace: (faceId: number | null) => void;
  onSelectFace: (faceId: number) => void;
}) {
  const decoded = useMemo(() => decodeStepModel(model), [model]);
  const displayPositions = useMemo(() => mapStepPositions(decoded.positions), [decoded.positions]);
  const geometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(displayPositions, 3));
    result.setIndex(new Uint32BufferAttribute(decoded.indices, 1));
    result.computeVertexNormals();
    return result;
  }, [decoded.indices, displayPositions]);

  const edgeGeometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(mapStepPositions(decoded.edgePoints), 3));
    result.setIndex(new Uint32BufferAttribute(edgeSegmentIndices(decoded.edgeCells), 1));
    return result;
  }, [decoded.edgeCells, decoded.edgePoints]);

  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => () => edgeGeometry.dispose(), [edgeGeometry]);
  const selectable = useMemo(() => new Set(model.selectableFaceIds), [model]);
  const highlightedFace = selectedFace ?? hoveredFace;
  return (
    <group>
      <mesh
        geometry={geometry}
        onPointerMove={(event) => {
          const faceId = typeof event.faceIndex === "number"
            ? decoded.triangleFaceIds[event.faceIndex]
            : undefined;
          onHoverFace(faceId !== undefined && selectable.has(faceId) ? faceId : null);
        }}
        onPointerOut={() => onHoverFace(null)}
        onClick={(event) => {
          const faceId = typeof event.faceIndex === "number"
            ? decoded.triangleFaceIds[event.faceIndex]
            : undefined;
          if (faceId !== undefined && selectable.has(faceId)) {
            event.stopPropagation();
            onSelectFace(faceId);
          }
        }}
      >
        <meshStandardMaterial color="#b8c2cc" transparent opacity={0.2} depthWrite roughness={0.62} metalness={0.1} />
      </mesh>
      <lineSegments geometry={edgeGeometry} renderOrder={2}>
        <lineBasicMaterial color="#31414d" transparent opacity={1} depthTest={true} depthWrite={false} />
      </lineSegments>
      {highlightedFace !== null ? (
        <StepFaceOverlay
          positions={displayPositions}
          indices={decoded.indices}
          triangleFaceIds={decoded.triangleFaceIds}
          faceId={highlightedFace}
          selected={highlightedFace === selectedFace}
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

export default function PalletViewport({
  beams,
  dimensions,
  preset,
  fitRequest,
  stepModel,
  selectedStepFace,
  onSelectStepFace,
  showPallet = true,
  selectedBeams,
  dimensionEditing,
  hoveredDimension,
  onToggleBeam,
  onSelectDimension,
  onHoverDimension,
  insertionMarkers,
  insertionMode,
  selectedSlot,
  onSelectInsertion,
  manualMode = insertionMode,
  manualSupports = [],
    manualSection,
  onSelectManualSupport = () => {},
  manualHud,
  beamSelectionEnabled,
}: {
  beams: ViewportBeam[];
  dimensions: ViewportDimension[];
  preset: CameraPreset;
    fitRequest: number;
    stepModel?: StepModelSnapshot | null;
    selectedStepFace?: number | null;
    onSelectStepFace?: (faceId: number) => void;
    showPallet?: boolean;
  selectedBeams: string[];
  dimensionEditing: boolean;
  hoveredDimension: string | null;
  onToggleBeam: (beam: ViewportBeam, point?: ViewportPoint) => void;
  onSelectDimension: (dimension: ViewportDimension) => void;
  onHoverDimension: (dimension: ViewportDimension | null) => void;
  insertionMarkers: ViewportInsertionMarker[];
  insertionMode: boolean;
  selectedSlot: { layerId: string; afterBeamIndex: number } | null;
  onSelectInsertion: (marker: ViewportInsertionMarker) => void;
  manualMode?: boolean;
  manualSupports?: { beam: ViewportBeam; point: ViewportPoint }[];
    manualSection?: ManualBeamSection;
  onSelectManualSupport?: (beam: ViewportBeam, point: ViewportPoint) => void;
  manualHud?: ReactNode;
  beamSelectionEnabled: boolean;
}) {
  const [cursor, setCursor] = useState<[number, number]>([16, 16]);
  const [hoveredBeam, setHoveredBeam] = useState<string | null>(null);
    const [hoveredStepFace, setHoveredStepFace] = useState<number | null>(null);
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
      if (stepModel) {
        const [xMin, xMax, yMin, yMax, zMin, zMax] = stepModel.bounds;
        const modelMin: [number, number, number] = [xMin / 1000, zMin / 1000, yMin / 1000];
        const modelMax: [number, number, number] = [xMax / 1000, zMax / 1000, yMax / 1000];
        for (let axis = 0; axis < 3; axis += 1) {
          min[axis] = Math.min(min[axis], modelMin[axis]);
          max[axis] = Math.max(max[axis], modelMax[axis]);
        }
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
    return {
      position: (alongX
        ? [first.point[0], bearing + height / 2, (start + end) / 2]
        : [(start + end) / 2, bearing + height / 2, first.point[2]]) as ViewportPoint,
      size: alongX ? [thickness, height, length] as [number, number, number] : [length, height, thickness] as [number, number, number],
    };
  }, [manualSection, manualSupports]);
  return (
    <div className="viewport" onPointerMove={(event) => { const box = event.currentTarget.getBoundingClientRect(); setCursor([event.clientX - box.left + 14, event.clientY - box.top + 14]); }}>
      <Canvas camera={{ position: [5, 4, 5], fov: 42 }}>
          <Camera preset={preset} bounds={bounds} />
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
              if (manualMode) onToggleBeam(beam, point);
              else onToggleBeam(beam, point);
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
              <DimensionLabel
                value={dimension.value}
                position={middle}
                dimension={dimension}
                canEdit={dimensionEditing}
                onSelect={onSelectDimension}
                onHover={onHoverDimension}
              />
            </group>
          );
          }) : null}
        {manualHud && manualSupports[0] ? <Html position={[manualSupports[0].point[0], manualSupports[0].point[1] + 0.24, manualSupports[0].point[2]]} center>{manualHud}</Html> : null}
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
              hoveredFace={hoveredStepFace}
              selectedFace={selectedStepFace ?? null}
              onHoverFace={setHoveredStepFace}
              onSelectFace={(faceId) => onSelectStepFace?.(faceId)}
            />
          ) : null}
      </Canvas>
      {manualMode ? <div className="viewport-hint" style={{ left: cursor[0], top: cursor[1] }}>{manualSupports.length === 0 ? "Select the first support" : manualSupports.length === 1 ? "Select the second support" : "Configure the new beam"}</div> : null}
    </div>
  );
}
