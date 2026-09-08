// Offline regression checks for font-independent replay pieces on small screens.
// Optional arguments: Playwright module path, browser channel (or "webkit").
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const playwright = require(process.argv[2] || 'playwright');

(async () => {
  const browserName = process.argv[3];
  const browser = browserName === 'webkit'
    ? await playwright.webkit.launch({headless:true})
    : await playwright.chromium.launch({headless:true, channel:browserName || undefined});
  try {
    const page = await browser.newPage({
      viewport:{width:390,height:844}, deviceScaleFactor:2, isMobile:true, hasTouch:true,
    });
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    await page.route(/^https?:/, route => route.abort());
    const replayDirectory = path.join(__dirname, '../replays');
    const replayFiles = (await fs.readdir(replayDirectory))
      .filter(file => file.endsWith('.html') && file !== 'index.html').sort();
    assert.ok(replayFiles.length >= 8, 'Cover all existing standalone game replays');
    const openReplay = file => page.goto(pathToFileURL(path.join(replayDirectory, file)).href);
    const snapshots = () => page.locator('#pieces .piece[data-present="true"]').evaluateAll(elements =>
      elements.map(element => {
        const svg = element.querySelector('svg'), use = svg?.querySelector('use');
        const bounds = use?.getBBox();
        return {
          id:element.dataset.piece, type:element.dataset.type, square:element.dataset.square,
          color:element.classList.contains('white') ? 'white' : 'black',
          svg:svg?.namespaceURI, reference:use?.getAttribute('href'),
          fill:use && getComputedStyle(use).fill, stroke:use && getComputedStyle(use).stroke,
          width:bounds?.width, height:bounds?.height,
          text:element.textContent.trim(),
        };
      }).sort((a,b) => a.id.localeCompare(b.id)));
    const brightness = color => {
      const channels = color.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/);
      assert.ok(channels, `Expected an opaque RGB piece color, got ${color}`);
      return Number(channels[1]) * .2126 + Number(channels[2]) * .7152 + Number(channels[3]) * .0722;
    };

    for (const file of replayFiles) {
      await openReplay(file);
      assert.equal(await page.locator('#board').getAttribute('data-ply'), '0', file);
      const pieces = await snapshots();
      assert.equal(pieces.length, 32, file);
      for (const piece of pieces) {
        assert.equal(piece.svg, 'http://www.w3.org/2000/svg', `${file}: ${piece.id} is a vector`);
        assert.equal(piece.reference, '#piece-' + piece.type, `${file}: ${piece.id} shape`);
        assert.ok(piece.width > 0 && piece.height > 0, `${file}: ${piece.id} has rendered geometry`);
        assert.equal(piece.text, '', `${file}: ${piece.id} does not depend on a font/emoji glyph`);
        assert.notEqual(piece.fill, 'none', `${file}: ${piece.id} fill`);
        assert.notEqual(piece.stroke, 'none', `${file}: ${piece.id} outline`);
      }
      const whitePawns = pieces.filter(piece => piece.color === 'white' && piece.type === 'p');
      const blackPawns = pieces.filter(piece => piece.color === 'black' && piece.type === 'p');
      assert.equal(whitePawns.length, 8, file);
      assert.equal(blackPawns.length, 8, file);
      const whiteFill = whitePawns[0].fill, blackFill = blackPawns[0].fill;
      assert.ok(whitePawns.every(piece => piece.fill === whiteFill), `${file}: consistent White pawns`);
      assert.ok(blackPawns.every(piece => piece.fill === blackFill), `${file}: consistent Black pawns`);
      assert.ok(brightness(whiteFill) - brightness(blackFill) > 100, `${file}: distinctly light and dark pawns`);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${file}: mobile overflow`);
      await page.locator('#flip').click();
      assert.deepEqual(await snapshots(), pieces, `${file}: flipping preserves identities, colors, and shapes`);
    }

    // A pawn's DOM identity survives promotion and reverse navigation, but its
    // displayed silhouette must follow the selected historical position.
    await openReplay('wally-engine-v02-replay.html');
    await page.locator('#timeline').fill('52');
    const promotedPawn = page.locator('#pieces [data-piece="P-b2"]');
    assert.equal(await promotedPawn.getAttribute('data-square'), 'b7');
    assert.equal(await promotedPawn.locator('use').getAttribute('href'), '#piece-p');
    const pawnFill = await promotedPawn.locator('use').evaluate(element => getComputedStyle(element).fill);
    await page.locator('#next').click();
    assert.equal(await promotedPawn.getAttribute('data-square'), 'b8');
    assert.equal(await promotedPawn.getAttribute('data-type'), 'q');
    assert.equal(await promotedPawn.locator('use').getAttribute('href'), '#piece-q');
    assert.equal(await promotedPawn.locator('use').evaluate(element => getComputedStyle(element).fill), pawnFill);
    await page.locator('#previous').click();
    assert.equal(await promotedPawn.getAttribute('data-type'), 'p');
    assert.equal(await promotedPawn.locator('use').getAttribute('href'), '#piece-p');
    await page.locator('#next').click();
    assert.equal(await promotedPawn.locator('use').getAttribute('href'), '#piece-q');

    await openReplay('replay.html');
    const screenshotPath = path.join(__dirname, '../images/replays/pieces-mobile.png');
    await fs.mkdir(path.dirname(screenshotPath), {recursive:true});
    await page.locator('#board').screenshot({path:screenshotPath, animations:'disabled'});
    assert.deepEqual(errors, []);
    assert.deepEqual(requests, []);
    console.log(`Replay piece checks passed for ${replayFiles.length} pages: mobile vector rendering, distinct pawn colors, flip, promotion/reverse navigation, and offline operation.`);
    console.log(`Mobile board screenshot: ${screenshotPath}`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
