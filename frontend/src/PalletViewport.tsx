import { OrbitControls } from "@react-three/drei";
import { Canvas, useThree } from "@react-three/fiber";
import { useEffect } from "react";

export type ViewportBeam = {
  index: number;
  layerId: string;
  center: [number, number, number];
  size: [number, number, number];
};
export type CameraPreset = "isometric" | "top" | "front" | "side";

function Camera({ preset }: { preset: CameraPreset }) {
  const { camera } = useThree();
  useEffect(() => {
    const positions: Record<CameraPreset, [number, number, number]> = { isometric: [5, 4, 5], top: [0, 6, 0.001], front: [0, -6, 0], side: [-6, 0, 0] };
    camera.position.set(...positions[preset]); camera.lookAt(0, 0, 0);
  }, [camera, preset]);
  return null;
}

export default function PalletViewport({ beams, preset }: { beams: ViewportBeam[]; preset: CameraPreset }) {
  return <div className="viewport"><Canvas camera={{ position: [5, 4, 5], fov: 42 }}>
    <Camera preset={preset} />
    <color attach="background" args={["#edf1f3"]} />
    <ambientLight intensity={1.5} />
    <directionalLight position={[5, 8, 4]} intensity={2} castShadow />
    <gridHelper args={[10, 20, "#aab9c1", "#d9e1e5"]} />
    {beams.map((beam) => <mesh key={`${beam.layerId}:${beam.index}`} position={[beam.center[0] / 1000, beam.center[2] / 1000, beam.center[1] / 1000]}>
      <boxGeometry args={[beam.size[0] / 1000, beam.size[2] / 1000, beam.size[1] / 1000]} />
      <meshStandardMaterial color="#b88254" roughness={0.72} />
    </mesh>)}
    <OrbitControls makeDefault />
  </Canvas></div>;
}
