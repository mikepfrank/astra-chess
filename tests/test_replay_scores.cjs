// Offline integration checks. Uses an existing Playwright and browser install.
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.argv[2] || 'playwright');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.argv[3] || undefined});
  try {
    const page = await browser.newPage({viewport:{width:1100,height:1000}});
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    await page.goto(pathToFileURL(path.join(__dirname, '../replays/wally-engine-v02-replay.html')).href);
    const score = page.locator('#engine-score-value');
    assert.equal(await score.innerText(), 'No recorded evaluation');
    await page.locator('#next').click();
    assert.equal(await score.innerText(), '+0.00 pawns');
    assert.match(await page.locator('#engine-score-detail').innerText(), /1\. Nc3.*6 plies/);
    await page.locator('#next').click();
    assert.equal(await score.innerText(), 'No recorded evaluation');
    assert.match(await page.locator('#engine-score-detail').innerText(), /Black move/);
    for (const [ply, label] of [[57,'Mate in 2'], [59,'Mate in 1'], [61,'Checkmate']]) {
      await page.locator(`[data-ply="${ply}"].move-button`).click();
      assert.equal(await score.innerText(), label);
      assert.equal(await page.locator('#board').getAttribute('data-ply'), String(ply));
      await page.locator('#flip').click();
      assert.equal(await score.innerText(), label);
    }
    assert.equal(await page.locator('#pieces [data-present="true"]').count(), 18);
    await page.locator('#first').click();
    await page.locator('#timeline').fill('53');
    assert.equal(await score.innerText(), '+22.25 pawns');
    assert.equal(await page.locator('#pieces [data-present="true"][data-type="q"]').count(), 2);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#engine-score summary').click();
    assert.match(await page.locator('#engine-score-note').innerText(), /before this move/);
    const download = await page.locator('#download-pgn').getAttribute('href');
    assert.match(download, /^blob:/);
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    // The existing generated archive still behaves without any evaluation data.
    await page.goto(pathToFileURL(path.join(__dirname, '../replays/wally-engine-replay.html')).href);
    await page.locator('#next').click();
    assert.equal(await page.locator('#board').getAttribute('data-ply'), '1');
    console.log('Replay browser checks passed: scores, Black-frame absence, mate convention, navigation, flip, promotion, mobile, offline download, legacy replay.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
