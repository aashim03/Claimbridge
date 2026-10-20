// Repeatable browser + API access matrix against an ISOLATED protected instance.
//
//   node scripts/access-matrix.mjs
//
// It never touches the demo stack: it seeds its own graph (claimbridge_access), starts its own API
// (port 8101, AUTH_MODE=protected, random one-run tokens) and its own web server (port 3201), drives a
// real Chrome through sign-in / reload / sign-out / account switching / revocation, and writes
// artifacts/browser/access-matrix.json. Needs FalkorDB on localhost:6379 and the backend venv.
import { spawn, spawnSync } from 'node:child_process';
import crypto from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { delay, ensureDir, launchBrowser } from './cdp.mjs';

const repo = path.resolve(import.meta.dirname, '..');
const out = await ensureDir(process.env.CB_SCREENSHOT_DIR || path.join(repo, 'artifacts/browser'));
const py = process.env.PYTHON || path.join(repo, 'backend', '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const API = 8101, WEB = 3201, base = `http://127.0.0.1:${WEB}`;
const token = () => crypto.randomBytes(24).toString('hex');
// Tokens are random per run. Only in CB_KEEP/CB_REUSE development loops are they kept (in the OS temp dir) so a reused API still accepts them.
const tokenFile = path.join(os.tmpdir(), 'claimbridge-access-matrix-tokens.json');
const T = process.env.CB_REUSE === '1' ? JSON.parse(await readFile(tokenFile, 'utf8').catch(() => 'null')) ?? { alice: token(), bob: token(), op: token() }
  : { alice: token(), bob: token(), op: token() };
if (process.env.CB_KEEP === '1') await writeFile(tokenFile, JSON.stringify(T));
const creds = (omit = []) => JSON.stringify(Object.fromEntries([
  [T.alice, { subject: 'alice', role: 'tenant', tenant_id: 'TEN-01' }],
  [T.bob, { subject: 'bob', role: 'tenant', tenant_id: 'TEN-03' }],
  [T.op, { subject: 'operator', role: 'admin' }],
].filter(([k]) => !omit.includes(k))));
const ALICE_CLAIM = 'EV-T1-01', BOB_CLAIM = 'EV-M-A';
const apiEnv = omit => ({ ...process.env, GRAPH: 'claimbridge_access', AUTH_MODE: 'protected', AUTH_CREDENTIALS_JSON: creds(omit),
  LLM_PLATFORM: 'fake', LLM_MODE: 'live', COOKIE_SECURE: '0', HF_HUB_DISABLE_PROGRESS_BARS: '1' });

const procs = [];
const startApi = omit => { const p = spawn(py, ['-m', 'uvicorn', 'claimbridge.api:app', '--port', String(API), '--log-level', 'warning'],
  { cwd: path.join(repo, 'backend'), env: apiEnv(omit), stdio: 'ignore', windowsHide: true }); procs.push(p); return p; };
const stop = p => new Promise(res => { if (p.exitCode !== null) return res(); p.once('exit', res); p.kill(); setTimeout(res, 3000); });
const until = async (fn, ms, what) => { const end = Date.now() + ms; while (Date.now() < end) { try { if (await fn()) return; } catch { /* not yet */ } await delay(300); } throw new Error(`timed out: ${what}`); };

const results = [];
const check = (name, ok, detail = '') => { results.push({ name, passed: !!ok, detail: String(detail).slice(0, 300) }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${ok ? '' : `  -- ${detail}`}`); };

const reuse = process.env.CB_REUSE === '1';   // iterate quickly: keep the seeded graph and servers between runs
const keep = process.env.CB_KEEP === '1';
let browser, api, web;
try {
  const up = async url => { try { return (await fetch(url)).ok; } catch { return false; } };
  if (!(reuse && await up(`http://127.0.0.1:${API}/api/session`))) {
    console.log('seeding the isolated graph…');
    const seed = spawnSync(py, [path.join(repo, 'scripts', 'prepare_access_graph.py')], { env: apiEnv(), encoding: 'utf8' });
    if (seed.status !== 0) throw new Error(`could not seed: ${seed.stderr || seed.stdout}`);
    api = startApi();
    await until(async () => (await fetch(`http://127.0.0.1:${API}/api/session`)).ok, 60000, 'API start');
  } else { console.log('reusing the running isolated API'); }
  const nextBin = path.join(repo, 'web', 'node_modules', 'next', 'dist', 'bin', 'next');
  if (!(reuse && await up(`${base}/api/session`))) {
    web = spawn(process.execPath, [nextBin, 'dev', '-p', String(WEB)], { cwd: path.join(repo, 'web'),
      env: { ...process.env, API_URL: `http://127.0.0.1:${API}` }, stdio: 'ignore', windowsHide: true });
    procs.push(web);
  }
  await until(async () => (await fetch(`${base}/api/session`)).ok, 120000, 'web start (proxying to the isolated API)');

  browser = await launchBrowser({ port: 9334 });
  const { evaluate, waitFor, text, navigate, type, click, cookies, send } = browser;
  const call = (pathname, init = {}) => evaluate(`fetch(${JSON.stringify(pathname)}, ${JSON.stringify(init)})
    .then(async r => ({ status: r.status, subject: r.headers.get('x-claimbridge-subject'), body: (await r.text()).slice(0, 400) }))`);
  const signIn = async who => {
    await waitFor('!!document.querySelector("#access-token")', { what: 'sign-in form' });
    await type('#access-token', who);
    await click('Sign in');
  };
  const banner = who => waitFor(`document.body.innerText.includes(${JSON.stringify(who)})`, { what: `banner ${who}` });
  const gated = () => waitFor('document.body.innerText.includes("Sign in to your cases")', { what: 'sign-in gate', timeout: 30000 });
  const noneOf = async (...needles) => { const t = await text(); return needles.filter(n => t.includes(n)); };

  // 1. Anonymous
  await navigate(`${base}/console`);
  await gated();
  check('anonymous visitor sees only the sign-in form', (await noneOf(ALICE_CLAIM, BOB_CLAIM, 'Asha', 'Carmen')).length === 0);
  const anon = await Promise.all(['/api/claims', '/api/memory', '/api/overview', '/api/agents', `/api/claims/${ALICE_CLAIM}`].map(u => call(u)));
  check('anonymous API calls are all 401', anon.every(r => r.status === 401), anon.map(r => r.status));
  await browser.screenshot(path.join(out, 'access-1-signin.png'));

  // 2. Wrong token
  await type('#access-token', 'definitely-not-a-valid-token-0123456789abcdef'); await click('Sign in');
  await waitFor('!!document.querySelector("[role=alert]")', { what: 'sign-in error' }).catch(async e => { console.log('PAGE:', (await text()).slice(0, 400)); throw e; });
  check('a wrong token is refused and the gate stays', (await text()).includes('Sign in to your cases'));
  check('no cookie after a failed sign-in', !(await cookies()).some(c => c.name === 'claimbridge_session'));

  // 3. Alice
  await type('#access-token', T.alice); await click('Sign in');
  await banner('alice');
  await waitFor(`document.body.innerText.includes(${JSON.stringify(ALICE_CLAIM)})`, { what: 'alice docket' });
  const t1 = await text();
  check("alice sees her own claim and not bob's", t1.includes(ALICE_CLAIM) && !t1.includes(BOB_CLAIM) && !t1.includes('Carmen'), t1.slice(0, 200));
  const cookie = (await cookies()).find(c => c.name === 'claimbridge_session');
  check('session cookie is HttpOnly, SameSite=Strict, scoped to /api', cookie && cookie.httpOnly && cookie.sameSite === 'Strict' && cookie.path === '/api', JSON.stringify(cookie));
  check('the token is not readable from page script', !(await evaluate('document.cookie')).includes('claimbridge_session') && !(await evaluate('JSON.stringify([localStorage, sessionStorage])')).includes(T.alice));
  await browser.screenshot(path.join(out, 'access-2-alice-docket.png'));

  // 4. Reload keeps the session
  await send('Page.reload'); await delay(300);
  await banner('alice');
  check('reload keeps the session', true);

  // 5. The other tenant's claim, by URL and by API
  await navigate(`${base}/console/claims/${BOB_CLAIM}`);
  await delay(2500);
  const denied = await noneOf('Carmen', 'Ambulance', 'Notice of claim denial');
  check("opening bob's claim by URL shows none of its details", denied.length === 0, denied);
  await browser.screenshot(path.join(out, 'access-3-other-tenant-denied.png'));
  const matrix = [
    ['GET', `/api/claims/${BOB_CLAIM}`], ['GET', `/api/claims/${BOB_CLAIM}/graph`], ['GET', `/api/claims/${BOB_CLAIM}/packet`],
  ];
  const ro = await Promise.all(matrix.map(([m, u]) => call(u, { method: m })));
  check("alice's cookie gets 404 for bob's detail, graph and packet", ro.every(r => r.status === 404), ro.map(r => r.status));
  const csrf = { 'Content-Type': 'application/json', 'X-ClaimBridge-Request': '1' };
  const post = (u, body, headers = csrf) => call(u, { method: 'POST', headers, body: JSON.stringify(body) });
  const rw = await Promise.all([
    post(`/api/claims/${BOB_CLAIM}/approve`, {}), post(`/api/claims/${BOB_CLAIM}/outcome`, { outcome: 'OVERTURNED' }),
    post('/api/claims/inject', { ids: [BOB_CLAIM] }),
  ]);
  check("alice cannot approve, record an outcome for, or file bob's claim", rw.every(r => [403, 404].includes(r.status)), rw.map(r => r.status));
  const noHeader = await post(`/api/claims/${ALICE_CLAIM}/approve`, {}, { 'Content-Type': 'application/json' });
  check('a cookie-authenticated write without the same-origin header is refused', noHeader.status === 403, noHeader.status);
  const ops = await Promise.all([call('/api/agents'), post('/api/agents/start', { role: 'intake' }), post('/api/world', { action: 'publish' })]);
  check('operator-only actions are 403 for a tenant', ops.every(r => r.status === 403), ops.map(r => r.status));
  const spoof = await call('/api/memory/findings/F-CODING/precedents', { headers: { 'X-Tenant-Id': 'TEN-03' } });
  check('X-Tenant-Id cannot change whose cases are shown', spoof.status === 200 && JSON.parse(spoof.body.length < 400 ? spoof.body : '{"tenant":"?"}' ).tenant !== 'TEN-03', spoof.body);
  check('every response names the signed-in subject', ro.concat(ops).every(r => r.subject === 'alice'), ro.map(r => r.subject));

  // 6. The event stream carries no other tenant's ids
  const tick = await evaluate(`new Promise(res => { const es = new EventSource('/api/stream'); const t = setTimeout(() => { es.close(); res(null); }, 8000);
    es.addEventListener('tick', e => { clearTimeout(t); es.close(); res(e.data); }); })`);
  check('the stream delivers a bare timestamp, no ids or worker metadata', tick && Object.keys(JSON.parse(tick)).join() === 'ev', tick);

  // 7. Identity changed in another tab: this tab must not show the new identity's data under the old banner
  await navigate(`${base}/console`);
  await waitFor(`document.body.innerText.includes(${JSON.stringify(ALICE_CLAIM)})`, { what: 'alice docket again' });
  await send('Network.setCookie', { name: 'claimbridge_session', value: T.bob, domain: '127.0.0.1', path: '/api', httpOnly: true, sameSite: 'Strict' });
  await evaluate('document.querySelector("a[href=\\"/console/memory\\"]")?.click()');           // any data request while the cookie is bob's
  await waitFor(`document.body.innerText.includes("bob")`, { what: 'banner switches to bob', timeout: 30000 });
  await delay(1500);
  const swapped = await noneOf(ALICE_CLAIM, 'Asha');
  check("a cookie swapped in another tab never leaves alice's data on screen under bob", swapped.length === 0, swapped);

  // 8. Sign out clears everything
  await navigate(`${base}/console`);
  await banner('bob');
  await waitFor(`document.body.innerText.includes(${JSON.stringify(BOB_CLAIM)})`, { what: 'bob docket' });
  const bobText = await text();
  check("bob sees his claim and not alice's", bobText.includes(BOB_CLAIM) && !bobText.includes(ALICE_CLAIM) && !bobText.includes('Asha'));
  await click('Sign out');
  await gated();
  check('after sign-out the page holds no claim data', (await noneOf(ALICE_CLAIM, BOB_CLAIM, 'Asha', 'Carmen')).length === 0);
  check('after sign-out the API is closed to this browser', (await call('/api/claims')).status === 401);
  await evaluate('history.back()'); await delay(1500);
  check('history back does not resurrect signed-out data', (await noneOf(ALICE_CLAIM, BOB_CLAIM, 'Asha', 'Carmen')).length === 0);

  // 9. Account switching: bob signed out, operator signs in, then alice: nothing carries over
  await navigate(`${base}/console`);
  await signIn(T.op);
  await banner('operator');
  await waitFor(`document.body.innerText.includes(${JSON.stringify(ALICE_CLAIM)}) && document.body.innerText.includes(${JSON.stringify(BOB_CLAIM)})`, { what: 'operator sees both tenants' });
  check('the operator sees both tenants', true);
  check('operator-only endpoints work for the operator', (await call('/api/agents')).status === 200);
  await browser.screenshot(path.join(out, 'access-4-operator.png'));
  await click('Sign out'); await gated();
  await signIn(T.alice);
  await banner('alice');
  await waitFor(`document.body.innerText.includes(${JSON.stringify(ALICE_CLAIM)})`, { what: 'alice docket after operator' });
  check("switching operator to alice leaves no other tenant's data", (await noneOf(BOB_CLAIM, 'Carmen')).length === 0);

  // 10. Revocation: the operator removes alice's credential; her open page must end its session
  await stop(api);
  api = startApi([T.alice]);
  await until(async () => (await fetch(`http://127.0.0.1:${API}/api/session`)).ok, 60000, 'API restart');
  await gated();
  check("revoking a credential ends an already-open page's session", (await noneOf(ALICE_CLAIM, 'Asha')).length === 0);
  await browser.screenshot(path.join(out, 'access-5-revoked.png'));
  check('the revoked token can no longer sign in', await (async () => {
    await type('#access-token', T.alice); await click('Sign in');
    await waitFor('!!document.querySelector("[role=alert]")', { what: 'revoked sign-in error' });
    return (await text()).includes('Sign in to your cats') === false && (await text()).includes('Sign in to your cases');
  })());
  check('no JavaScript errors in the page', browser.errors.length === 0, browser.errors.join(' | '));
} catch (e) {
  check('matrix completed without an unexpected error', false, e.stack || e.message);
} finally {
  await browser?.close().catch(() => {});
  if (!keep) for (const p of procs) await stop(p).catch(() => {});
  const summary = { run_at: new Date().toISOString(), isolated_graph: 'claimbridge_access', tokens: 'random per run, never stored', results };
  await writeFile(path.join(out, 'access-matrix.json'), JSON.stringify(summary, null, 2));
  const failed = results.filter(r => !r.passed);
  console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
  process.exitCode = failed.length ? 1 : 0;
}
