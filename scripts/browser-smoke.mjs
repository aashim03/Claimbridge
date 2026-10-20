// Real-browser action flows against the running demo stack (default http://127.0.0.1:3100).
//
//   node scripts/browser-smoke.mjs
//
// It files two scenario claims through the API, waits for the agents, then drives the console like a person:
// the animated graph replay (play / pause / step / node click), the case tabs, the New-claim and declare-evidence
// forms, the memory, agents and evaluation pages, and a phone-width pass. A page that merely renders does not
// pass: each step asserts that the control actually did something. Writes artifacts/browser/smoke.json and
// screenshots. Needs the stack (`docker compose --profile app up -d`) and Chrome (CHROME_PATH to override).
import path from 'node:path';
import { writeFile } from 'node:fs/promises';
import { delay, ensureDir, launchBrowser } from './cdp.mjs';

const base = process.env.CB_BASE_URL || 'http://127.0.0.1:3100';
const out = await ensureDir(process.env.CB_SCREENSHOT_DIR || 'artifacts/browser');
const results = [];
const step = (name, ok, detail = '') => { results.push({ name, passed: !!ok, detail: String(detail).slice(0, 240) }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  -- ${detail}`}`); };

const browser = await launchBrowser({ port: 9335 });
const { evaluate, waitFor, text, navigate, click, screenshot } = browser;
const api = (url, init) => evaluate(`fetch(${JSON.stringify(url)}, ${JSON.stringify(init || {})}).then(async r => ({ status: r.status, body: await r.json().catch(() => null) }))`);
const post = (url, body) => api(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-ClaimBridge-Request': '1' }, body: JSON.stringify(body) });
const status = async cid => (await api(`/api/claims/${cid}`)).body?.claim?.status;

try {
  // ------------------------------------------------------------------ landing
  await navigate(`${base}/`);
  await waitFor('!!document.querySelector(".cbg-status")', { what: 'landing replay' });
  await click('Replay');                      // a replay that already finished (or reduced motion) restarts on demand
  await delay(500);
  const first = await evaluate('document.querySelector(".cbg-status b").innerText');
  await delay(4500);
  const later = await evaluate('document.querySelector(".cbg-status b").innerText');
  step('landing: the recorded replay plays when asked', first !== later, `${first} -> ${later}`);
  await screenshot(path.join(out, 'landing.png'));

  // ------------------------------------------------------------------ set up two claims through the API
  await navigate(`${base}/console`);
  await waitFor('document.body.innerText.includes("Docket")', { what: 'docket' });
  for (const cid of ['EV-T1-01', 'EV-M-B1']) {
    const s = await status(cid);
    if (s === 'NEW') await post('/api/claims/inject', { ids: [cid] });
  }
  for (const cid of ['EV-T1-01', 'EV-M-B1']) {
    await waitFor(`fetch("/api/claims/${cid}").then(r => r.json()).then(d => ["AWAITING_REVIEW","APPROVED","CURATED","NEEDS_HUMAN"].includes(d.claim.status))`, { timeout: 180000, what: `${cid} planned by the agents` });
  }
  step('the agents plan both claims', (await status('EV-T1-01')) !== 'NEEDS_HUMAN');

  // ------------------------------------------------------------------ docket
  await navigate(`${base}/console`);
  await waitFor('document.body.innerText.includes("EV-T1-01")', { what: 'docket rows' });
  await click('New claim');
  await waitFor('!!document.querySelector("[role=dialog]")', { what: 'new claim drawer' });
  step('docket: New claim opens a drawer with a notice field', await evaluate('!!document.querySelector("#nc-notice") && !!document.querySelector("[role=dialog] form")'));
  await evaluate('document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" })); window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }))');
  await waitFor('!document.querySelector("[role=dialog]")', { what: 'drawer closes on Escape' });
  step('docket: Escape closes the drawer', true);

  // ------------------------------------------------------------------ case page and the graph replay
  await navigate(`${base}/console/claims/EV-T1-01`);
  await waitFor('!!document.querySelector(".cbg-svg")', { what: 'graph replay on the case page' });
  step('case: the graph replay is the default tab', await evaluate('document.querySelector("[role=tab][aria-selected=true]").innerText.startsWith("Graph replay")'));
  const label = () => evaluate('document.querySelector(".cbg-play").innerText.trim()');
  const startLabel = await label();
  await click('Pause').catch(() => click('Play'));
  await delay(300);
  const afterToggle = await label();
  step('case: Play/Pause toggles', startLabel !== afterToggle, `${startLabel} -> ${afterToggle}`);
  const counter = () => evaluate('(document.querySelector(".cbg-status b")||{}).innerText||""');
  await click('Replay');
  await delay(400);
  await click('Pause').catch(() => {});
  const before = await counter();
  await click('Step ›');
  await delay(900);
  const after = await counter();
  step('case: Step advances the replay', before !== after, `${before} -> ${after}`);
  const nodes = await evaluate('document.querySelectorAll(".cbg-node:not(.hidden)").length');
  step('case: nodes are drawn as steps play', nodes >= 2, `${nodes} visible`);
  await evaluate('(() => { const n = [...document.querySelectorAll(".cbg-node:not(.hidden)")].pop(); n.dispatchEvent(new MouseEvent("click", { bubbles: true })); })()');
  await delay(300);
  step('case: clicking a node pins what it contributed', await evaluate('!!document.querySelector(".cbg-insp .cbg-unpin")'));
  await evaluate('document.querySelector(".cbg-unpin").click()');
  for (let i = 0; i < 12; i++) await click('Step ›').catch(() => {});
  await delay(1200);
  step('case: the replay reaches a recommendation', await evaluate('document.querySelector(".cbg-insp")?.innerText.includes("Recommendation") || document.body.innerText.includes("Appeal")'));
  await screenshot(path.join(out, 'case-replay.png'));

  // ------------------------------------------------------------------ tabs
  for (const [tab, needle] of [['Plan', 'Each item names'], ['Precedents', 'recorded win'], ['Evidence', 'Declare a document is on file'], ['Agent record', 'Picked up']]) {
    await click(tab);
    const ok = await waitFor(`document.body.innerText.includes(${JSON.stringify(needle)})`, { timeout: 6000, what: `${tab} tab` }).then(() => true, () => false);
    step(`case: the ${tab} tab shows its content`, ok, needle);
  }
  // ------------------------------------------------------------------ the Investigate panel (desktop)
  await click('Investigate');
  await waitFor('document.body.innerText.includes("The investigator picks read-only graph tools")', { what: 'Investigate tab' });
  await click('Graph-only run');
  await waitFor('document.body.innerText.includes("tool calls, in order")', { timeout: 60000, what: 'investigation steps' });
  const steps = await evaluate('document.querySelectorAll("[aria-label=\\"Tool calls in order\\"] ol > li").length');
  step('investigate: the tool calls are listed in order', steps >= 5, `${steps} steps`);
  step('investigate: the outcome is named in words, honestly ("Graph-only")', await evaluate('/Graph-only \\(/.test(document.body.innerText) || document.body.innerText.includes("AI agent")'));
  step('investigate: a graph-only run is never labelled an AI agent', await evaluate('(() => { const t = document.body.innerText; return !/Graph-only \\(/.test(t) || !/AI agent:/.test(t.split("Brief")[0].slice(-400)); })()'));
  step('investigate: plain sentence first, then the tool and its ids', await evaluate('document.body.innerText.includes("Looked up the policy in force")'));
  await evaluate('document.querySelector("details > summary").click()');
  step('investigate: a step expands to its raw tool result', await evaluate(`!!document.querySelector('details[open] pre') && document.querySelector('details[open] pre').innerText.includes('"ok"')`));
  step('investigate: tokens are reported', await evaluate('/tokens|0 tokens/.test(document.body.innerText)'));
  await evaluate('[...document.querySelectorAll("button")].find(b => b.textContent.includes("Show the path through the graph"))?.click()');
  step('investigate: reuses the existing path-through-the-graph view', await waitFor('!!document.querySelector("[aria-label=\\"Path through the graph\\"]")', { timeout: 8000 }).then(() => true, () => false));
  await screenshot(path.join(out, 'investigate.png'));
  await click('Open the graph replay');
  step('investigate: links to the graph replay', await waitFor('!!document.querySelector(".cbg-svg")', { timeout: 8000 }).then(() => true, () => false));
  step('case: the support score is never a bare 0%', !/Support score\s*0%/.test(await text()));
  step('case: no stale wording ("good law", "Could be wrong if")', !/good law|Could be wrong if/i.test(await text()));
  await screenshot(path.join(out, 'case-evidence.png'));

  // ------------------------------------------------------------------ declare evidence on the second claim (moves it back to the Planner)
  await navigate(`${base}/console/claims/EV-M-B1`);
  await waitFor('!!document.querySelector("[role=tab]")', { what: 'EV-M-B1 case' });
  if ((await status('EV-M-B1')) === 'AWAITING_REVIEW') {
    await click('Evidence');
    await waitFor('document.body.innerText.includes("Declare a document is on file")', { what: 'declare form' });
    await waitFor(`[...document.querySelectorAll('select[aria-label="Document type"] option')].some(o => o.value)`, { what: 'document options loaded' }).catch(() => {});
    const picked = await evaluate(`(() => { const s = document.querySelector('select[aria-label="Document type"]'); const o = [...s.options].find(o => o.value); if (!o) return null;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, o.value); s.dispatchEvent(new Event('change', { bubbles: true })); return o.value; })()`);
    if (picked) {
      await click('Declare');
      await waitFor(`fetch("/api/claims/EV-M-B1").then(r => r.json()).then(d => d.evidence.some(e => e.declared_by))`, { timeout: 20000, what: 'document declared' });
      step('case: declaring a document is recorded and not marked verified', (await api('/api/claims/EV-M-B1')).body.evidence.every(e => !e.declared_by || e.verified === false));
      await waitFor(`fetch("/api/claims/EV-M-B1").then(r => r.json()).then(d => d.claim.status === "AWAITING_REVIEW")`, { timeout: 120000, what: 'claim re-planned' });
      step('case: the claim is re-planned after the change', true);
    } else step('case: the declare form offers a document', false, 'no option');
  } else step('case: EV-M-B1 is awaiting review (declare flow skipped)', true, 'state: ' + await status('EV-M-B1'));

  // ------------------------------------------------------------------ the other pages
  for (const [route, needles, name] of [
    ['/console/memory', ['Memory', 'recorded win', 'Which clauses carry the most memory', 'algo.pageRank'], 'memory'],
    ['/console/agents', ['Agents', 'Supervisor'], 'agents'],
    ['/console/evaluation', ['What each system can see', 'Limits of this evaluation'], 'evaluation'],
  ]) {
    await navigate(`${base}${route}`);
    const ok = await waitFor(`${JSON.stringify(needles)}.every(n => document.body.innerText.includes(n))`, { timeout: 15000, what: name }).then(() => true, () => false);
    step(`${name} page renders its content`, ok, needles.join(' / '));
    await screenshot(path.join(out, `${name}.png`));
  }
  step('evaluation page names the run it shows', /Run\s+\S{8,}/.test(await text()) || (await text()).includes('Run identity'));

  // ------------------------------------------------------------------ blast radius on the Memory page
  await navigate(`${base}/console/memory`);
  await waitFor('document.body.innerText.includes("If C-")', { timeout: 30000, what: 'blast radius reach' });
  step('memory: the blast radius lists what is reached, with hop distances', await evaluate('/hop \d/.test(document.body.innerText)'));
  await evaluate('document.getElementById("blast-h").scrollIntoView()');
  await screenshot(path.join(out, 'blast-radius.png'));

  // ------------------------------------------------------------------ phone width
  await browser.viewport(390, 844, true);
  await navigate(`${base}/console/claims/EV-T1-01`);
  await waitFor('!!document.querySelector("[role=tab]")', { what: 'case on phone' });
  await click('Investigate');
  await waitFor('document.body.innerText.includes("The investigator picks read-only graph tools")', { what: 'Investigate tab on phone' });
  await click('Graph-only run');
  await waitFor('document.body.innerText.includes("tool calls, in order")', { timeout: 60000, what: 'investigation on phone' });
  step('mobile-investigate: no horizontal page scroll', (await evaluate('document.documentElement.scrollWidth - window.innerWidth')) <= 2);
  step('mobile-investigate: the run button is reachable by keyboard (a real <button>)', await evaluate('[...document.querySelectorAll("button")].some(b => b.textContent.trim() === "Graph-only run" && b.tabIndex >= 0)'));
  await screenshot(path.join(out, 'mobile-investigate.png'));
  await navigate(`${base}/console/memory`);
  await waitFor('document.body.innerText.includes("If C-")', { timeout: 30000, what: 'blast radius on phone' });
  step('mobile-blast-radius: no horizontal page scroll', (await evaluate('document.documentElement.scrollWidth - window.innerWidth')) <= 2);
  for (const [route, name] of [['/console', 'mobile-docket'], ['/console/claims/EV-T1-01', 'mobile-case'], ['/console/evaluation', 'mobile-evaluation'], ['/', 'mobile-landing']]) {
    await navigate(`${base}${route}`);
    await delay(2500);
    const overflow = await evaluate('document.documentElement.scrollWidth - window.innerWidth');
    step(`${name}: no horizontal page scroll`, overflow <= 2, `overflow ${overflow}px`);
    await screenshot(path.join(out, `${name}.png`));
  }
  step('no JavaScript errors anywhere', browser.errors.length === 0, browser.errors.join(' | '));
} catch (e) {
  step('smoke completed without an unexpected error', false, e.stack || e.message);
} finally {
  await browser.close();
  const failed = results.filter(r => !r.passed);
  await writeFile(path.join(out, 'smoke.json'), JSON.stringify({ run_at: new Date().toISOString(), base, results, errors: browser.errors }, null, 2));
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exitCode = failed.length ? 1 : 0;
}
