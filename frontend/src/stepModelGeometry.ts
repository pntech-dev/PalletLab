export type StepModelPayload = {
  encoding: "typed-buffer-v1";
  positions: string;
  indices: string;
  triangleFaceIds: string;
  selectableFaceIds: number[];
  edgePoints: string;
  edgeCells: string;
  bounds: [number, number, number, number, number, number];
};

export type StepModelGeometry = {
  displayPositions: Float32Array;
  indices: Uint32Array;
  triangleFaceIds: Int32Array;
  selectableFaceIds: number[];
  displayEdgePositions: Float32Array;
  edgeIndices: Uint32Array;
  bounds: [number, number, number, number, number, number];
  transform: number[];
};

function decodeBase64(source: string): Uint8Array {
  const text = window.atob(source);
  const result = new Uint8Array(text.length);
  for (let index = 0; index < text.length; index += 1) result[index] = text.charCodeAt(index);
  return result;
}

function decodeTypedArray<T extends Float32Array | Uint32Array | Int32Array>(
  source: string,
  bytesPerValue: number,
  create: (buffer: ArrayBufferLike, byteOffset: number, length: number) => T,
): T {
  const bytes = decodeBase64(source);
  if (bytes.byteLength % bytesPerValue !== 0) throw new Error("Некорректный бинарный буфер STEP-модели.");
  return create(bytes.buffer, bytes.byteOffset, bytes.byteLength / bytesPerValue);
}

function mapStepPositions(source: Float32Array): Float32Array {
  const positions = new Float32Array(source.length);
  for (let index = 0; index < source.length; index += 3) {
    positions[index] = source[index] / 1000;
    positions[index + 1] = source[index + 2] / 1000;
    positions[index + 2] = source[index + 1] / 1000;
  }
  return positions;
}

function edgeSegmentIndices(cells: Uint32Array): Uint32Array {
  let cursor = 0;
  let count = 0;
  while (cursor < cells.length) {
    const pointCount = cells[cursor];
    if (pointCount === undefined || cursor + pointCount >= cells.length) throw new Error("Некорректные рёбра STEP-модели.");
    count += Math.max(0, pointCount - 1);
    cursor += pointCount + 1;
  }
  const indices = new Uint32Array(count * 2);
  cursor = 0;
  let target = 0;
  while (cursor < cells.length) {
    const pointCount = cells[cursor];
    for (let offset = 1; offset < pointCount; offset += 1) {
      indices[target] = cells[cursor + offset];
      indices[target + 1] = cells[cursor + offset + 1];
      target += 2;
    }
    cursor += pointCount + 1;
  }
  return indices;
}

export function prepareStepModel(model: StepModelPayload): StepModelGeometry {
  if (model.encoding !== "typed-buffer-v1") throw new Error("Неподдерживаемый формат STEP-модели.");
  const positions = decodeTypedArray(model.positions, 4, (buffer, offset, length) => new Float32Array(buffer, offset, length));
  const edgePoints = decodeTypedArray(model.edgePoints, 4, (buffer, offset, length) => new Float32Array(buffer, offset, length));
  const edgeCells = decodeTypedArray(model.edgeCells, 4, (buffer, offset, length) => new Uint32Array(buffer, offset, length));
  return {
    displayPositions: mapStepPositions(positions),
    indices: decodeTypedArray(model.indices, 4, (buffer, offset, length) => new Uint32Array(buffer, offset, length)),
    triangleFaceIds: decodeTypedArray(model.triangleFaceIds, 4, (buffer, offset, length) => new Int32Array(buffer, offset, length)),
    selectableFaceIds: model.selectableFaceIds,
    displayEdgePositions: mapStepPositions(edgePoints),
    edgeIndices: edgeSegmentIndices(edgeCells),
    bounds: model.bounds,
    transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  };
}
