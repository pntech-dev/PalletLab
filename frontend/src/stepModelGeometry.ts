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
  positions: Float32Array;
  indices: Uint32Array;
  triangleFaceIds: Int32Array;
  selectableFaceIds: number[];
  edgePoints: Float32Array;
  edgeCells: Uint32Array;
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

export function prepareStepModel(model: StepModelPayload): StepModelGeometry {
  if (model.encoding !== "typed-buffer-v1") throw new Error("Неподдерживаемый формат STEP-модели.");
  return {
    positions: decodeTypedArray(model.positions, 4, (buffer, offset, length) => new Float32Array(buffer, offset, length)),
    indices: decodeTypedArray(model.indices, 4, (buffer, offset, length) => new Uint32Array(buffer, offset, length)),
    triangleFaceIds: decodeTypedArray(model.triangleFaceIds, 4, (buffer, offset, length) => new Int32Array(buffer, offset, length)),
    selectableFaceIds: model.selectableFaceIds,
    edgePoints: decodeTypedArray(model.edgePoints, 4, (buffer, offset, length) => new Float32Array(buffer, offset, length)),
    edgeCells: decodeTypedArray(model.edgeCells, 4, (buffer, offset, length) => new Uint32Array(buffer, offset, length)),
    bounds: model.bounds,
    transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  };
}
