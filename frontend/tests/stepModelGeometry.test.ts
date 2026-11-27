import assert from "node:assert/strict";
import test from "node:test";
import { prepareStepModel } from "../src/stepModelGeometry.ts";

test("model preparation converts coordinates without copying the shared asset buffer", async () => {
  const arrays: Record<string, Float32Array | Uint32Array | Int32Array> = {
    positions: new Float32Array([1000, 2000, 3000, 0, 0, 0, 1000, 0, 0]),
    indices: new Uint32Array([0, 1, 2]),
    triangleFaceIds: new Int32Array([7]),
    selectableFaceIds: new Int32Array([7]),
    edgePoints: new Float32Array([4000, 5000, 6000, 0, 0, 0]),
    edgeCells: new Uint32Array([2, 0, 1]),
  };
  let offset = 0;
  const buffers: Record<string, { offset: number; byteLength: number; dtype: string }> = {};
  for (const [name, values] of Object.entries(arrays)) {
    buffers[name] = { offset, byteLength: values.byteLength, dtype: "<f4" };
    offset += values.byteLength;
  }
  const header = new TextEncoder().encode(JSON.stringify({ version: 1, bounds: [0, 1, 0, 1, 0, 1], buffers }));
  const dataStart = 12 + header.length + ((4 - header.length % 4) % 4);
  const asset = new ArrayBuffer(dataStart + offset);
  const bytes = new Uint8Array(asset);
  bytes.set(new TextEncoder().encode("PLSTEP01"));
  new DataView(asset).setUint32(8, header.length, true);
  bytes.set(header, 12);
  for (const [name, values] of Object.entries(arrays)) bytes.set(new Uint8Array(values.buffer), dataStart + buffers[name].offset);
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(asset);
  try {
    const model = await prepareStepModel({ assetUrl: "test" });
    assert.deepEqual([...model.displayPositions.slice(0, 3)], [1, 3, 2]);
    assert.deepEqual([...model.displayEdgePositions.slice(0, 3)], [4, 6, 5]);
    assert.deepEqual([...model.edgeIndices], [0, 1]);
    assert.equal(model.displayPositions.buffer, model.indices.buffer);
    assert.equal(model.displayEdgePositions.buffer, model.indices.buffer);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
