import { BufferAttribute, BufferGeometry, type Sphere } from "three";
import { MeshBVH, type MeshBVHOptions } from "three-mesh-bvh";
import {
    prepareStepModel,
    type StepModelGeometry,
    type StepModelPayload,
} from "./stepModelGeometry";

const worker = self as unknown as {
    onmessage: ((event: MessageEvent<StepModelPayload>) => void) | null;
    postMessage: (
        message: { model?: StepModelGeometry; error?: string },
        transfer: Transferable[],
    ) => void;
};

function sphereValues(sphere: Sphere | null): [number, number, number, number] {
    return sphere
        ? [sphere.center.x, sphere.center.y, sphere.center.z, sphere.radius]
        : [0, 0, 0, 0];
}

worker.onmessage = async ({ data }) => {
    try {
        const model = await prepareStepModel(data);
        const geometry = new BufferGeometry();
        geometry.setAttribute(
            "position",
            new BufferAttribute(model.displayPositions, 3),
        );
        geometry.setIndex(new BufferAttribute(model.indices, 1));
        geometry.computeVertexNormals();
        geometry.computeBoundingSphere();
        const options: MeshBVHOptions & { indirect: true } = {
            indirect: true,
            maxLeafTris: 48,
        };
        const boundsTree = MeshBVH.serialize(new MeshBVH(geometry, options), {
            cloneBuffers: false,
        });
        const edges = new BufferGeometry();
        edges.setAttribute(
            "position",
            new BufferAttribute(model.displayEdgePositions, 3),
        );
        edges.computeBoundingSphere();
        const prepared: StepModelGeometry = {
            ...model,
            normals: geometry.getAttribute("normal").array as Float32Array,
            boundsTree,
            modelSphere: sphereValues(geometry.boundingSphere),
            edgeSphere: sphereValues(edges.boundingSphere),
        };
        const indirect = (
            boundsTree as typeof boundsTree & { indirectBuffer?: Uint32Array }
        ).indirectBuffer;
        const buffers = new Set<ArrayBuffer>([
            prepared.displayPositions.buffer as ArrayBuffer,
            prepared.indices.buffer as ArrayBuffer,
            prepared.triangleFaceIds.buffer as ArrayBuffer,
            prepared.displayEdgePositions.buffer as ArrayBuffer,
            prepared.edgeIndices.buffer as ArrayBuffer,
            prepared.normals.buffer as ArrayBuffer,
            ...boundsTree.roots,
        ]);
        if (indirect) buffers.add(indirect.buffer as ArrayBuffer);
        worker.postMessage({ model: prepared }, [...buffers]);
    } catch (error) {
        worker.postMessage(
            {
                error:
                    error instanceof Error
                        ? error.message
                        : "Не удалось подготовить STEP-модель для просмотра.",
            },
            [],
        );
    }
};
