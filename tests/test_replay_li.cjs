// Offline integration checks for the first drawn archive and its historical scores.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.argv[2] || 'playwright');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.argv[3] || undefined});
  try {
    const page = await browser.newPage({viewport:{width:1100,height:1050}, acceptDownloads:true});
    const errors = [], requests = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()); });
    await page.route(/^https?:/, route => route.abort());
    const root = path.join(__dirname, '..');
    const journal = JSON.parse(await fs.readFile(path.join(root, 'engine-games/li-v02-classical/game.json'), 'utf8'));
    const pgnSource = await fs.readFile(path.join(root, 'engine-games/li-v02-classical/game.pgn'), 'utf8');
    const shots = path.join(root, 'images/replays');
    await fs.mkdir(shots, {recursive:true});
    await page.goto(pathToFileURL(path.join(root, 'replays/li-replay.html')).href);
    const data = JSON.parse(await page.locator('#replay-data').textContent());
    assert.equal(data.frames.length, 140);
    assert.deepEqual(data.frames.slice(1).map(f => f.move.san), journal.san);
    assert.deepEqual(data.frames.slice(1).map(f => f.move.uci), journal.uci);
    assert.equal(data.headers.Result, '1/2-1/2');
    assert.equal(data.outcome.winner, null);
    assert.equal(data.evaluations.recordedChoices, 70);
    assert.equal(data.evaluations.perspective, 'white');
    assert.ok(data.frames.filter(f => f.move?.color === 'black').every(f => f.evaluation === null));
    assert.equal(await page.locator('h1').innerText(), 'Astra (Ultra) vs. Li');
    assert.match(await page.locator('.result').getAttribute('aria-label'), /draw.*insufficient material/i);
    assert.equal(await page.locator('#bottom-player .name-text').innerText(), 'Astra');
    assert.equal(await page.locator('#top-player .player-meta').innerText(), '2000 · Black');
    assert.equal(await page.locator('#pieces [data-present="true"]').count(), 32);
    const score = page.locator('#engine-score-value');
    const seek = async ply => {
      await page.locator('#timeline').fill(String(ply));
      assert.equal(await page.locator('#board').getAttribute('data-ply'), String(ply));
    };
    const piece = (color, type, square) => page.locator(`#pieces .${color}[data-present="true"][data-type="${type}"][data-square="${square}"]`);
    assert.equal(await score.innerText(), 'No recorded evaluation');
    for (const [move, cp] of [[1,0], [20,56], [43,229], [55,316], [62,246], [63,25]]) {
      await seek(move * 2 - 1);
      assert.equal(await score.innerText(), `${cp >= 0 ? '+' : ''}${(cp / 100).toFixed(2)} pawns`);
      assert.match(await page.locator('#engine-score-detail').innerText(), /Pre-move search.*Positive favors White/);
      await page.locator('#next').click();
      assert.equal(await score.innerText(), 'No recorded evaluation');
      assert.match(await page.locator('#engine-score-detail').innerText(), /Black move/);
    }
    for (const [ply, color, rank] of [[9, 'white', '1'], [32, 'black', '8']]) {
      await seek(ply);
      assert.equal(await piece(color, 'k', 'g' + rank).count(), 1);
      assert.equal(await piece(color, 'r', 'f' + rank).count(), 1);
      assert.match(await page.locator('#selected-detail').innerText(), /Kingside castling/);
    }
    await seek(11); // 6.Bxc6 captures a knight.
    assert.equal(await piece('white', 'b', 'c6').count(), 1);
    assert.equal(await piece('black', 'n', 'c6').count(), 0);
    await page.locator('#previous').click();
    assert.equal(await piece('black', 'n', 'c6').count(), 1);
    await seek(123); // Recorded +2.46 before the sacrifice was accepted.
    await page.screenshot({path:path.join(shots, 'li-desktop.png'), fullPage:true, animations:'disabled'});
    await page.locator('#last').click();
    assert.equal(await page.locator('#board').getAttribute('data-ply'), '139');
    assert.equal(await page.locator('#pieces [data-present="true"]').count(), 2);
    assert.equal(await piece('white', 'k', 'e6').count(), 1);
    assert.equal(await piece('black', 'k', 'h5').count(), 1);
    assert.equal(await score.innerText(), 'Draw');
    assert.match(await page.locator('#engine-score-detail').innerText(), /insufficient material/i);
    assert.equal(await page.locator('#bottom-player .turn').innerText(), 'DRAW');
    assert.equal(await page.locator('#top-player .turn').innerText(), 'DRAW');
    assert.match(await page.locator('#selected-detail').innerText(), /draw.*insufficient material/i);
    assert.doesNotMatch(await page.locator('#selected-detail').innerText(), /wins|checkmate|resigned/i);
    await page.locator('#engine-score summary').click();
    assert.match(await page.locator('#engine-score-note').innerText(), /0\.00/);
    await page.locator('#flip').click();
    assert.equal(await score.innerText(), 'Draw');
    assert.equal(await page.locator('#bottom-player .name-text').innerText(), 'Li');
    assert.equal(await page.locator('#bottom-player .turn').innerText(), 'DRAW');
    await page.locator('#flip').click();
    const [download] = await Promise.all([page.waitForEvent('download'), page.locator('#download-pgn').click()]);
    // Python's text reader normalizes source CRLF to LF in the embedded PGN.
    assert.equal(await fs.readFile(await download.path(), 'utf8'), pgnSource.replace(/\r\n/g, '\n'));
    await page.locator('#first').click();
    await page.locator('h1').click();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#board').getAttribute('data-ply'), '1');
    await page.keyboard.press('End');
    assert.equal(await page.locator('#board').getAttribute('data-ply'), '139');
    await seek(138);
    await page.locator('#speed').selectOption('550');
    await page.locator('#play').click();
    await page.waitForFunction(() => document.querySelector('#board').dataset.ply === '139');
    assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'false');
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height:844});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    }
    await page.setViewportSize({width:390, height:844});
    await seek(139);
    await page.screenshot({path:path.join(shots, 'li-mobile.png'), fullPage:true, animations:'disabled'});
    await page.locator('#first').click();
    const fills = {};
    for (const color of ['white', 'black']) {
      const pawns = page.locator(`#pieces .${color}[data-present="true"][data-type="p"]`);
      assert.equal(await pawns.count(), 8);
      assert.equal(await pawns.first().locator('use').getAttribute('href'), '#piece-p');
      fills[color] = await pawns.first().locator('use').evaluate(e => getComputedStyle(e).fill);
    }
    assert.notEqual(fills.white, fills.black);
    await page.screenshot({path:path.join(shots, 'li-start-mobile.png'), fullPage:true, animations:'disabled'});
    await page.goto(pathToFileURL(path.join(root, 'replays/index.html')).href);
    assert.equal(await page.locator('a.game').count(), 9);
    assert.match(await page.locator('.intro').innerText(), /Nine recorded games.*four trials/);
    const li = page.locator('a.game').filter({hasText:'Astra (Ultra) vs. Li'});
    assert.equal(await li.getAttribute('href'), 'https://astra-vs-li.netlify.app/');
    assert.match(await li.innerText(), /Draw.*½–½/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    console.log('Li replay checks passed: all moves, draw labels, scores/absence, castling, capture/rewind, flip, navigation, playback, PGN, mobile SVG pawns, index, offline operation.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
