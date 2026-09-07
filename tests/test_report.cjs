// Browser integration test using an existing Playwright installation; no download.
// Pass its package directory, then an installed browser channel (e.g. msedge).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.argv[2] || 'playwright');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: process.argv[3] || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 900 } });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    // Synthetic navigation fixture: deliberately includes a captured target to
    // exercise retargeting. It is not an engine proof or an archived chess game.
    const fens = ['7k/8/8/8/4q3/8/4R3/K7 b - - 0 1',
                  '7k/8/8/4q3/8/8/4R3/K7 w - - 1 2',
                  '7k/8/8/4R3/8/8/8/K7 b - - 0 2'];
    const data = {kind:'goal_probe',label:'Target identity UI test',start_fen:fens[0],
      goal:{type:'avoid_capture',side:'black',target:'e4'},horizon_plies:2,status:'unknown',
      proof_status:'refuted',witness_status:'not_searched',settings:{proof_only:true},
      semantics:{unknown:'Cooperative reachability was not examined.'},nodes:10,elapsed_seconds:0.01,
      lines:[{fens,uci:['e4e5','e2e5'],san:['Qe5','Rxe5']}],position_history_fens:[]};
    const template = fs.readFileSync(path.join(__dirname, '../astra_engine/report.template.html'), 'utf8');
    await page.setContent(template.replace('__QUESTION__', data.label).replace('__EVIDENCE__', JSON.stringify(data)));
    let query = JSON.parse(await page.locator('#follow-up').inputValue());
    assert.equal(query.goal.type, 'avoid_capture');
    assert.equal(query.goal.side, 'black');
    assert.equal(query.goal.target, 'e4');
    assert.equal(query.proof_only, true);
    assert.match(await page.locator('#verdict').innerText(), /No forcing strategy/);
    await page.locator('#next').click();
    query = JSON.parse(await page.locator('#follow-up').inputValue());
    assert.equal(query.goal.target, 'e5');
    assert.equal(query.fen, fens[1]);
    assert.deepEqual(query.history_fens, [fens[0]]);
    await page.locator('#next').click();
    assert.equal(await page.locator('#target').inputValue(), '');
    assert.equal(await page.locator('#export-query').isDisabled(), true);
    await page.locator('#start').click();
    assert.equal(await page.locator('#target').inputValue(), 'e4');
    assert.equal(await page.locator('#export-query').isEnabled(), true);
    await page.locator('#mode').selectOption('analyze');
    await page.locator('summary').filter({hasText:'Optional analysis features'}).click();
    await page.locator('#mobility').check();
    await page.locator('#extensions').selectOption('2');
    query = JSON.parse(await page.locator('#follow-up').inputValue());
    assert.equal(query.evaluation.mobility, true);
    assert.equal(query.threat_extensions, 2);
    assert.equal('proof_only' in query, false);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
      JSON.stringify(await page.evaluate(() => [...document.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>({tag:e.tagName,id:e.id,width:e.getBoundingClientRect().width})))));
    assert.equal(await page.locator('.square').count(), 64);
    assert.deepEqual(errors, []);
    console.log('Report browser checks passed: target/side/history, capture retargeting, proof verdict, options, mobile layout.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
