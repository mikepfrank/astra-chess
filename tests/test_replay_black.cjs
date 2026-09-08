// Offline integration checks for the first archive with Astra playing Black.
// Uses an existing Playwright and browser install; no engine or web requests.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.argv[2] || 'playwright');

(async () => {
  const browser = await chromium.launch({headless:true, channel:process.argv[3] || undefined});
  try {
    const page = await browser.newPage({viewport:{width:1100,height:1000}, acceptDownloads:true});
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    await page.route(/^https?:/, route => route.abort());
    await page.goto(pathToFileURL(path.join(__dirname, '../replays/wally-engine-v02-black-replay.html')).href);
    const score = page.locator('#engine-score-value');
    const detail = page.locator('#engine-score-detail');
    const board = page.locator('#board');
    const piece = (color, type, square) => page.locator(`#pieces .${color}[data-present="true"][data-type="${type}"][data-square="${square}"]`);
    const seek = async ply => {
      if (ply === 0) await page.locator('#first').click();
      else await page.locator(`[data-ply="${ply}"].move-button`).click();
      assert.equal(await board.getAttribute('data-ply'), String(ply));
    };
    assert.equal(await page.locator('#bottom-player .name-text').innerText(), 'Astra');
    assert.equal(await page.locator('#bottom-player .player-meta').innerText(), 'Black');
    assert.equal(await page.locator('#top-player .name-text').innerText(), 'Wally');
    assert.equal(await page.locator('#top-player .player-meta').innerText(), '1800 · White');
    assert.deepEqual(await page.locator('#files span').allTextContents(), [...'hgfedcba']);
    assert.deepEqual(await page.locator('#ranks span').allTextContents(), [...'12345678']);
    assert.equal(await page.locator('#pieces [data-present="true"]').count(), 32);
    assert.equal(await piece('black', 'r', 'h8').getAttribute('style'), 'opacity: 1; transform: translate(0%, 700%); z-index: 1;');
    assert.equal(await piece('white', 'r', 'h1').count(), 1);
    assert.equal(await score.innerText(), 'No recorded evaluation');

    await seek(1);
    assert.equal(await score.innerText(), 'No recorded evaluation');
    assert.match(await detail.innerText(), /White move/);
    await page.locator('#next').click();
    assert.equal(await score.innerText(), '+0.13 pawns');
    assert.match(await detail.innerText(), /1… c5.*5 plies.*Positive favors Black/);
    const beforeFlip = await page.locator('#position-title').innerText();
    await page.locator('#flip').click();
    assert.equal(await board.getAttribute('data-ply'), '2');
    assert.equal(await page.locator('#position-title').innerText(), beforeFlip);
    assert.equal(await score.innerText(), '+0.13 pawns');
    assert.equal(await page.locator('#bottom-player .name-text').innerText(), 'Wally');
    assert.equal(await page.locator('#bottom-player .player-meta').innerText(), '1800 · White');
    assert.equal(await page.locator('#top-player .name-text').innerText(), 'Astra');
    assert.equal(await page.locator('#top-player .player-meta').innerText(), 'Black');
    assert.deepEqual(await page.locator('#files span').allTextContents(), [...'abcdefgh']);
    await page.locator('#flip').click();

    for (const [ply, color, rank] of [[16, 'black', '8'], [17, 'white', '1']]) {
      await seek(ply);
      assert.equal(await piece(color, 'k', 'g' + rank).count(), 1);
      assert.equal(await piece(color, 'r', 'f' + rank).count(), 1);
      assert.equal(await piece(color, 'k', 'e' + rank).count(), 0);
      assert.match(await page.locator('#selected-detail').innerText(), /Kingside castling/);
    }
    await seek(19);
    const beforeCapture = await page.locator('#pieces [data-present="true"]').count();
    await page.locator('#next').click();
    assert.equal(await page.locator('#pieces [data-present="true"]').count(), beforeCapture - 1);
    assert.equal(await piece('black', 'n', 'd4').count(), 1);
    assert.equal(await piece('white', 'n', 'd4').count(), 0);
    assert.match(await page.locator('#selected-detail').innerText(), /Captures knight/);

    for (const move of [42,43,44]) {
      await seek(move * 2);
      assert.equal(await score.innerText(), 'No recorded evaluation');
      assert.match(await detail.innerText(), /No qualifying saved search result/);
    }
    for (const [ply, label] of [[92, 'Mate in 2'], [94, 'Mate in 1'], [96, 'Checkmate']]) {
      await seek(ply);
      assert.equal(await score.innerText(), label);
      assert.match(await detail.innerText(), ply === 96 ? /Black wins/ : /Black moves remaining/);
      if (ply < 96) {
        await page.locator('#next').click();
        assert.equal(await score.innerText(), 'No recorded evaluation');
        assert.match(await detail.innerText(), /White move/);
      }
    }
    assert.equal(await piece('white', 'k', 'g2').count(), 1);
    assert.equal(await piece('black', 'r', 'd2').count(), 1);
    assert.equal(await piece('white', 'b', 'd2').count(), 0);
    assert.equal(await page.locator('#pieces [data-present="true"]').count(), 12);
    assert.match(await page.locator('#selected-detail').innerText(), /Captures bishop.*Checkmate.*Black wins/);
    assert.equal(await page.locator('.result strong').innerText(), '0–1');
    assert.equal(await page.locator('#bottom-player .turn').innerText(), 'WINNER');
    assert.match(await board.getAttribute('aria-label'), /Black won by checkmate/);

    // Actual PGN download preserves the players' colors, result, and final move.
    const [download] = await Promise.all([
      page.waitForEvent('download'), page.locator('#download-pgn').click(),
    ]);
    const pgn = await fs.readFile(await download.path(), 'utf8');
    assert.match(pgn, /\[White "Wally"\]/);
    assert.match(pgn, /\[Black "Astra \(Ultra\)"\]/);
    assert.match(pgn, /\[WhiteElo "1800"\]/);
    assert.doesNotMatch(pgn, /\[BlackElo "1800"\]/);
    assert.match(pgn, /48\. Kg2 Rcxd2# 0-1/);

    // Controls must change the selected frame and playback must stop on request.
    await page.locator('#first').click();
    await page.locator('#timeline').fill('90');
    assert.equal(await board.getAttribute('data-ply'), '90');
    assert.equal(await score.innerText(), '+17.05 pawns');
    await page.locator('h1').click();
    await page.keyboard.press('ArrowLeft');
    assert.equal(await board.getAttribute('data-ply'), '89');
    await page.keyboard.press('ArrowRight');
    assert.equal(await board.getAttribute('data-ply'), '90');
    await page.keyboard.press('Home');
    assert.equal(await board.getAttribute('data-ply'), '0');
    await page.keyboard.press('End');
    assert.equal(await board.getAttribute('data-ply'), '96');
    await page.locator('#first').click();
    await page.locator('#speed').selectOption('550');
    await page.locator('h1').click();
    await page.keyboard.press('Space');
    await page.waitForFunction(() => Number(document.querySelector('#board').dataset.ply) >= 1);
    await page.keyboard.press('Space');
    assert.equal(await page.locator('#play').getAttribute('aria-pressed'), 'false');
    const pausedPly = await board.getAttribute('data-ply');
    // Wait for the event loop over the configured next-move interval, avoiding
    // a fixed sleep and verifying no stale playback timer can advance the board.
    await page.waitForFunction(async () => {
      const start = performance.now();
      while (performance.now() - start < Number(document.querySelector('#speed').value) + 50)
        await new Promise(requestAnimationFrame);
      return true;
    });
    assert.equal(await board.getAttribute('data-ply'), pausedPly);

    const screenshotDir = path.join(__dirname, '../engine-output/wally-v02-black-evaluation');
    await fs.mkdir(screenshotDir, {recursive:true});
    await seek(92);
    await page.screenshot({path:path.join(screenshotDir, 'replay-desktop.png'), fullPage:true, animations:'disabled'});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await seek(96);
    await page.locator('#engine-score summary').click();
    assert.match(await page.locator('#engine-score-note').innerText(), /recorded game ended here/);
    await page.screenshot({path:path.join(screenshotDir, 'replay-mobile.png'), fullPage:true, animations:'disabled'});
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    console.log('Black replay browser checks passed: orientation, identities, score perspective/parity, missing searches, mate distances, castling/captures, controls, PGN download, mobile, and offline operation.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
