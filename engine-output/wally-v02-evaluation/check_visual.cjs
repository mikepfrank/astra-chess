const assert = require('node:assert/strict');
const {pathToFileURL} = require('node:url');
const path = require('node:path');
const {chromium} = require(process.argv[2]);
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try {
    for(const width of [736,360]) for(const theme of ['light','dark']) {
      const page=await browser.newPage({viewport:{width,height:720},colorScheme:theme});
      const errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      page.on('requestfailed',r=>console.log('REQUEST FAILED',r.url(),r.failure()));
      page.on('console',m=>{if(m.type()==='error')console.log('BROWSER ERROR',m.text())});
      await page.goto(pathToFileURL(path.join(__dirname,'preview.html')).href);
      const frame=page.frameLocator('iframe');
      const root=frame.locator('#wally-evaluation-history');
      await root.locator('[data-point="28"]').waitFor({timeout:12000}).catch(async e=>{console.log('PAGE ERRORS',errors);console.log('FRAMES',page.frames().map(f=>f.url()));throw e});
      assert.equal(await root.locator('[data-point]').count(),28);
      assert.equal(await root.locator('[data-mate]').count(),3);
      const range=root.locator('input[type="range"]');
      await range.fill('23');
      await range.dispatchEvent('input');
      assert.match(await root.locator('output').innerText(),/23\. dxc5.*\+16\.13/);
      await range.fill('30');
      await range.dispatchEvent('input');
      assert.match(await root.locator('output').innerText(),/30\. Qf8.*next move/);
      await range.fill('12');
      await range.dispatchEvent('input');
      const b=await root.locator('[data-point="12"]').boundingBox();
      await page.mouse.move(b.x+b.width/2,b.y+b.height/2);
      assert.match(await root.locator('[role="tooltip"]').innerText(),/Nxc6.*2\.97/);
      await page.mouse.click(b.x+b.width/2,b.y+b.height/2);
      assert.equal(await range.inputValue(),'12');
      await page.mouse.move(0,0);
      await root.locator('[data-chart-hit]').dispatchEvent('pointerleave');
      const geometry=await root.evaluate(r=>({
        overflow:document.documentElement.scrollWidth>innerWidth,
        width:r.clientWidth,
        svgWidth:r.querySelector('svg').viewBox.baseVal.width,
        badPath:[...r.querySelectorAll('path')].some(p=>/NaN|undefined/.test(p.getAttribute('d')||'')),
        pointBoxes:[...r.querySelectorAll('[data-point],[data-mate]')].map(p=>{const b=p.getBoundingClientRect();return {x:b.x,y:b.y,w:b.width,h:b.height}}),
        frame:r.querySelector('svg').getBoundingClientRect().toJSON()
      }));
      assert.equal(geometry.overflow,false);
      assert.equal(geometry.badPath,false);
      assert.ok(Math.abs(geometry.width-geometry.svgWidth)<1);
      assert.ok(geometry.pointBoxes.every(b=>b.w>0&&b.h>0&&b.x>=geometry.frame.x&&b.x+b.w<=geometry.frame.right));
      assert.deepEqual(errors,[]);
      await page.screenshot({path:path.join(__dirname,`${theme}-${width}.png`)});
      console.log(JSON.stringify({width,theme,checks:'marks, mate separation, selection, tooltip, paths, bounds passed'}));
      await page.close();
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
