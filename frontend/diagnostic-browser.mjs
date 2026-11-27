import { createServer as createHttpServer } from "node:http";
import { createReadStream } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import { createServer } from "vite";
const file = "C:/Users/User/AppData/Local/PalletLab/step_cache/web_assets/step-web-v1-aef15e104574b9bc37b996c1e66893f75cdd5e8568db5ee0f482053622438a1d.bin";
const server = createHttpServer((_req, res) => { res.setHeader("Access-Control-Allow-Origin", "*"); createReadStream(file).pipe(res); });
await new Promise(resolve => server.listen(19753, "127.0.0.1", resolve));
const vite = await createServer({ configFile: false, server: { host: "127.0.0.1", port: 19752, strictPort: true } }); await vite.listen();
const profile = await mkdtemp(join(tmpdir(), "palletlab-diagnostic-"));
const browser = spawn("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", ["--headless=new", "--no-first-run", "--disable-gpu", "--enable-unsafe-swiftshader", "--remote-debugging-port=19754", `--user-data-dir=${profile}`, "http://127.0.0.1:19752/diagnostic.html"], { windowsHide: true, stdio: "ignore" });
try {
  let page;
  for (let i = 0; i < 100 && !page; i++) { try { page = (await (await fetch("http://127.0.0.1:19754/json")).json()).find(p => p.type === "page"); } catch {} if (!page) await new Promise(r => setTimeout(r, 100)); }
  if (!page) throw new Error("Browser did not start");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let seq = 0; const calls = new Map();
  socket.onmessage = ({ data }) => { const msg = JSON.parse(data); if (msg.id && calls.has(msg.id)) { calls.get(msg.id)(msg); calls.delete(msg.id); } else if (msg.method === "Runtime.exceptionThrown") console.log(JSON.stringify(msg.params.exceptionDetails)); };
  const send = (method, params = {}) => new Promise(resolve => { const id = ++seq; calls.set(id, resolve); socket.send(JSON.stringify({id,method,params})); });
  await send("Runtime.enable");
  let result = "timeout";
  for (let i = 0; i < 100; i++) {
    const reply = await send("Runtime.evaluate", { expression: "document.body.dataset.result || 'loading'", returnByValue: true });
    result = reply.result?.result?.value || "loading";
    if (result !== "loading") break;
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  console.log(result); socket.close();
} finally {
  browser.kill(); await vite.close(); await new Promise(resolve => server.close(resolve));
  if (profile.startsWith(join(tmpdir(), "palletlab-diagnostic-"))) await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }).catch(() => {});
}
