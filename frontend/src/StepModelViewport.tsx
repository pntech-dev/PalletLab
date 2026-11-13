import { useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { useThree } from "@react-three/fiber";
import {
  acceleratedRaycast,
  computeBoundsTree,
  disposeBoundsTree,
  type MeshBVHOptions,
} from "three-mesh-bvh";
import {
  BufferGeometry,
  DoubleSide,
  Float32BufferAttribute,
  Matrix4,
  Mesh,
  Raycaster,
  Uint32BufferAttribute,
  Vector2,
} from "three";

import type { StepModelGeometry } from "./stepModelGeometry";
import { createStepFaceOverlayGeometry, createStepFaceOverlayMaterial, indexStepFaceRanges, type StepFaceRange } from "./stepFaceGeometry";

export type StepFacePickerRef = MutableRefObject<
  ((clientX: number, clientY: number, bounds: DOMRect) => void) | null
>;

export default function StepModelViewport({
  model,
  selectedFace,
  onSelectFace,
  selectionEnabled,
  pickerRef,
  opacity,
}: {
  model: StepModelGeometry;
  selectedFace: number | null;
  onSelectFace: (faceId: number) => void;
  selectionEnabled: boolean;
  pickerRef: StepFacePickerRef;
  opacity: number;
}) {
  const meshRef = useRef<Mesh>(null);
  const [hoveredFace, setHoveredFace] = useState<number | null>(null);
  const { camera, gl } = useThree();
  const transform = useMemo(() => new Matrix4().fromArray(model.transform), [model.transform]);
  const selectableFaces = useMemo(() => new Set(model.selectableFaceIds), [model.selectableFaceIds]);
  const faceRanges = useMemo(() => indexStepFaceRanges(model.triangleFaceIds), [model.triangleFaceIds]);
  const selection = useRef({ enabled: selectionEnabled, onSelectFace });
  selection.current = { enabled: selectionEnabled, onSelectFace };
  const geometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(model.displayPositions, 3));
    result.setIndex(new Uint32BufferAttribute(model.indices, 1));
    result.computeVertexNormals();
    result.computeBoundingSphere();
    result.computeBoundsTree = computeBoundsTree;
    result.disposeBoundsTree = disposeBoundsTree;
    const boundsTreeOptions: MeshBVHOptions & { indirect: true } = { indirect: true };
    result.computeBoundsTree(boundsTreeOptions);
    return result;
  }, [model.displayPositions, model.indices]);
  const edgeGeometry = useMemo(() => {
    const result = new BufferGeometry();
    result.setAttribute("position", new Float32BufferAttribute(model.displayEdgePositions, 3));
    result.setIndex(new Uint32BufferAttribute(model.edgeIndices, 1));
    result.computeBoundingSphere();
    return result;
  }, [model.displayEdgePositions, model.edgeIndices]);

  useEffect(() => () => {
    geometry.disposeBoundsTree();
    geometry.dispose();
  }, [geometry]);
  useEffect(() => () => edgeGeometry.dispose(), [edgeGeometry]);
  useEffect(() => {
    const mesh = meshRef.current;
    if (mesh) mesh.raycast = acceleratedRaycast;
  }, [geometry]);
  useEffect(() => {
    const raycaster = new Raycaster();
    raycaster.firstHitOnly = true;
    const pointer = new Vector2();
    const pickFace = (clientX: number, clientY: number, bounds: DOMRect): number | undefined => {
      const mesh = meshRef.current;
      if (!mesh || bounds.width <= 0 || bounds.height <= 0) return undefined;
      pointer.set(
        ((clientX - bounds.left) / bounds.width) * 2 - 1,
        -((clientY - bounds.top) / bounds.height) * 2 + 1,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObject(mesh, false)[0];
      return typeof hit?.faceIndex === "number" ? model.triangleFaceIds[hit.faceIndex] : undefined;
    };
    pickerRef.current = (clientX, clientY, bounds) => {
      if (!selection.current.enabled) return;
      const faceId = pickFace(clientX, clientY, bounds);
      if (faceId !== undefined && selectableFaces.has(faceId)) selection.current.onSelectFace(faceId);
    };
    const canvas = gl.domElement;
    let frame: number | null = null;
    let latestPointer: { x: number; y: number } | null = null;
    const clearHover = () => {
      latestPointer = null;
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      setHoveredFace(null);
    };
    const handlePointerMove = (event: PointerEvent) => {
      if (!selectionEnabled) return;
      if (event.buttons !== 0) { clearHover(); return; }
      latestPointer = { x: event.clientX, y: event.clientY };
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        if (!latestPointer) return;
        const faceId = pickFace(latestPointer.x, latestPointer.y, canvas.getBoundingClientRect());
        setHoveredFace(faceId !== undefined && faceRanges.has(faceId) ? faceId : null);
      });
    };
    canvas.addEventListener("pointermove", handlePointerMove, true);
    canvas.addEventListener("pointerleave", clearHover);
    return () => {
      pickerRef.current = null;
      if (frame !== null) cancelAnimationFrame(frame);
      canvas.removeEventListener("pointermove", handlePointerMove, true);
      canvas.removeEventListener("pointerleave", clearHover);
    };
  }, [camera, faceRanges, gl, model.triangleFaceIds, pickerRef, selectableFaces, selectionEnabled]);
  useEffect(() => { if (!selectionEnabled) setHoveredFace(null); }, [selectionEnabled]);
  useEffect(() => setHoveredFace(null), [model.displayPositions, model.indices, model.triangleFaceIds]);
  const selectedFaceRange = selectedFace === null ? undefined : faceRanges.get(selectedFace);
  const hoveredFaceRange = hoveredFace === null ? undefined : faceRanges.get(hoveredFace);
  return (
    <group matrix={transform} matrixAutoUpdate={false}>
      <mesh ref={meshRef} geometry={geometry}>
        <meshStandardMaterial
          color="#b8c2cc"
          transparent
          opacity={opacity}
          depthWrite
          roughness={0.62}
          metalness={0.1}
          side={DoubleSide}
        />
      </mesh>
      <lineSegments geometry={edgeGeometry} renderOrder={2}>
        <lineBasicMaterial color="#31414d" transparent opacity={Math.min(1, opacity * 5)} depthTest={true} depthWrite={false} />
      </lineSegments>
      <StepFaceOverlay source={geometry} faceRange={selectedFaceRange} hovered={false} />
      <StepFaceOverlay source={geometry} faceRange={selectionEnabled && hoveredFace !== selectedFace ? hoveredFaceRange : undefined} hovered />
    </group>
  );
}

function StepFaceOverlay({ source, faceRange, hovered }: {
  source: BufferGeometry;
  faceRange: StepFaceRange | undefined;
  hovered: boolean;
}) {
  const geometry = useMemo(() => createStepFaceOverlayGeometry(source), [source]);
  const material = useMemo(() => createStepFaceOverlayMaterial(hovered), [hovered]);
  const invalidate = useThree((state) => state.invalidate);
  useLayoutEffect(() => {
    if (faceRange) geometry.setDrawRange(faceRange.start * 3, faceRange.count * 3);
    invalidate();
  }, [faceRange, geometry, invalidate]);
  useEffect(() => () => { geometry.dispose(); }, [geometry]);
  useEffect(() => () => { material.dispose(); }, [material]);
  return <mesh geometry={geometry} material={material} visible={!!faceRange} renderOrder={3} />;
}
