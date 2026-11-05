export type StepModelPayload = { assetUrl: string };

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

type AssetHeader = {
  version: number;
  bounds: [number, number, number, number, number, number];
  buffers: Record<string, { offset: number; byteLength: number; dtype: string }>;
};

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

export async function prepareStepModel(model: StepModelPayload): Promise<StepModelGeometry> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 30_000);
  let response: Response;
  try {
    response = await fetch(model.assetUrl, { cache: "no-store", signal: controller.signal });
  } catch (error) {
    throw new Error(error instanceof Error && error.name === "AbortError"
      ? "Превышено время ожидания бинарной STEP-модели."
      : "Не удалось загрузить бинарную STEP-модель.");
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) throw new Error("Не удалось получить бинарную геометрию STEP-модели.");
  const asset = await response.arrayBuffer();
  const bytes = new Uint8Array(asset);
  if (new TextDecoder().decode(bytes.slice(0, 8)) !== "PLSTEP01") throw new Error("Некорректный бинарный формат STEP-модели.");
  const headerLength = new DataView(asset, 8, 4).getUint32(0, true);
  const headerStart = 12;
  const header = JSON.parse(new TextDecoder().decode(bytes.slice(headerStart, headerStart + headerLength))) as AssetHeader;
  if (header.version !== 1) throw new Error("Неподдерживаемая версия STEP-геометрии.");
  const dataStart = headerStart + headerLength + ((4 - (headerLength % 4)) % 4);
  const buffer = <T extends Float32Array | Uint32Array | Int32Array>(
    name: string, create: (data: ArrayBuffer, offset: number, length: number) => T,
  ): T => {
    const entry = header.buffers[name];
    if (!entry || entry.byteLength % 4 !== 0) throw new Error("Некорректный буфер STEP-модели.");
    return create(asset, dataStart + entry.offset, entry.byteLength / 4);
  };
  const positions = buffer("positions", (data, offset, length) => new Float32Array(data, offset, length));
  const edgePoints = buffer("edgePoints", (data, offset, length) => new Float32Array(data, offset, length));
  const edgeCells = buffer("edgeCells", (data, offset, length) => new Uint32Array(data, offset, length));
  return {
    displayPositions: mapStepPositions(positions),
    indices: buffer("indices", (data, offset, length) => new Uint32Array(data, offset, length)),
    triangleFaceIds: buffer("triangleFaceIds", (data, offset, length) => new Int32Array(data, offset, length)),
    selectableFaceIds: Array.from(buffer("selectableFaceIds", (data, offset, length) => new Int32Array(data, offset, length))),
    displayEdgePositions: mapStepPositions(edgePoints),
    edgeIndices: edgeSegmentIndices(edgeCells),
    bounds: header.bounds,
    transform: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  };
}

export function stepModelBufferBytes(model: StepModelGeometry): number {
  return model.displayPositions.byteLength + model.indices.byteLength
    + model.triangleFaceIds.byteLength + model.displayEdgePositions.byteLength
    + model.edgeIndices.byteLength;
}

export function browserHeapBytes(): number | undefined {
  const memory = (performance as Performance & { memory?: { usedJSHeapSize?: number } }).memory;
  return typeof memory?.usedJSHeapSize === "number" ? memory.usedJSHeapSize : undefined;
}
