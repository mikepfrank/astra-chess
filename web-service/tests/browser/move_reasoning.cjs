// Fully intercepted board UI: synthetic records only, no model or live API.
const {launchBrowser,outputDir}=require('./support.cjs');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const app=path.resolve(__dirname,'../..'),origin='https://thinking-preview.local';
const python=process.env.ASTRA_TEST_PYTHON||path.join(app,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const fixture=JSON.parse(execFileSync(python,['-c',[
  'import json',
  'from astra_web.config import Config',
  'from astra_web.chess_game import new_game, snapshot',
  "config=Config(model_profile='openrouter-glm',persona='arcturus')",
  "game=new_game({'id':'thinking-user','name':'Thinking preview'},'white',config)",
  "game['id']='thinking-game'",
  'print(json.dumps(snapshot(game)))',
].join('\n')],{cwd:app,encoding:'utf8'}));
(async()=>{
  const browser=await launchBrowser();
  try{
    await fs.mkdir(outputDir,{recursive:true});
    const context=await browser.newContext({viewport:{width:1280,height:1000}});
    let game=structuredClone(fixture),fail=false,release=null,hold=false;
    const actions=[],errors=[];
    await context.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      assert.equal(url.origin,origin,'Unexpected external request');
      if(request.method()==='POST'){
        assert.equal(url.pathname,'/api/games/thinking-game/actions');
        const body=request.postDataJSON();actions.push(body);
        assert.equal(body.action,'set_move_reasoning');
        assert.ok(['high','max'].includes(body.reasoning));
        assert.equal(body.version,game.version);assert.ok(body.request_id);
        if(hold)await new Promise(resolve=>{release=resolve;});
        if(fail){game.version++;return route.fulfill({status:409,json:{detail:'Version conflict'}});}
        game={...game,version:game.version+1,move_reasoning:body.reasoning};
        return route.fulfill({json:game});
      }
      assert.equal(request.method(),'GET');
      if(url.pathname==='/api/auth/me')return route.fulfill({json:{user:{id:'thinking-user',name:'Thinking preview'},csrf_token:'synthetic-only'}});
      if(url.pathname==='/api/config')return route.fulfill({json:{player_available:true,player_mode:'test',player_name:'Arcturus',model:fixture.model,reasoning:'max'}});
      if(url.pathname==='/api/games/thinking-game')return route.fulfill({json:game});
      const relative=url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,'');
      if(!['index.html','app.js','style.css','pieces.js'].includes(relative))return route.fulfill({status:404,body:''});
      return route.fulfill({path:path.join(app,'static',relative),contentType:relative.endsWith('.js')?'text/javascript':relative.endsWith('.css')?'text/css':'text/html'});
    });
    const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>{errors.push(e.message);console.error('Browser error:',e.message);});
    const card=page.locator('#move-thinking'),high=page.locator('#move-thinking-high'),max=page.locator('#move-thinking-max');
    async function loaded(){await page.goto(origin+'/?game=thinking-game');await card.waitFor({state:'visible'});}
    await loaded();assert.equal(await max.isChecked(),true);
    await high.click();
    try{await page.waitForFunction(()=>document.getElementById('move-thinking-high').checked&&!document.getElementById('move-thinking-high').disabled);}
    catch(error){console.error({actions,selected:game.move_reasoning,toast:await page.locator('#toast').textContent()});throw error;}
    assert.equal(actions.length,1);assert.equal(game.move_reasoning,'high');
    await page.reload();await card.waitFor({state:'visible'});assert.equal(await high.isChecked(),true);
    assert.match(await page.locator('#model-detail').textContent(),/high for moves.*high for chat/);
    const board=game.fen,clock=structuredClone(game.clock),messages=structuredClone(game.messages);
    game={...game,worker:{state:'thinking',message:'Thinking'},version:game.version+1};
    await page.reload();await card.waitFor({state:'visible'});
    hold=true;await max.click();await page.waitForFunction(()=>document.getElementById('move-thinking-max').disabled);
    assert.equal(await high.isDisabled(),true);assert.ok(release);release();hold=false;
    await page.waitForFunction(()=>document.getElementById('move-thinking-max').checked&&!document.getElementById('move-thinking-max').disabled);
    assert.equal(game.fen,board);assert.deepEqual(game.clock,clock);assert.deepEqual(game.messages,messages);
    fail=true;await high.click();await page.waitForFunction(()=>document.getElementById('toast').textContent.includes('game changed'));
    await page.waitForFunction(()=>document.getElementById('move-thinking-max').checked&&!document.getElementById('move-thinking-max').disabled);
    fail=false;assert.equal(game.move_reasoning,'max');
    await high.focus();await page.keyboard.press('Space');
    await page.waitForFunction(()=>document.getElementById('move-thinking-high').checked&&!document.getElementById('move-thinking-high').disabled);
    await card.screenshot({path:path.join(outputDir,'move-thinking-desktop.png')});
    await page.setViewportSize({width:390,height:844});await card.scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await card.screenshot({path:path.join(outputDir,'move-thinking-mobile.png')});
    game={...game,status:'suspended',worker:{state:'idle'},version:game.version+1};
    await page.reload();await card.waitFor({state:'visible'});assert.equal(await high.isEnabled(),true);
    game={...game,status:'finished',result:'0-1',termination:'resignation',version:game.version+1};
    await page.reload();await page.locator('#save-replay').waitFor({state:'visible'});assert.equal(await card.isHidden(),true);
    game={...game,status:'active',result:'*',move_reasoning_options:[],version:game.version+1};
    await page.reload();await page.locator('#welcome-overlay').waitFor({state:'hidden'});assert.equal(await card.isHidden(),true);
    assert.deepEqual(errors,[]);
    console.log('Move reasoning UI passed: default, persistence, active-turn selection, pending guard, conflict recovery, keyboard, desktop/mobile, suspended/finished/unsupported games; no live calls.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
