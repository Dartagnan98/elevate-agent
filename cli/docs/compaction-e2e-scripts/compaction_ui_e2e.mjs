import { chromium } from 'playwright';
import fs from 'fs';

const URL = 'http://127.0.0.1:9143/?token=hardentest';
const TRACE = '/tmp/elevate-harden.GzsCa5/logs/compaction-trace.jsonl';
const SHOT = '/tmp/harden-work';
fs.mkdirSync(SHOT, { recursive: true });

const traceCount = (ev) => {
  try {
    const lines = fs.readFileSync(TRACE, 'utf8').split('\n').filter(Boolean);
    let c = 0;
    for (const l of lines) { try { if (JSON.parse(l).event === ev) c++; } catch {} } return c;
  } catch { return 0; }
};
const traceHas = (ev) => traceCount(ev) > 0;

const snapshotRows = (pg) => pg.evaluate(() => {
  const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const user = [...document.querySelectorAll('.user-msg')].map(e => norm(e.innerText)).filter(Boolean);
  const asst = [...document.querySelectorAll('.chat-message-prose')].map(e => norm(e.innerText).slice(0, 120)).filter(Boolean);
  const bodyText = document.body.innerText;
  const internal = /\[CONTEXT COMPACTION\]|preserved plan\/todo|\[preserved plan|RECENT AUTONOMOUS ACTIVITY|\[CONTEXT SUMMARY\]/i;
  const sessionRows = document.querySelectorAll('.session-row').length;
  return {
    userCount: user.length, asstCount: asst.length,
    userTexts: user, asstTexts: asst,
    hasInternal: internal.test(bodyText),
    internalMatch: (bodyText.match(internal) || [null])[0],
    sessionRows,
  };
});

const fail = (m) => { console.log('ASSERT-FAIL: ' + m); process.exitCode = 1; };
const ok = (m) => console.log('  ok: ' + m);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.setDefaultTimeout(60000);

console.log('open dashboard');
await page.goto(URL, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);
try { await page.getByRole('button', { name: /New chat/i }).first().click(); await page.waitForTimeout(1500); } catch {}

const compactBaseline = traceCount('agent.compress_context_done');
const rotBaseline = traceCount('agent.session_rotation_done');

const WORKLOAD =
  'Read the file tui_gateway/server.py IN FULL using read_file (it is very large, ~14000 lines; ' +
  'issue several read_file calls with offset/limit to cover the entire file end to end). ' +
  'Then read agent/context_compressor.py IN FULL the same way. ' +
  'Do not stop until BOTH files have been read in their entirety. ' +
  'After both are fully read, reply with the single word DONE.';

const ta = page.locator('textarea.composer-input');
await ta.click();
await ta.fill(WORKLOAD);
await ta.press('Enter');
console.log('workload submitted; waiting for compaction…');

let before = null, after = null, maxUser = 0, maxAsst = 0, sawInternal = false, internalSample = null;
const seenUserTexts = new Set();
const deadline = Date.now() + 16 * 60 * 1000; // 16 min hard cap
let pollIdx = 0, lastChangeAt = Date.now(), lastSig = '';
let firstCompactSeen = false;

while (Date.now() < deadline) {
  await page.waitForTimeout(4000);
  pollIdx++;
  let snap;
  try { snap = await snapshotRows(page); } catch (e) { continue; }
  maxUser = Math.max(maxUser, snap.userCount);
  maxAsst = Math.max(maxAsst, snap.asstCount);
  snap.userTexts.forEach(t => seenUserTexts.add(t));
  if (snap.hasInternal) { sawInternal = true; internalSample = snap.internalMatch; }

  const compactNow = traceCount('agent.compress_context_done') - compactBaseline;
  const sig = snap.userCount + '/' + snap.asstCount;
  if (sig !== lastSig) { lastSig = sig; lastChangeAt = Date.now(); }

  if (!firstCompactSeen && compactNow >= 1) {
    firstCompactSeen = true;
    before = snap;
    await page.screenshot({ path: `${SHOT}/ui_e2e_BEFORE_compaction.png` });
    console.log(`  [poll ${pollIdx}] FIRST COMPACTION detected (compactions=${compactNow}); captured BEFORE snapshot user=${snap.userCount} asst=${snap.asstCount}`);
  } else if (firstCompactSeen) {
    after = snap; // keep latest post-compaction snapshot
  }
  if (pollIdx % 5 === 0) {
    console.log(`  [poll ${pollIdx}] user=${snap.userCount} asst=${snap.asstCount} compactions=${compactNow} internal=${snap.hasInternal} idleSec=${Math.round((Date.now()-lastChangeAt)/1000)}`);
  }

  // completion: DONE present AND transcript stable for 25s AND at least one compaction
  const doneText = snap.asstTexts.some(t => /\bDONE\b/.test(t)) || (await page.evaluate(() => /\bDONE\b/.test(document.body.innerText)));
  const stable = (Date.now() - lastChangeAt) > 25000;
  if (firstCompactSeen && doneText && stable) { console.log('  turn complete + stable'); break; }
  if (firstCompactSeen && stable && (Date.now() - lastChangeAt) > 90000) { console.log('  stable 90s post-compaction (no DONE) — proceeding'); break; }
}

if (after == null) after = await snapshotRows(page);
await page.screenshot({ path: `${SHOT}/ui_e2e_AFTER_compaction.png` });

console.log('\n=== ASSERTIONS (live session) ===');
const compactions = traceCount('agent.compress_context_done') - compactBaseline;
const rotations = traceCount('agent.session_rotation_done') - rotBaseline;
if (compactions >= 1) ok(`compaction fired during the UI run (${compactions})`); else fail(`no compaction fired (${compactions}) — workload too small`);
if (rotations === 0) ok('ZERO session rotations during the UI run'); else fail(`${rotations} session rotation(s) fired`);

if (before) {
  // append-only: every user message visible BEFORE compaction is still visible AFTER
  const missing = before.userTexts.filter(t => !after.userTexts.includes(t));
  if (missing.length === 0) ok(`append-only: all ${before.userTexts.length} pre-compaction user row(s) still visible after`); else fail(`user rows vanished across compaction: ${JSON.stringify(missing)}`);
  if (after.userCount >= before.userCount) ok(`user row count monotonic (${before.userCount} -> ${after.userCount})`); else fail(`user row count shrank ${before.userCount} -> ${after.userCount}`);
  if (after.asstCount >= before.asstCount - 0) ok(`assistant row count did not shrink (${before.asstCount} -> ${after.asstCount})`); else fail(`assistant rows shrank ${before.asstCount} -> ${after.asstCount}`);
} else {
  console.log('  (no discrete BEFORE snapshot captured — compaction likely fired before first poll; relying on final-state + reopen assertions)');
}
if (!sawInternal && !after.hasInternal) ok('no internal compaction bubbles in the visible transcript'); else fail(`internal compaction text leaked into UI: ${internalSample || after.internalMatch}`);
if (after.sessionRows >= 1) ok(`session still present in the list (${after.sessionRows} row(s))`); else fail('session disappeared from the list');

const liveUserTexts = after.userTexts.slice();

// ===== REOPEN: reload the page and reopen the session =====
console.log('\n=== REOPEN (reload) ===');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(3500);
// click the top session row to reopen it
try { await page.locator('.session-row').first().click(); await page.waitForTimeout(3000); } catch {}
await page.waitForTimeout(2000);
const reopened = await snapshotRows(page);
await page.screenshot({ path: `${SHOT}/ui_e2e_REOPEN.png` });

const reopenMissing = liveUserTexts.filter(t => !reopened.userTexts.includes(t));
if (liveUserTexts.length >= 1 && reopenMissing.length === 0) ok(`reopen rebuilt all ${liveUserTexts.length} user row(s) identically`); else fail(`reopen lost user rows: ${JSON.stringify(reopenMissing)} (live=${liveUserTexts.length} reopened=${reopened.userTexts.length})`);
if (!reopened.hasInternal) ok('reopen: no internal compaction bubbles'); else fail(`reopen leaked internal text: ${reopened.internalMatch}`);
if (reopened.sessionRows >= 1) ok('reopen: session still in list'); else fail('reopen: session missing from list');

console.log('\nRESULT: ' + (process.exitCode ? 'FAIL' : 'PASS'));
console.log(`screenshots: ${SHOT}/ui_e2e_BEFORE_compaction.png, ui_e2e_AFTER_compaction.png, ui_e2e_REOPEN.png`);
await browser.close();
