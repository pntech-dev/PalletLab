import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { DEFAULT_SETTINGS } from "./appSettings";
import fixture from "../diagnostic-fixture.json";
import "./design/tokens.css";
import "./styles.css";
import "./design/components.css";
class Boundary extends React.Component<
    { children: React.ReactNode },
    { error: string }
> {
    state = { error: "" };
    static getDerivedStateFromError(error: Error) {
        return { error: error.stack ?? error.message };
    }
    render() {
        if (this.state.error) {
            document.body.dataset.result = `error:${this.state.error}`;
            return null;
        }
        return this.props.children;
    }
}
let polls = 0;
const api = {
    status: async () => ({
        application: "PalletLab",
        version: "1",
        snapshotVersion: 1,
    }),
    default_project: async () => fixture.project,
    application_settings: async () => ({
        ...DEFAULT_SETTINGS,
        autosaveEnabled: false,
    }),
    update_status: async () => ({ state: "idle" }),
    calculate: async () => fixture.calculation,
    solidworks_export_settings: async () => ({ ok: false }),
    import_step_model: async () => ({
        ok: true,
        operationId: "test",
        state: "running",
        progress: 5,
    }),
    step_import_status: async () =>
        ++polls < 6
            ? {
                  ok: true,
                  operationId: "test",
                  state: "running",
                  progress: polls * 10,
              }
            : { ok: true, operationId: "test", state: "completed" },
    step_model_snapshot: async () => ({
        ok: true,
        assetUrl: "http://127.0.0.1:19753/asset",
    }),
};
Object.defineProperty(window, "pywebview", { value: { api } });
const oldError = console.error;
console.error = (...args) => {
    oldError(...args);
    if (String(args[0]).includes("Ошибка отображения 3D-вида"))
        document.body.dataset.result = `viewport:${args.map(String).join(" | ")}`;
};
createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <Boundary>
            <App />
        </Boundary>
    </React.StrictMode>,
);
let clicked = false,
    modelSeenAt = 0;
setInterval(() => {
    const button = [...document.querySelectorAll("button")].find((b) =>
        b.textContent?.includes("Импорт модели"),
    );
    if (!clicked && button && !button.disabled) {
        clicked = true;
        button.click();
    }
    if (
        clicked &&
        document
            .querySelector(".scene-settings-panel")
            ?.textContent?.includes("Показывать 3D-модель")
    ) {
        if (!modelSeenAt) modelSeenAt = Date.now();
        if (Date.now() - modelSeenAt > 5000 && !document.body.dataset.result)
            document.body.dataset.result = "rendered";
    }
}, 100);
