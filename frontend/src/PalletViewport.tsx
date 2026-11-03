import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";

export type ViewportBeam = {
  index: number;
  layerId: string;
  center: [number, number, number];
  size: [number, number, number];
};

export default function PalletViewport({ beams }: { beams: ViewportBeam[] }) {
  return <div className="viewport"><Canvas camera={{ position: [5, 4, 5], fov: 42 }}>
    <color attach="background" args={["#edf1f3"]} />
    <ambientLight intensity={1.5} />
    <directionalLight position={[5, 8, 4]} intensity={2} castShadow />
    <gridHelper args={[10, 20, "#aab9c1", "#d9e1e5"]} />
    {beams.map((beam) => <mesh key={`${beam.layerId}:${beam.index}`} position={beam.center.map((value) => value / 1000) as [number, number, number]}>
      <boxGeometry args={beam.size.map((value) => value / 1000) as [number, number, number]} />
      <meshStandardMaterial color="#b88254" roughness={0.72} />
    </mesh>)}
    <OrbitControls makeDefault />
  </Canvas></div>;
}
