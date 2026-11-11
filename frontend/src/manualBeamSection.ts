import type { ViewportBeam } from "./PalletViewport";

export type BeamSection = { height: number; width: number };

type LayerSection = { id: string; direction: { beam_height: number; beam_width: number } };

/** Manual beams are placed in the layer above their support. */
export function manualSectionForSupport(
  layers: readonly LayerSection[], beam: ViewportBeam | null | undefined, fallback: BeamSection,
): BeamSection {
  const index = beam ? layers.findIndex((layer) => layer.id === beam.physicalLayerId) : -1;
  const target = index >= 0 ? layers[index + 1] : undefined;
  return target ? { height: target.direction.beam_height, width: target.direction.beam_width } : fallback;
}
