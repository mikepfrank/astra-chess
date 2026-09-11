// Public deployment checks only. No credentials, registration, moves, messages,
// generation or sharing requests. Requires an explicit operator-chosen origin.
const {launchBrowser,publicOrigin}=require('./support.cjs');
const assert=require('node:assert/strict');
const base=publicOrigin();
function sameOrigin(value){
  const url=new URL(value,base);
  assert.equal(url.origin,base,'Public check must stay on the selected origin');
  return url.href;
}
(async()=>{
  const browser=await launchBrowser();
  try{
    const context=await browser.newContext({viewport:{width:1280,height:1000}});
    const errors=[],blocked=[];
    await context.route('**/*',async route=>{
      const request=route.request();
      if(request.method()!=='GET'){
        blocked.push(request.method()+' '+new URL(request.url()).pathname);
        return route.abort();
      }
      try{sameOrigin(request.url());}catch{blocked.push('Other origin');return route.abort();}
      return route.continue();
    });
    const page=await context.newPage();
    page.on('pageerror',error=>errors.push(error.message));
    page.on('console',message=>{
      if(message.type()==='error'&&!message.location().url.endsWith('/favicon.ico'))errors.push(message.text());
    });
    await page.goto(base+'/');
    assert.equal(await page.locator('#save-replay').textContent(),'Save/share replay');
    assert.equal(await page.locator('#share-game, #share-dialog').count(),0);
    assert.equal(await page.locator('#archive-variant-moves').getAttribute('aria-selected'),'true');
    assert.equal(await page.locator('#archive-variant-chat').getAttribute('aria-selected'),'false');
    assert.equal(await page.locator('#archive-commentary').count(),0);
    assert.equal(await page.locator('#delete-archive').textContent(),'Delete this version');
    assert.equal(await page.locator('#archive-listed').isChecked(),false);
    assert.equal(await page.locator('#share-archive').textContent(),'Share');
    const configResponse=await context.request.get(base+'/api/config');assert.equal(configResponse.status(),200);
    assert.equal((await configResponse.json()).player_available,true,'Availability is configuration presence, not proof of a successful model turn');
    await page.goto(base+'/games/');
    assert.equal(await page.getByRole('heading',{name:'Public game replays'}).count(),1);
    await page.getByRole('link',{name:'Explore Astra’s earlier chess experiments →'}).click();
    const links=await page.locator('a.game').evaluateAll(elements=>elements.map(element=>element.href));
    assert.ok(links.length>=10,'The existing ten historical replays must remain linked');
    for(const link of links){
      const response=await context.request.get(sameOrigin(link));assert.equal(response.status(),200);
      assert.ok(response.headers()['content-security-policy']?.includes("script-src 'sha256-"));
    }
    await page.goto(base+'/experiments/astra-vs-dr-thanos-2026-09-09.html');
    await page.locator('#last').click();
    const counts=(await page.locator('#chat-count').textContent()).match(/(\d+)\s*\/\s*(\d+)/);
    assert.ok(counts&&Number(counts[2])>0);assert.equal(counts[1],counts[2]);
    await page.locator('#first').click();
    assert.match(await page.locator('#chat-count').textContent(),new RegExp('0\\s*/\\s*'+counts[2]));
    await page.goto(base+'/experiments/li-replay.html');await page.locator('#last').click();
    assert.match(await page.locator('#selected-detail').textContent(),/draw|material/i);
    assert.deepEqual(blocked,[]);assert.deepEqual(errors,[]);
    console.log(JSON.stringify({publicGetOnly:true,unifiedReplayUi:true,playerConfigured:true,historicalPagesChecked:links.length,historicalChatNavigation:true,liDraw:true,mutationsAttempted:0,pageErrors:0}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
