import assert from "node:assert/strict";
import test from "node:test";
import { BufferGeometry, DoubleSide, Float32BufferAttribute, Mesh, MeshBasicMaterial, Raycaster, Uint32BufferAttribute, Vector3 } from "three";
import { acceleratedRaycast, computeBoundsTree, disposeBoundsTree } from "three-mesh-bvh";
import { createStepFaceOverlayGeometry, createStepFaceOverlayMaterial, indexStepFaceRanges } from "../src/stepFaceGeometry.ts";

test("face overlays share model buffers and draw the requested triangles from either side", () => {
  const model = new BufferGeometry();
  model.setAttribute("position", new Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 0, 0, 3, 0, 0, 2, 1, 0], 3));
  model.setIndex(new Uint32BufferAttribute([0, 1, 2, 3, 4, 5], 1));
  const ranges = indexStepFaceRanges(new Int32Array([11, 22]));
  const overlay = createStepFaceOverlayGeometry(model);
  const material = createStepFaceOverlayMaterial(true);
  assert.equal(overlay.getAttribute("position"), model.getAttribute("position"));
  assert.equal(overlay.getIndex(), model.getIndex());
  assert.equal(material.side, DoubleSide);
  const range = ranges.get(22)!;
  overlay.setDrawRange(range.start * 3, range.count * 3);
  const mesh = new Mesh(overlay, material);
  mesh.updateMatrixWorld();
  for (const z of [-1, 1]) {
    const ray = new Raycaster(new Vector3(2.2, 0.2, z), new Vector3(0, 0, -z));
    assert.equal(ray.intersectObject(mesh).length, 1);
    ray.ray.origin.x = 0.2;
    assert.equal(ray.intersectObject(mesh).length, 0);
  }
  overlay.dispose(); material.dispose(); model.dispose();
});

test("BVH picking preserves original STEP triangle-to-face mapping", () => {
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new Float32BufferAttribute([0, 0, 0, 1, 0, 0, 0, 1, 0, 2, 0, 0, 3, 0, 0, 2, 1, 0], 3));
  geometry.setIndex(new Uint32BufferAttribute([0, 1, 2, 3, 4, 5], 1));
  geometry.computeBoundsTree = computeBoundsTree;
  geometry.disposeBoundsTree = disposeBoundsTree;
  geometry.computeBoundsTree({ indirect: true });
  const material = new MeshBasicMaterial({ side: DoubleSide });
  const mesh = new Mesh(geometry, material);
  mesh.raycast = acceleratedRaycast;
  mesh.updateMatrixWorld();
  const faceIds = new Int32Array([11, 22]);
  for (const [x, expected] of [[0.2, 11], [2.2, 22]]) {
    const ray = new Raycaster(new Vector3(x, 0.2, 1), new Vector3(0, 0, -1));
    ray.firstHitOnly = true;
    const hit = ray.intersectObject(mesh)[0];
    assert.ok(hit && hit.faceIndex !== undefined && hit.faceIndex !== null);
    assert.equal(faceIds[hit.faceIndex], expected);
  }
  geometry.disposeBoundsTree(); geometry.dispose(); material.dispose();
});
