import { Line, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { CanvasTexture, LinearFilter } from "three";
import { useEffect, useMemo } from "react";

export type ViewportBeam = {
  index: number;
  layerId: string;
  layerIndex: number;
  center: [number, number, number];
  size: [number, number, number];
};
export type ViewportPoint = [number, number, number];
export type CameraPreset = "isometric" | "top" | "front" | "side";
export type ViewportDimension = {
  layerId: string; axis: "length" | "width"; index: number; editValue: number | null; editable: boolean;
  value: number; start: [number, number, number]; end: [number, number, number];
  startExtension: [number, number, number] | null; endExtension: [number, number, number] | null;
};
export type ViewportInsertionMarker = {
  slot: { axis: "length" | "width"; layerId: string; afterBeamIndex: number; maximumClearGap: number; suggestedClearGap: number };
  center: [number, number, number]; size: number;
  preview: { center: [number, number, number]; size: [number, number, number] };
};

function point([x, y, z]: [number, number, number]): [number, number, number] { return [x / 1000, z / 1000, y / 1000]; }

type ViewportBounds = { center: [number, number, number]; span: number };

function Camera({ preset, bounds }: { preset: CameraPreset; bounds: ViewportBounds }) {
  const { camera } = useThree();
  useEffect(() => {
    const [x, y, z] = bounds.center;
    const distance = Math.max(3, bounds.span * 1.45);
    const positions: Record<CameraPreset, [number, number, number]> = {
      isometric: [x + distance, y + distance * 0.75, z + distance],
      top: [x, y + distance * 1.35, z + 0.001],
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

function DimensionHitArea({ dimension, start, end, middle, onSelect, onHover }: {
  dimension: ViewportDimension;
  start: [number, number, number];
  end: [number, number, number];
  middle: [number, number, number];
  onSelect: (dimension: ViewportDimension) => void;
  onHover: (dimension: ViewportDimension | null) => void;
}) {
  const length = Math.hypot(end[0] - start[0], end[1] - start[1], end[2] - start[2]);
  // The rendered line is intentionally thin. This invisible cuboid covers its
  // full length and gives it a reliable 160 mm hit target on every DPI scale.
  const size: [number, number, number] = dimension.axis === "length"
    ? [length, 0.16, 0.16]
    : [0.16, 0.16, length];
  return <mesh position={middle} onClick={(event) => { event.stopPropagation(); onSelect(dimension); }}
    onPointerOver={(event) => { event.stopPropagation(); onHover(dimension); }} onPointerOut={() => onHover(null)}>
    <boxGeometry args={size} />
    <meshBasicMaterial transparent opacity={0} depthWrite={false} />
  </mesh>;
}

function DimensionLabel({ value, position, dimension, canEdit, onSelect, onHover }: {
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
    if (!context) throw new Error("Canvas 2D is unavailable for dimension labels.");
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
  return <sprite position={position} scale={[0.30, 0.12, 1]} renderOrder={10}
    onClick={(event) => { event.stopPropagation(); if (canEdit && dimension.editable) onSelect(dimension); }}
    onPointerOver={(event) => { if (canEdit && dimension.editable) { event.stopPropagation(); onHover(dimension); } }}
    onPointerOut={() => onHover(null)}>
    <spriteMaterial map={texture} transparent depthTest={false} depthWrite={false} />
  </sprite>;
}

export default function PalletViewport({ beams, dimensions, preset, selectedBeams, dimensionEditing, hoveredDimension, onToggleBeam, onSelectDimension, onHoverDimension, insertionMarkers, insertionMode, selectedSlot, onSelectInsertion, manualMode = insertionMode, manualSupports = [], onSelectManualSupport = () => {} }: { beams: ViewportBeam[]; dimensions: ViewportDimension[]; preset: CameraPreset; selectedBeams: string[]; dimensionEditing: boolean; hoveredDimension: string | null; onToggleBeam: (beam: ViewportBeam, point?: ViewportPoint) => void; onSelectDimension: (dimension: ViewportDimension) => void; onHoverDimension: (dimension: ViewportDimension | null) => void; insertionMarkers: ViewportInsertionMarker[]; insertionMode: boolean; selectedSlot: { layerId: string; afterBeamIndex: number } | null; onSelectInsertion: (marker: ViewportInsertionMarker) => void; manualMode?: boolean; manualSupports?: { beam: ViewportBeam; point: ViewportPoint }[]; onSelectManualSupport?: (beam: ViewportBeam, point: ViewportPoint) => void }) {
  const bounds = useMemo(() => {
    const min = [Infinity, Infinity, Infinity]; const max = [-Infinity, -Infinity, -Infinity];
    for (const beam of beams) {
      const center: [number, number, number] = [beam.center[0] / 1000, beam.center[2] / 1000, beam.center[1] / 1000];
      const size: [number, number, number] = [beam.size[0] / 1000, beam.size[2] / 1000, beam.size[1] / 1000];
      for (let axis = 0; axis < 3; axis += 1) {
        min[axis] = Math.min(min[axis], center[axis] - size[axis] / 2);
        max[axis] = Math.max(max[axis], center[axis] + size[axis] / 2);
      }
    }
    const center = min.map((value, axis) => (value + max[axis]) / 2) as [number, number, number];
    return { center, span: Math.max(...max.map((value, axis) => value - min[axis])) };
  }, [beams]);
  const grid = useMemo(() => {
    const length = Math.max(...beams.map((beam) => beam.center[0] + beam.size[0] / 2)) / 1000;
    const width = Math.max(...beams.map((beam) => beam.center[1] + beam.size[1] / 2)) / 1000;
    const section = 0.5;
    const size = Math.max(10, Math.ceil((Math.max(length, width) + section * 4) / section) * section);
    return { size, divisions: Math.round(size / section), position: [length / 2, 0, width / 2] as [number, number, number] };
  }, [beams]);
  return <div className="viewport"><Canvas camera={{ position: [5, 4, 5], fov: 42 }}>
    <Camera preset={preset} bounds={bounds} />
    <color attach="background" args={["#edf1f3"]} />
    <ambientLight intensity={1.5} />
    <directionalLight position={[5, 8, 4]} intensity={2} castShadow />
    <gridHelper args={[grid.size, grid.divisions, "#aab9c1", "#d9e1e5"]} position={grid.position} />
    {beams.map((beam) => <mesh key={`${beam.layerId}:${beam.index}`} position={[beam.center[0] / 1000, beam.center[2] / 1000, beam.center[1] / 1000]} onClick={(event) => { event.stopPropagation(); const point: ViewportPoint = [event.point.x, event.point.y, event.point.z]; if (manualMode) onToggleBeam(beam, point); else onToggleBeam(beam, point); }}>
      <boxGeometry args={[beam.size[0] / 1000, beam.size[2] / 1000, beam.size[1] / 1000]} />
      <meshStandardMaterial color={selectedBeams.includes(`${beam.layerId}:${beam.layerIndex}`) ? "#d83a3a" : "#b88254"} roughness={0.72} />
    </mesh>)}
    {manualSupports.map(({ beam, point }) => <mesh key={`manual-point:${beam.layerId}:${beam.layerIndex}`} position={point}>
      <sphereGeometry args={[0.07, 16, 12]} /><meshStandardMaterial color="#e07822" emissive="#7a3307" />
    </mesh>)}
    {false ? insertionMarkers.map((marker) => {
      const selected = selectedSlot?.layerId === marker.slot.layerId && selectedSlot?.afterBeamIndex === marker.slot.afterBeamIndex;
      return <group key={`${marker.slot.layerId}:${marker.slot.afterBeamIndex}`}>
        <mesh position={[marker.center[0] / 1000, marker.center[2] / 1000, marker.center[1] / 1000]} onClick={(event) => { event.stopPropagation(); onSelectInsertion(marker); }}>
          <sphereGeometry args={[marker.size / 1000, 16, 12]} />
          <meshStandardMaterial color={selected ? "#e07822" : "#269e6b"} emissive={selected ? "#7a3307" : "#0e5638"} />
        </mesh>
        {selected ? <mesh position={[marker.preview.center[0] / 1000, marker.preview.center[2] / 1000, marker.preview.center[1] / 1000]}>
          <boxGeometry args={[marker.preview.size[0] / 1000, marker.preview.size[2] / 1000, marker.preview.size[1] / 1000]} /><meshStandardMaterial color="#269e6b" transparent opacity={0.45} />
        </mesh> : null}
      </group>;
    }) : null}
    {dimensions.map((dimension, index) => {
      const dimensionKey = `${dimension.layerId}:${dimension.index}`;
      const isHovered = dimensionEditing && hoveredDimension === dimensionKey;
      const start = point(dimension.start); const end = point(dimension.end);
      const middle: [number, number, number] = [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2, (start[2] + end[2]) / 2];
      const length = Math.hypot(end[0] - start[0], end[1] - start[1], end[2] - start[2]);
      const scale = Math.min(0.06, length / 5);
      const unit: [number, number, number] = [(end[0] - start[0]) / length, (end[1] - start[1]) / length, (end[2] - start[2]) / length];
      const side: [number, number, number] = Math.abs(unit[1]) < 0.9 ? [-unit[2], 0, unit[0]] : [unit[1], -unit[0], 0];
      const arrow = (origin: [number, number, number], direction: number) => [
        [origin[0] + (unit[0] * direction + side[0]) * scale, origin[1] + (unit[1] * direction + side[1]) * scale, origin[2] + (unit[2] * direction + side[2]) * scale],
        origin,
        [origin[0] + (unit[0] * direction - side[0]) * scale, origin[1] + (unit[1] * direction - side[1]) * scale, origin[2] + (unit[2] * direction - side[2]) * scale],
      ] as [number, number, number][];
      return <group key={index}>
        {dimension.startExtension ? <Line points={[point(dimension.startExtension), start]} color="#315b6c" lineWidth={1} /> : null}
        {dimension.endExtension ? <Line points={[point(dimension.endExtension), end]} color="#315b6c" lineWidth={1} /> : null}
        <Line points={[start, end]} color={isHovered ? "#e07822" : dimension.editable ? "#315b6c" : "#718087"} lineWidth={isHovered ? 3 : dimension.editable ? 2 : 1.5} />
        <Line points={arrow(start, 1)} color="#315b6c" lineWidth={1.5} />
        <Line points={arrow(end, -1)} color="#315b6c" lineWidth={1.5} />
        {dimensionEditing && dimension.editable ? <DimensionHitArea dimension={dimension} start={start} end={end} middle={middle} onSelect={onSelectDimension} onHover={onHoverDimension} /> : null}
        <DimensionLabel value={dimension.value} position={middle} dimension={dimension} canEdit={dimensionEditing} onSelect={onSelectDimension} onHover={onHoverDimension} />
      </group>;
    })}
    <OrbitControls makeDefault target={bounds.center} />
  </Canvas></div>;
}
