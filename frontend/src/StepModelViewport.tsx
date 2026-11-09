import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import { useThree } from "@react-three/fiber";
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

export type StepFacePickerRef = MutableRefObject<
  ((clientX: number, clientY: number, bounds: DOMRect) => void) | null
>;

export default function StepModelViewport({
  model,
  selectedFace,
  onSelectFace,
  selectionEnabled,
  pickerRef,
}: {
  model: StepModelGeometry;
  selectedFace: number | null;
  onSelectFace: (faceId: number) => void;
  selectionEnabled: boolean;
  pickerRef: StepFacePickerRef;
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
        <meshStandardMaterial
          color="#b8c2cc"
          transparent
          opacity={0.2}
          depthWrite
          roughness={0.62}
          metalness={0.1}
          side={DoubleSide}
        />
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
}: {
  positions: Float32Array;
  indices: Uint32Array;
  triangleFaceIds: Int32Array;
  faceId: number;
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
      <meshBasicMaterial color="#e64231" transparent opacity={0.78} depthWrite={false} polygonOffset polygonOffsetFactor={-2} />
    </mesh>
  );
}
