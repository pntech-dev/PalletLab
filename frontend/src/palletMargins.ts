import type { Direction, Project } from "./App";

export type Margins = [number, number, number, number];
export type MarginIndex = 0 | 1 | 2 | 3;

export function palletMargins(project: Project): Margins {
  const saved = project.pallet.pallet_margins;
  if (saved?.length === 4) return [...saved];
  if (saved?.length === 2) return [saved[0], saved[1], saved[0], saved[1]];
  const length = project.pallet.layers.find((layer) => layer.axis === "length")?.direction ?? project.pallet.length;
  const width = project.pallet.layers.find((layer) => layer.axis === "width")?.direction ?? project.pallet.width;
  return [length.margin_start, length.margin_end, width.margin_start, width.margin_end];
}

export function marginLinks(project: Project): [boolean, boolean] {
  if (project.pallet.pallet_margin_links) return [...project.pallet.pallet_margin_links];
  const margins = palletMargins(project);
  return [margins[0] === margins[1], margins[2] === margins[3]];
}

/** Shift an axis by its envelope changes, preserving legacy layer grids. */
export function changePalletMargin(project: Project, index: MarginIndex, next: number): Project {
  const pallet = project.pallet;
  const old = palletMargins(project);
  const margins: Margins = [...old];
  const links = marginLinks(project);
  margins[index] = next;
  if (index === 0 && links[0]) margins[1] = next;
  if (index === 2 && links[1]) margins[3] = next;
  const deltas = margins.map((value, i) => value - old[i]);
  const shift = (direction: Direction, axis: "length" | "width"): Direction => {
    const offset = axis === "length" ? 0 : 2;
    const start = deltas[offset];
    return {
      ...direction,
      margin_start: direction.margin_start + start,
      margin_end: direction.margin_end + deltas[offset + 1],
      support_positions: direction.support_positions?.map((position) => position + start) ?? direction.support_positions,
    };
  };
  return { ...project, pallet: {
    ...pallet,
    pallet_margins: margins,
    pallet_margin_links: links,
    length: shift(pallet.length, "length"),
    width: shift(pallet.width, "width"),
    layers: pallet.layers.map((layer) => ({ ...layer, direction: shift(layer.direction, layer.axis) })),
    manual_beams: pallet.manual_beams?.map((beam) => ({
      ...beam,
      start_point: beam.start_point
        ? [beam.start_point[0] + deltas[0], beam.start_point[1] + deltas[2], beam.start_point[2]]
        : beam.start_point,
    })),
  } };
}

export function toggleMarginLink(project: Project, pair: 0 | 1): Project {
  const links = marginLinks(project);
  links[pair] = !links[pair];
  let result: Project = { ...project, pallet: { ...project.pallet, pallet_margin_links: links } };
  if (links[pair]) {
    const margins = palletMargins(result);
    const first = pair === 0 ? 0 : 2;
    result = changePalletMargin(result, first, margins[first]);
  }
  return result;
}
