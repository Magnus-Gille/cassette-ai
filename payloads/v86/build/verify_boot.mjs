// Dedicated CDP verifier — launches its own headless chromium (isolated from the
// shared MCP browser), loads the v86 HTML over HTTP, waits for boot, and reports:
//   - failed network requests (proves zero runtime fetches for BIOS/image)
//   - serial terminal text + VGA screen text (proves Linux actually booted)
import { spawn } from "node:child_process";
import http from "node:http";

const CHROME = process.env.CHROME;
const URL = process.env.PAGE_URL || "http://localhost:8812/v86_linux.html";
const PORT = 9333;
const userDir = `/tmp/v86verify-${Date.now()}`;

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

const proc = spawn(CHROME, [
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${userDir}`,
  "--headless=new",
  "--no-sandbox",
  "--disable-gpu",
  "--no-first-run",
  "about:blank",
], { stdio: ["ignore", "ignore", "ignore"] });

function getJSON(path) {
  return new Promise((resolve, reject) => {
    http.get(`http://localhost:${PORT}${path}`, res => {
      let d = ""; res.on("data", c => d += c); res.on("end", () => resolve(JSON.parse(d)));
    }).on("error", reject);
  });
}

let msgId = 0;
function cdp(ws, method, params = {}, sessionId) {
  return new Promise((resolve) => {
    const id = ++msgId;
    const handler = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === id) { ws.removeEventListener("message", handler); resolve(m.result); }
    };
    ws.addEventListener("message", handler);
    ws.send(JSON.stringify({ id, method, params, sessionId }));
  });
}

const failedRequests = [];
const allRequests = [];

(async () => {
  // wait for CDP endpoint
  let ver;
  for (let i = 0; i < 40; i++) {
    try { ver = await getJSON("/json/version"); break; } catch { await sleep(250); }
  }
  const browserWsUrl = ver.webSocketDebuggerUrl;
  const bws = new WebSocket(browserWsUrl);
  await new Promise(r => bws.addEventListener("open", r, { once: true }));

  // create a fresh tab
  const target = await cdp(bws, "Target.createTarget", { url: "about:blank" });
  const targetId = target.targetId;
  const attached = await cdp(bws, "Target.attachToTarget", { targetId, flatten: true });
  const sessionId = attached.sessionId;

  // listen for network events on the page session
  bws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.sessionId !== sessionId) return;
    if (m.method === "Network.requestWillBeSent") {
      allRequests.push(m.params.request.url);
    }
    if (m.method === "Network.loadingFailed") {
      failedRequests.push({ url: m.params.requestId, err: m.params.errorText, type: m.params.type });
    }
    if (m.method === "Network.responseReceived") {
      const s = m.params.response.status;
      if (s >= 400) failedRequests.push({ url: m.params.response.url, status: s });
    }
  });

  await cdp(bws, "Network.enable", {}, sessionId);
  await cdp(bws, "Page.enable", {}, sessionId);
  await cdp(bws, "Runtime.enable", {}, sessionId);

  await cdp(bws, "Page.navigate", { url: URL }, sessionId);

  // Poll for boot up to ~75s
  let result = null;
  for (let i = 0; i < 75; i++) {
    await sleep(1000);
    const r = await cdp(bws, "Runtime.evaluate", {
      expression: `JSON.stringify({
        status: document.getElementById('status') && document.getElementById('status').textContent,
        serial: (window.__getSerial ? window.__getSerial() : ''),
        screen: (function(){ var c=document.querySelector('#screen_container>div'); return c?c.textContent:''; })()
      })`,
      returnByValue: true,
    }, sessionId);
    try {
      result = JSON.parse(r.result.value);
    } catch { continue; }
    const combined = (result.serial || "") + "\n" + (result.screen || "");
    if (/login:|#\s*$|\/ #|buildroot|Welcome|BusyBox|Linux version/i.test(combined) && (result.serial.length + result.screen.length) > 200) {
      // also wait a couple more seconds to capture the prompt
    }
    if (/login:|\/ #|# $|buildroot login/i.test(combined)) break;
  }

  // Try to send a command over serial to prove interactivity: type "uname -a\n"
  // serial input goes via the textarea -> emulator; use the emulator API directly.
  await cdp(bws, "Runtime.evaluate", {
    expression: `(function(){ if(window.__v86 && window.__v86.serial0_send){ window.__v86.serial0_send("uname -a\\n"); } else if (window.__v86) { window.__v86.bus && window.__v86.bus.send && window.__v86.bus.send("serial0-input", 10); } })()`,
    returnByValue: true,
  }, sessionId);
  // proper API: emulator.serial0_send
  await cdp(bws, "Runtime.evaluate", {
    expression: `(function(){ try{ window.__v86.serial0_send("\\nuname -a\\n"); return "sent"; }catch(e){ return "err:"+e; } })()`,
    returnByValue: true,
  }, sessionId);
  await sleep(4000);

  const finalR = await cdp(bws, "Runtime.evaluate", {
    expression: `JSON.stringify({
      status: document.getElementById('status').textContent,
      serial: (window.__getSerial?window.__getSerial():''),
      screen: (function(){ var c=document.querySelector('#screen_container>div'); return c?c.textContent:''; })()
    })`,
    returnByValue: true,
  }, sessionId);
  const fin = JSON.parse(finalR.result.value);

  // Report
  const offsite = allRequests.filter(u => !u.startsWith("http://localhost:8812") && !u.startsWith("about:") && !u.startsWith("data:") && !u.startsWith("blob:"));
  const badFailed = failedRequests.filter(f => !/favicon/i.test(f.url || ""));

  console.log("=== NETWORK ===");
  console.log("total requests:", allRequests.length);
  console.log("offsite (non-localhost:8812) requests:", JSON.stringify(offsite));
  console.log("failed/4xx (excl favicon):", JSON.stringify(badFailed));
  console.log("all request urls:", JSON.stringify(allRequests));
  console.log("=== STATUS ===");
  console.log(fin.status);
  console.log("=== SERIAL (last 1500) ===");
  console.log((fin.serial || "").slice(-1500));
  console.log("=== SCREEN (VGA text mode) ===");
  console.log(fin.screen || "(empty / graphical mode)");

  proc.kill("SIGKILL");
  process.exit(0);
})().catch(e => { console.error("VERIFY ERROR", e); proc.kill("SIGKILL"); process.exit(1); });
