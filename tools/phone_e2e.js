const { chromium, devices } = require('playwright');
const PORT = process.argv[2], OUT = process.argv[3];
const base = `http://127.0.0.1:${PORT}`;
let token, fails = [], n = 0;
const ok = (name, cond, d='') => { n++; console.log(`${name.padEnd(40)} ${cond ? 'PASS' : 'FAIL'}  ${d}`); if (!cond) fails.push(name); };
async function st() { const r = await fetch(base + '/api/v1/state', { headers: { Authorization: 'Bearer ' + token } }); return r.json(); }
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const r = await fetch(base + '/api/v1/session', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin: '246810' }) });
  token = (await r.json()).token;
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['iPhone 13'], acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(e.message));
  await page.goto(base + '/');
  await page.waitForSelector('#pairView:not([hidden])', { timeout: 8000 }).catch(() => {});
  ok('pair screen shows first', await page.isVisible('#pairView'));
  await page.screenshot({ path: OUT + '/1_pair.png' });
  await page.fill('#pin', '111111'); await page.click('#pairForm button');
  await sleep(800);
  ok('wrong PIN keeps you on pair screen', await page.isVisible('#pairView'));
  await page.fill('#pin', '246810'); await page.click('#pairForm button');
  await page.waitForSelector('#app:not([hidden])', { timeout: 8000 }).catch(() => {});
  ok('correct PIN opens the remote', await page.isVisible('#app'));
  // load a script via Write tab
  await page.click('[data-tab="write"]');
  await page.fill('#title', 'Zebra phone script');
  await page.fill('#body', '# One\nHello from the phone test, this is line one.\nAnd line two follows here.\n# Two\nSection two starts now.\n');
  ok('word count updates', /\d+ words/.test(await page.textContent('#count')) && !(await page.textContent('#count')).startsWith('0 '));
  await page.click('#saveLoad'); await sleep(1200);
  let s = await st();
  ok('Save & load puts it on the prompter', s.script && s.script.title === 'Zebra phone script', JSON.stringify(s.script));
  await page.screenshot({ path: OUT + '/2_write.png' });
  await page.click('[data-tab="remote"]'); await sleep(500);
  await page.screenshot({ path: OUT + '/3_remote.png', fullPage: true });
  const act = async (a) => { await page.click(`[data-action="${a}"]`); await sleep(700); return st(); };
  let s0 = await st();
  s = await act('bigger'); ok('Bigger button', s.font_px > s0.font_px);
  s = await act('smaller'); ok('Smaller button', s.font_px === s0.font_px);
  s = await act('faster'); ok('Faster button', s.wpm > s0.wpm);
  s = await act('slower'); ok('Slower button', s.wpm === s0.wpm);
  s = await act('play'); await sleep(2500); s = await st();
  ok('Play button scrolls', (s.playing || s.counting) && s.progress > 0, 'progress ' + s.progress);
  ok('Play button turns into Pause', /Pause/.test(await page.textContent('#ppText')));
  s = await act('play'); ok('Pause button', !s.playing);
  s = await act('ahead'); const pa = s.pos; s = await act('back'); ok('Ahead / Back', pa > s.pos, `${pa} -> ${s.pos}`);
  s = await act('restart'); ok('Restart', s.progress < 0.01);
  await page.waitForSelector('#secWrap:not([hidden])', { timeout: 3000 }).catch(() => {});
  ok('Sections appear', await page.isVisible('#secWrap'));
  s = await act('next_section'); const p1 = s.pos; s = await act('prev_section'); ok('Next / previous section', p1 > s.pos);
  s = await act('hide'); ok('Hide', s.window_visible === false);
  ok('status says hidden', /hidden/i.test(await page.textContent('#conn')));
  s = await act('hide'); ok('Show', s.window_visible === true);
  const g0 = (await st()).ghost_opacity;
  s = await act('ghost_less'); ok('More see-through', s.ghost_opacity < g0, `${g0} -> ${s.ghost_opacity}`);
  s = await act('ghost_more'); ok('More solid', s.ghost_opacity > g0 - 0.11 && s.ghost_opacity >= g0 - 0.001, `${s.ghost_opacity}`);
  s = await act('voice'); ok('Voice Follow button', s.voice_follow === true);
  ok('Voice button label updates', /on/i.test(await page.textContent('#voiceText')));
  s = await act('voice'); ok('Voice Follow off', s.voice_follow === false);
  s = await act('read_aloud'); await sleep(800); s = await st();
  ok('Read aloud button', s.reading_aloud === true || s.tts_engine !== '', `reading=${s.reading_aloud} engine=${s.tts_engine}`);
  if (s.reading_aloud) { await act('read_aloud'); }
  // library
  await page.click('[data-tab="library"]'); await sleep(800);
  const items = await page.$$('#list .item');
  ok('Library lists scripts', items.length >= 1, items.length + ' items');
  await page.screenshot({ path: OUT + '/4_library.png' });
  await page.fill('#search', 'Zebra'); await sleep(700);
  ok('Search filters', (await page.$$('#list .item')).length === 1);
  await page.fill('#search', ''); await sleep(700);
  // upload
  await page.click('[data-tab="write"]');
  await page.setInputFiles('#file', { name: 'uploaded.txt', mimeType: 'text/plain', buffer: Buffer.from('Uploaded script body from the phone.\n') });
  await sleep(1200); s = await st();
  ok('Upload a file', s.script && /uploaded/i.test(s.script.title), JSON.stringify(s.script));
  // delete (two taps)
  await page.click('[data-tab="library"]'); await sleep(800);
  const before = (await page.$$('#list .item')).length;
  const del = page.locator('#list .item').first().locator('button.danger');
  await del.click(); ok('Delete asks "Sure?"', (await del.textContent()) === 'Sure?');
  await del.click(); await sleep(1000);
  ok('Delete removes it', (await page.$$('#list .item')).length === before - 1);
  // edit
  await page.locator('#list .item').first().locator('button', { hasText: 'Edit' }).click(); await sleep(800);
  ok('Edit opens the script', /Editing/.test(await page.textContent('#editing')));
  // screen view
  await page.click('[data-tab="screen"]'); await sleep(2500);
  const w1 = await page.$eval('#screenImg', i => i.naturalWidth);
  ok('Screen tab shows the computer screen', w1 > 0, 'naturalWidth ' + w1 + ' / ' + await page.textContent('#screenMsg'));
  const src1 = await page.$eval('#screenImg', i => i.src); await sleep(2200);
  ok('Screen view refreshes', (await page.$eval('#screenImg', i => i.src)) !== src1);
  await page.screenshot({ path: OUT + '/5_screen.png' });
  await page.click('#screenPause'); const src2 = await page.$eval('#screenImg', i => i.src); await sleep(2200);
  ok('Screen view pauses', (await page.$eval('#screenImg', i => i.src)) === src2 && /Resume/.test(await page.textContent('#screenPause')));
  await page.click('#screenPause');
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 8000 }).catch(() => null), page.click('#shotSave')]);
  const dlPath = dl ? await dl.path() : null;
  const dlSize = dlPath ? require('fs').statSync(dlPath).size : 0;
  ok('Save screenshot downloads a full-size image', dl && /\.jpg$/.test(dl.suggestedFilename()) && dlSize > 5000, dl ? dl.suggestedFilename() + ' ' + dlSize + ' bytes' : 'no download');
  await page.click('#shotAsk'); await sleep(500);
  ok('Ask AI about this opens the AI tab with the screen on', await page.isVisible('#tab-ai') && await page.isChecked('#aiScreen') && (await page.inputValue('#aiText')).length > 0);
  await page.fill('#aiText', '');
  // AI chat (no key on the test profile -> friendly guidance, never a crash)
  await page.click('[data-tab="ai"]'); await sleep(800);
  ok('AI tab explains where to add the key', /API key/.test(await page.textContent('#aiInfo')));
  await page.fill('#aiText', 'What should I say next?'); await page.click('#aiSend'); await sleep(1500);
  ok('AI without a key shows a friendly message', /Settings/.test(await page.textContent('#aiLog')) && (await page.$$('.msg.error')).length === 1);
  await page.screenshot({ path: OUT + '/6_ai.png' });
  // touch targets
  const small = await page.$$eval('button', bs => bs.filter(b => b.offsetParent && (b.getBoundingClientRect().height < 44)).map(b => b.textContent.trim()).slice(0, 8));
  ok('touch targets >= 44px', small.length === 0, small.join(' | '));
  ok('no console errors / CSP violations', errors.filter(e => !/40[01] \(/.test(e)).length === 0, errors.join(' | ').slice(0, 300));
  await browser.close();
  console.log(`RESULT: ${fails.length ? 'FAILED (' + fails.length + '/' + n + '): ' + fails.join(', ') : 'OK (' + n + ' checks)'}`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error('HARNESS', e); process.exit(2); });
