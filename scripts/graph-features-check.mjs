// Real-browser check of the two graph features: the precedent path on a case and the clause-impact graph on Memory.
import path from 'node:path';
import { delay, ensureDir, launchBrowser } from './cdp.mjs';

const base = process.env.CB_BASE_URL || 'http://127.0.0.1:3100';
const out = await ensureDir('artifacts/graph-features');
const browser = await launchBrowser({ port: 9341, height: 1500 });
const { evaluate, waitFor, navigate, screenshot } = browser;
const results = [];
const step = (name, ok, detail = '') => { results.push({ name, ok: !!ok }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  -- ${detail}`}`); };
try {
  await navigate(`${base}/console/claims/EV-T1-01`);
  await waitFor('document.body.innerText.includes("Precedents")', { what: 'case page' });
  await evaluate(`[...document.querySelectorAll('button,[role=tab]')].find(b => /^Precedents/.test(b.innerText.trim()))?.click()`);
  await waitFor('document.body.innerText.includes("Show the path through the graph")', { what: 'path toggle' });
  await evaluate(`[...document.querySelectorAll('button')].find(b => b.innerText.includes('Show the path through the graph')).click()`);
  await waitFor('!!document.querySelector("ol[aria-label]")', { what: 'path list' });
  await delay(1500);
  const txt = await evaluate('document.querySelector("ol[aria-label]").innerText');
  step('case: the path marks the broken hop', /Breaks here/.test(txt) && /valid in/.test(txt) && /matches this path/.test(txt), txt);
  await screenshot(path.join(out, 'precedent-path.png'));

  await navigate(`${base}/console/memory`);
  await waitFor('document.body.innerText.includes("What rests on a clause")', { what: 'impact panel' });
  await waitFor('document.querySelectorAll("svg[aria-label^=Everything] g[role=button]").length > 3', { what: 'impact nodes' });
  await delay(2500);
  const before = await evaluate('document.querySelectorAll("svg[aria-label^=Everything] g[role=button]").length');
  await evaluate("document.getElementById('impact-h').scrollIntoView()"); await delay(300);
  await screenshot(path.join(out, 'clause-impact.png'));
  const dimmedBefore = await evaluate('[...document.querySelectorAll("svg[aria-label^=Everything] g[role=button]")].filter(g => g.getAttribute("opacity") === "0.4").length');
  await evaluate(`[...document.querySelectorAll('svg[aria-label^="Everything connected"] g[role=button]')].find(g => /evidence/.test(g.getAttribute('aria-label')))?.dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
  await delay(600);
  const dimmedAfter = await evaluate('[...document.querySelectorAll("svg[aria-label^=Everything] g[role=button]")].filter(g => g.getAttribute("opacity") === "0.4").length');
  step('memory: the impact graph draws nodes', before > 3, before);
  step('memory: clicking a node changes what is lit', dimmedBefore !== dimmedAfter || dimmedAfter === 0, `${dimmedBefore} -> ${dimmedAfter}`);
  await evaluate(`[...document.querySelectorAll('button')].find(b => b.innerText.includes('The Cypher behind this view')).click()`);
  step('memory: the Cypher is shown', await evaluate('document.body.innerText.includes("SUPERSEDES*0..4")'));
  step('no script errors', browser.errors.length === 0, browser.errors.join('; '));
} finally { await browser.close(); }
process.exit(results.every(r => r.ok) ? 0 : 1);
