import { Html, Line, OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useEffect } from "react";

export type ViewportBeam = {
  index: number;
  layerId: string;
  layerIndex: number;
  center: [number, number, number];
  size: [number, number, number];
};
export type CameraPreset = "isometric" | "top" | "front" | "side";
export type ViewportDimension = {
  layerId: string; axis: "length" | "width"; index: number; editValue: number | null; editable: boolean;
  value: number; start: [number, number, number]; end: [number, number, number];
  startExtension: [number, number, number] | null; endExtension: [number, number, number] | null;
};

function point([x, y, z]: [number, number, number]): [number, number, number] { return [x / 1000, z / 1000, y / 1000]; }

function Camera({ preset }: { preset: CameraPreset }) {
  const { camera } = useThree();
  useEffect(() => {
    const positions: Record<CameraPreset, [number, number, number]> = { isometric: [5, 4, 5], top: [0, 6, 0.001], front: [0, -6, 0], side: [-6, 0, 0] };
    camera.position.set(...positions[preset]); camera.lookAt(0, 0, 0);
  }, [camera, preset]);
  return null;
}

function DimensionHitArea({ dimension, start, end, middle, onSelect }: {
  dimension: ViewportDimension;
  start: [number, number, number];
  end: [number, number, number];
  middle: [number, number, number];
  onSelect: (dimension: ViewportDimension) => void;
}) {
  const length = Math.hypot(end[0] - start[0], end[1] - start[1], end[2] - start[2]);
  // The rendered line is intentionally thin. This invisible cuboid covers its
  // full length and gives it a reliable 160 mm hit target on every DPI scale.
  const size: [number, number, number] = dimension.axis === "length"
    ? [length, 0.16, 0.16]
    : [0.16, 0.16, length];
  return <mesh position={middle} onClick={(event) => { event.stopPropagation(); onSelect(dimension); }}>
    <boxGeometry args={size} />
    <meshBasicMaterial transparent opacity={0} depthWrite={false} />
  </mesh>;
}

export default function PalletViewport({ beams, dimensions, preset, selectedBeams, onToggleBeam, onSelectDimension }: { beams: ViewportBeam[]; dimensions: ViewportDimension[]; preset: CameraPreset; selectedBeams: string[]; onToggleBeam: (beam: ViewportBeam) => void; onSelectDimension: (dimension: ViewportDimension) => void }) {
  return <div className="viewport"><Canvas camera={{ position: [5, 4, 5], fov: 42 }}>
    <Camera preset={preset} />
    <color attach="background" args={["#edf1f3"]} />
    <ambientLight intensity={1.5} />
    <directionalLight position={[5, 8, 4]} intensity={2} castShadow />
    <gridHelper args={[10, 20, "#aab9c1", "#d9e1e5"]} />
    {beams.map((beam) => <mesh key={`${beam.layerId}:${beam.index}`} position={[beam.center[0] / 1000, beam.center[2] / 1000, beam.center[1] / 1000]} onClick={(event) => { event.stopPropagation(); onToggleBeam(beam); }}>
      <boxGeometry args={[beam.size[0] / 1000, beam.size[2] / 1000, beam.size[1] / 1000]} />
      <meshStandardMaterial color={selectedBeams.includes(`${beam.layerId}:${beam.layerIndex}`) ? "#d83a3a" : "#b88254"} roughness={0.72} />
    </mesh>)}
    {dimensions.map((dimension, index) => {
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
        <Line points={[start, end]} color={dimension.editable ? "#315b6c" : "#718087"} lineWidth={dimension.editable ? 2 : 1.5} />
        <Line points={arrow(start, 1)} color="#315b6c" lineWidth={1.5} />
        <Line points={arrow(end, -1)} color="#315b6c" lineWidth={1.5} />
        {dimension.editable ? <DimensionHitArea dimension={dimension} start={start} end={end} middle={middle} onSelect={onSelectDimension} /> : null}
        <Html position={middle} center occlude={false} zIndexRange={[1000000, 1000]} style={{ pointerEvents: "none" }}>
          <span className="dimension-label">{dimension.value.toFixed(0)}</span>
        </Html>
      </group>;
    })}
    <OrbitControls makeDefault />
  </Canvas></div>;
}
