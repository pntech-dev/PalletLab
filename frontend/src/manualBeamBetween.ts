import type { ViewportBeam } from "./PalletViewport";

export type BeamReferenceFace = "x_min" | "x_max" | "y_min" | "y_max";
export type BeamReference = { beam: ViewportBeam; face: BeamReferenceFace };

export function faceCoordinate({ beam, face }: BeamReference): number {
  const axis = face.startsWith("x_") ? 0 : 1;
  return beam.center[axis] + (face.endsWith("max") ? 1 : -1) * beam.size[axis] / 2;
}

export function betweenFaces(first: BeamReference, second: BeamReference, beamWidth: number): { center: number; baseDistance: number } | null {
  if (first.beam.layerId === second.beam.layerId && first.beam.layerIndex === second.beam.layerIndex) return null;
  if (first.face[0] !== second.face[0] || first.face.endsWith("max") === second.face.endsWith("max")) return null;
  const a = faceCoordinate(first), b = faceCoordinate(second);
  if ((first.face.endsWith("max") ? a >= b : a <= b) || Math.abs(b - a) < beamWidth) return null;
  const center = (a + b) / 2;
  return { center, baseDistance: center - (center >= 0 ? beamWidth / 2 : -beamWidth / 2) };
}
