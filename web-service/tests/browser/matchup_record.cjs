// Fully intercepted head-to-head UI: synthetic records, no live/model requests.
const {launchBrowser,outputDir}=require('./support.cjs');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const app=path.resolve(__dirname,'../..'),origin='https://matchup-preview.local';
const python=process.env.ASTRA_TEST_PYTHON||path.join(app,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const fixture=JSON.parse(execFileSync(python,['-c',[
  'import json',
  'from astra_web.config import Config',
  'from astra_web.chess_game import new_game, snapshot',
  "config=Config(model_profile='openrouter-glm',persona='arcturus')",
  "game=new_game({'id':'matchup-user','name':'Matchup preview'},'white',config)",
  'print(json.dumps(snapshot(game)))',
].join('\n')],{cwd:app,encoding:'utf8'}));
function record(wins,losses,draws,includes=false){return {
  completed_games:wins+losses+draws,human_wins:wins,ai_wins:losses,draws,
  human_points:wins+draws/2,ai_points:losses+draws/2,includes_current_game:includes,
};}
(async()=>{
  const browser=await launchBrowser();
  try{
    await fs.mkdir(outputDir,{recursive:true});
    const context=await browser.newContext({viewport:{width:1280,height:1000}});
    let authenticated=true,expired=false,holdGame=null,release=null;
    const games={
      first:{...structuredClone(fixture),id:'first',matchup_record:record(1,2,1)},
      second:{...structuredClone(fixture),id:'second',human_side:'black',astra_side:'white',player_name:'Other <opponent>',matchup_record:record(0,0,0)},
      legacy:{...structuredClone(fixture),id:'legacy',player_name:'Historical opponent'},
    };
    const errors=[],posts=[];
    await context.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      assert.equal(url.origin,origin,'Unexpected external request');
      if(request.method()==='POST'){
        posts.push(url.pathname);assert.equal(url.pathname,'/api/auth/logout');
        authenticated=false;return route.fulfill({json:{ok:true}});
      }
      assert.equal(request.method(),'GET');
      if(url.pathname==='/api/auth/me')return route.fulfill({json:{user:authenticated?{id:'matchup-user',name:'Matchup preview',protected:true}:null,csrf_token:authenticated?'synthetic-only':null}});
      if(url.pathname==='/api/config')return route.fulfill({json:{player_available:true,player_mode:'codex',player_name:'Arcturus',model:fixture.model,reasoning:'max'}});
      if(url.pathname==='/api/auth/memory')return route.fulfill({json:{enabled:false,text:''}});
      if(url.pathname==='/api/auth/recovery')return route.fulfill({json:{available:false}});
      if(url.pathname==='/api/games')return route.fulfill({json:{games:Object.values(games)}});
      if(url.pathname.startsWith('/api/games/')){
        if(expired)return route.fulfill({status:401,json:{detail:'Session expired'}});
        const id=url.pathname.slice('/api/games/'.length);assert.ok(games[id]);
        if(id===holdGame)await new Promise(resolve=>{release=resolve;});
        return route.fulfill({json:games[id]});
      }
      const relative=url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,'');
      if(!['index.html','app.js','style.css','pieces.js'].includes(relative))return route.fulfill({status:404,body:''});
      return route.fulfill({path:path.join(app,'static',relative),contentType:relative.endsWith('.js')?'text/javascript':relative.endsWith('.css')?'text/css':'text/html'});
    });
    const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
    const panel=page.locator('#matchup-record'),score=page.locator('#matchup-score'),details=page.locator('#matchup-details');
    async function refresh(){await page.evaluate(()=>window.dispatchEvent(new Event('online')));}
    async function hasScore(text){await page.waitForFunction(expected=>document.getElementById('matchup-score').textContent===expected,text);assert.equal(await panel.isVisible(),true);}
    async function chooseGame(index){
      await page.locator('#games-button').focus();await page.keyboard.press('Enter');
      await page.locator('#game-list .saved-game').nth(index).focus();await page.keyboard.press('Enter');
    }
    await page.goto(origin+'/?game=first');
    await hasScore('Head-to-head points: You 1½ – Arcturus 2½ · 4 games');
    assert.match(await details.textContent(),/1 win, 1 draw, 2 losses/);
    assert.match(await panel.getAttribute('title'),/Completed games only/);
    const initial=await score.textContent();
    await page.locator('#flip-board').focus();await page.keyboard.press('Enter');
    assert.equal(await score.textContent(),initial,'Board orientation must not swap the record');
    await page.locator('.intro').screenshot({path:path.join(outputDir,'matchup-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.locator('.intro').screenshot({path:path.join(outputDir,'matchup-mobile.png')});
    // The ordinary game poll picks up a newly completed game without another API.
    games.first={...games.first,status:'finished',result:'1-0',termination:'resignation',version:games.first.version+1,matchup_record:record(2,2,1,true)};
    await refresh();await hasScore('Head-to-head points: You 2½ – Arcturus 2½ · 5 games');
    assert.match(await panel.getAttribute('title'),/Includes this completed game/);
    // Hide the former opponent's record while a saved-game request is pending.
    holdGame='second';await chooseGame(1);
    await panel.waitFor({state:'hidden'});assert.equal(await score.textContent(),'');
    assert.ok(release);holdGame=null;release();release=null;
    await hasScore('Head-to-head points: You 0 – Other <opponent> 0 · 0 games');
    assert.equal(await panel.locator('opponent').count(),0,'Opponent names must remain text');
    await chooseGame(2);await page.locator('#play-title').filter({hasText:'Historical opponent'}).waitFor();
    assert.equal(await panel.isHidden(),true);assert.equal(await score.textContent(),'');assert.equal(await details.textContent(),'');
    await chooseGame(0);await hasScore('Head-to-head points: You 2½ – Arcturus 2½ · 5 games');
    games.first={...games.first,version:games.first.version+1,matchup_record:record(0,0,1,true)};
    await refresh();await hasScore('Head-to-head points: You ½ – Arcturus ½ · 1 game');
    // An incomplete or inconsistent response clears the former value.
    games.first={...games.first,version:games.first.version+1,matchup_record:{completed_games:999}};
    await refresh();await panel.waitFor({state:'hidden'});assert.equal(await score.textContent(),'');
    games.first={...games.first,version:games.first.version+1,matchup_record:record(0,1,0,true)};
    await refresh();await hasScore('Head-to-head points: You 0 – Arcturus 1 · 1 game');
    authenticated=false;expired=true;await refresh();await panel.waitFor({state:'hidden'});
    assert.equal(await score.textContent(),'');assert.equal(await details.textContent(),'');assert.equal(await panel.getAttribute('title'),null);
    // Explicit keyboard sign-out clears the authenticated score as well.
    authenticated=true;expired=false;await page.goto(origin+'/?game=first');
    await hasScore('Head-to-head points: You 0 – Arcturus 1 · 1 game');
    await page.locator('#account-button').focus();await page.keyboard.press('Enter');
    await page.locator('#logout').focus();await page.keyboard.press('Enter');
    await page.locator('#identity-dialog').waitFor({state:'visible'});
    assert.equal(await panel.isHidden(),true);assert.equal(await score.textContent(),'');assert.equal(await details.textContent(),'');
    assert.deepEqual(posts,['/api/auth/logout']);assert.deepEqual(errors,[]);
    console.log('Matchup UI passed: aggregate points/draws, completed update, board orientation, missing/invalid records, opponent switching/escaping, keyboard, desktop/mobile, auth expiry and logout; all requests intercepted.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
