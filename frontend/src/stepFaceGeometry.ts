import { BufferGeometry, DoubleSide, MeshBasicMaterial } from "three";

export type StepFaceRange = { start: number; count: number };

/** STEP import stores the triangles of each CAD face together. */
export function indexStepFaceRanges(faceIds: Int32Array): Map<number, StepFaceRange> {
  const ranges = new Map<number, StepFaceRange>();
  for (let start = 0; start < faceIds.length;) {
    const faceId = faceIds[start];
    let end = start + 1;
    while (end < faceIds.length && faceIds[end] === faceId) end += 1;
    if (faceId >= 0) ranges.set(faceId, { start, count: end - start });
    start = end;
  }
  return ranges;
}

/** Share the model's GPU buffers and draw only the selected triangle range. */
export function createStepFaceOverlayGeometry(source: BufferGeometry): BufferGeometry {
  const overlay = new BufferGeometry();
  overlay.setAttribute("position", source.getAttribute("position"));
  overlay.setIndex(source.getIndex());
  overlay.boundingSphere = source.boundingSphere;
  return overlay;
}

export function createStepFaceOverlayMaterial(hovered: boolean): MeshBasicMaterial {
  return new MeshBasicMaterial({ color: hovered ? "#ffeb3b" : "#e64231", transparent: true,
    opacity: hovered ? 0.9 : 0.78, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2,
    side: DoubleSide });
}
