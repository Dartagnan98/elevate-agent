import { chromium } from 'playwright';
import fs from 'fs';
const URL = 'http://127.0.0.1:9143/?token=hardentest';
const TRACE = '/tmp/elevate-harden.GzsCa5/logs/compaction-trace.jsonl';
const SHOT = '/tmp/harden-work';
fs.mkdirSync(SHOT, { recursive: true });
const traceCount = (ev) => { try { return fs.readFileSync(TRACE,'utf8').split('\n').filter(Boolean).reduce((a,l)=>{try{return a+(JSON.parse(l).event===ev?1:0)}catch{return a}},0);}catch{return 0;} };
const snap = (pg) => pg.evaluate(() => {
  const norm = s => (s||'').replace(/\s+/g,' ').trim();
  const user = [...document.querySelectorAll('.user-msg')].map(e=>norm(e.innerText)).filter(Boolean);
  const internal = /\[CONTEXT COMPACTION\]|preserved plan\/todo|\[preserved plan|RECENT AUTONOMOUS ACTIVITY|\[CONTEXT SUMMARY\]/i;
  const bt = document.body.innerText;
  return { user, userCount:user.length, hasInternal: internal.test(bt), internalMatch:(bt.match(internal)||[null])[0], sessionRows:document.querySelectorAll('.session-row').length, bodyHas:(s)=>bt.includes(s) };
});
const bodyHas = (pg,s)=>pg.evaluate(t=>document.body.innerText.includes(t), s);
const fail=m=>{console.log('ASSERT-FAIL: '+m);process.exitCode=1;};
const ok=m=>console.log('  ok: '+m);

const TURNS = [
  { p:'Use the read_file tool to read tui_gateway/server.py with offset 1 and limit 5000 (one call). After the tool returns, reply with exactly: DONE1', mark:'DONE1' },
  { p:'Use the read_file tool to read agent/context_compressor.py with offset 1 and limit 2400 (one call). After the tool returns, reply with exactly: DONE2', mark:'DONE2' },
  { p:'Use the read_file tool to read elevate_state.py with offset 1 and limit 2600 (one call). After the tool returns, reply with exactly: DONE3', mark:'DONE3' },
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport:{width:1280,height:900} });
page.setDefaultTimeout(60000);
await page.goto(URL,{waitUntil:'networkidle'}); await page.waitForTimeout(2500);
try { await page.getByRole('button',{name:/New chat/i}).first().click(); await page.waitForTimeout(1500); } catch {}
const compactBase = traceCount('agent.compress_context_done');
const rotBase = traceCount('agent.session_rotation_done');

let firstSnap=null;
for (let i=0;i<TURNS.length;i++){
  const {p,mark}=TURNS[i];
  const ta = page.locator('textarea.composer-input');
  await ta.click(); await ta.fill(p); await ta.press('Enter');
  console.log(`turn ${i+1} submitted; waiting for ${mark}…`);
  const cap = Date.now()+6*60*1000;
  while(Date.now()<cap){
    await page.waitForTimeout(4000);
    if (await bodyHas(page, mark)) {
      // settle a bit to let the run finish + composer re-enable
      await page.waitForTimeout(6000);
      break;
    }
  }
  const s = await snap(page);
  const comp = traceCount('agent.compress_context_done')-compactBase;
  console.log(`  turn ${i+1} done: userBubbles=${s.userCount} compactions=${comp} internal=${s.hasInternal} mark=${await bodyHas(page,mark)}`);
  if (i===0){ firstSnap=s; await page.screenshot({path:`${SHOT}/ui_e2e_multi_AFTER_turn1.png`}); }
}
const finalSnap = await snap(page);
await page.screenshot({ path:`${SHOT}/ui_e2e_multi_AFTER_turn3.png` });

console.log('\n=== ASSERTIONS (multi-turn live) ===');
const compactions = traceCount('agent.compress_context_done')-compactBase;
const rotations = traceCount('agent.session_rotation_done')-rotBase;
if (compactions>=1) ok(`compaction(s) fired across the run (${compactions})`); else fail(`no compaction fired (${compactions})`);
if (rotations===0) ok('ZERO session rotations across the run'); else fail(`${rotations} rotation(s) fired`);
if (finalSnap.userCount===TURNS.length) ok(`all ${TURNS.length} user turns visible (append-only, none vanished)`); else fail(`expected ${TURNS.length} user bubbles, got ${finalSnap.userCount}: ${JSON.stringify(finalSnap.user)}`);
if (firstSnap){ const miss=firstSnap.user.filter(t=>!finalSnap.user.includes(t)); if(miss.length===0) ok('turn-1 user bubble still present after later compactions'); else fail(`turn-1 bubble vanished: ${JSON.stringify(miss)}`); }
if (!finalSnap.hasInternal) ok('no internal compaction bubbles in the visible transcript'); else fail(`internal text leaked: ${finalSnap.internalMatch}`);
if (finalSnap.sessionRows>=1) ok(`session still in list (${finalSnap.sessionRows} rows)`); else fail('session vanished from list');
const liveUsers = finalSnap.user.slice();

console.log('\n=== REOPEN (reload) ===');
await page.reload({waitUntil:'networkidle'}); await page.waitForTimeout(3500);
try { await page.locator('.session-row').first().click(); await page.waitForTimeout(3500); } catch {}
const re = await snap(page);
await page.screenshot({ path:`${SHOT}/ui_e2e_multi_REOPEN.png` });
const reMiss = liveUsers.filter(t=>!re.user.includes(t));
if (liveUsers.length>=1 && reMiss.length===0 && re.userCount===liveUsers.length) ok(`reopen rebuilt all ${liveUsers.length} user turns identically`); else fail(`reopen mismatch: live=${liveUsers.length} reopened=${re.userCount} missing=${JSON.stringify(reMiss)}`);
if (!re.hasInternal) ok('reopen: no internal bubbles'); else fail(`reopen leaked internal: ${re.internalMatch}`);

console.log('\nRESULT: '+(process.exitCode?'FAIL':'PASS'));
await browser.close();
