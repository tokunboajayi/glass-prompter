// Website images of the phone remote (Remote, Screen and AI tabs). Network calls for the screen and the AI are
// mocked so the pictures are reproducible:  node tools/phone_shots.js PORT OUTDIR SCREEN_JPG
const { chromium, devices } = require('playwright');
const fs = require('fs');
const [port, out, screenJpg] = process.argv.slice(2);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ ...devices['iPhone 13'], deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const shot = fs.readFileSync(screenJpg);
  await page.route('**/api/v1/screen.jpg*', r => r.fulfill({ status: 200, contentType: 'image/jpeg', body: shot }));
  await page.route('**/api/v1/features', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ screen: true, ai: true, ai_model: 'claude-sonnet-5-5' }) }));
  const replies = [
    "Lead with the headline: revenue grew 18% to $5.4M, the best quarter on the chart. Then explain why: subscriptions are now 62% of revenue and churn fell 9%.",
    "Q3 was our strongest quarter yet: revenue up 18% to $5.4 million, driven by subscriptions."];
  let n = 0;
  await page.route('**/api/v1/ai/chat', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ reply: replies[Math.min(n++, replies.length - 1)], saw_screen: true }) }));
  await page.goto(`http://127.0.0.1:${port}/?k=246810`);
  await sleep(1500);
  // show the Windows/macOS 14 badge (this render runs headless on Linux, where hiding isn't available)
  const badge = () => page.evaluate(() => { const p = document.getElementById('conn');
    p.className = 'pill ok'; p.lastElementChild.textContent = 'Hidden from share'; });
  await badge();
  await page.screenshot({ path: out + '/phone_remote.png' });
  await page.click('[data-tab="screen"]'); await sleep(1500);
  await badge(); await page.screenshot({ path: out + '/phone_screen.png' });
  await page.click('[data-tab="ai"]'); await sleep(600);
  for (const q of ['What should I say about this slide?', 'Give me one line to open with.']) {
    await page.fill('#aiText', q); await page.click('#aiSend'); await sleep(900);
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await badge(); await page.screenshot({ path: out + '/phone_ai.png' });
  await browser.close();
})().catch(e => { console.error(e); process.exit(2); });
