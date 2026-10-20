// A tiny Chrome DevTools Protocol driver (no dependencies) shared by the browser scripts.
// Each launch uses a brand-new profile, so cookies from a previous run can never leak in.
import { spawn } from 'node:child_process';
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

export const delay = ms => new Promise(r => setTimeout(r, ms));

const defaultChrome = process.platform === 'win32'
  ? 'C:/Program Files/Google/Chrome/Application/chrome.exe'
  : process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : 'google-chrome';

export async function launchBrowser({ port = 9323, width = 1440, height = 1000, mobile = false } = {}) {
  const chrome = process.env.CHROME_PATH || defaultChrome;
  const profile = await mkdtemp(path.join(os.tmpdir(), 'claimbridge-browser-'));
  const proc = spawn(chrome, ['--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-extensions',
    `--remote-debugging-port=${port}`, '--remote-debugging-address=127.0.0.1', `--user-data-dir=${profile}`, 'about:blank'],
  { windowsHide: true, stdio: 'ignore' });
  let tabs;
  for (let i = 0; i < 80 && !tabs; i++) {
    try { tabs = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); } catch { await delay(250); }
  }
  if (!tabs) { proc.kill(); throw new Error(`Chrome did not start (CHROME_PATH=${chrome})`); }
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let next = 0;
  const pending = new Map();
  const errors = [];
  ws.onmessage = ({ data }) => {
    const m = JSON.parse(data);
    if (m.id) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result); }
    if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++next; pending.set(id, { resolve, reject }); ws.send(JSON.stringify({ id, method, params }));
  });
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  const viewport = async (w, h, m = w < 500) => send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: m });
  await viewport(width, height, mobile);

  const evaluate = async expression => {
    const r = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (expression, { timeout = 20000, what = expression } = {}) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      try { const v = await evaluate(expression); if (v) return v; } catch { /* page is navigating */ }
      await delay(200);
    }
    throw new Error(`timed out waiting for ${what}`);
  };
  const text = () => evaluate('document.body ? document.body.innerText : ""');
  const navigate = async url => { await send('Page.navigate', { url }); await delay(150); await waitFor('document.readyState === "complete"', { what: `load ${url}` }); };
  // Controlled inputs need the native setter and an input event.
  const type = (selector, value) => evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) throw new Error('no ${selector}');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, ${JSON.stringify(value)});
    el.dispatchEvent(new Event('input', { bubbles: true })); return true; })()`);
  const click = label => evaluate(`(() => { const el = [...document.querySelectorAll('button,a,[role=tab]')]
    .find(e => e.textContent.trim().startsWith(${JSON.stringify(label)})); if (!el) throw new Error('no control ${label}'); el.click(); return true; })()`);
  const screenshot = async file => { const s = await send('Page.captureScreenshot', { format: 'png' }); await writeFile(file, Buffer.from(s.data, 'base64')); };
  const cookies = async () => (await send('Network.getAllCookies')).cookies;
  const close = async () => { try { await send('Browser.close'); } catch { /* already gone */ } ws.close(); proc.kill(); await delay(300); await rm(profile, { recursive: true, force: true }).catch(() => {}); };
  return { send, evaluate, waitFor, text, navigate, type, click, screenshot, cookies, viewport, errors, close };
}

export async function ensureDir(dir) { await mkdir(dir, { recursive: true }); return path.resolve(dir); }
