/** Historical STEP-built pallets use three standard 70 mm layers. */
export const LEGACY_STEP_BEARING_HEIGHT = 210;

export type StepPlacement = {
  transform: number[];
  starts: [number, number];
  bearingHeight: number;
};

/** Align the model with the current pallet while preserving its original orientation. */
export function stepViewportTransform(placement: StepPlacement, margins: readonly number[], palletHeight: number): number[] {
  const transform = [...placement.transform];
  transform[12] += (margins[0] - placement.starts[0]) / 1000;
  transform[13] += (palletHeight - placement.bearingHeight) / 1000;
  transform[14] += (margins[2] - placement.starts[1]) / 1000;
  return transform;
}
