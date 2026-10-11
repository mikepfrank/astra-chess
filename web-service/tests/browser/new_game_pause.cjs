// All requests are intercepted: no live games, accounts or model calls.
const {launchBrowser,outputDir}=require('./support.cjs');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const origin='http://127.0.0.1:9876';
const guide='https://github.com/mikepfrank/astra-chess/blob/codex/hosted-chess/web-service/DEPLOYMENT.md';
const message='New games are temporarily paused because of API costs. You can continue or resume games you have already started. If you have your own OpenAI API key and web hosting, you can deploy your own instance by asking Codex, Astra, or a similar coding agent to follow the deployment guide: '+guide;
const displayedMessage=message.replace('Codex, Astra, or','OpenAI Codex or');
const errors=[],contexts=[];
async function fixture(browser,options={}){
  const data={paused:true,user:{id:'fixture-owner',name:'Fixture owner'},policyStatus:200,calls:[],...options};
  data.game={id:'fixture-game',human_side:'white',astra_side:'black',status:'suspended',version:0,ply:0,moves:[],messages:[],fen:'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',legal_moves:['e2e4'],worker:{state:'idle'},clock:{remaining_seconds:5400}};
  const context=await browser.newContext({viewport:{width:1280,height:1000}});contexts.push(context);
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    assert.equal(url.origin,origin,'No external requests are allowed');
    if(url.pathname.startsWith('/api/')){
      const body=method==='GET'?null:request.postDataJSON();data.calls.push({path:url.pathname,method,body});
      const reply=(json,status=200)=>route.fulfill({json,status});
      if(url.pathname==='/api/config')return reply({player_available:true,player_mode:'live',model:'fixture'});
      if(url.pathname==='/api/new-game-policy')return reply({new_games_available:!data.paused,new_games_message:message,deployment_url:guide},data.policyStatus);
      if(url.pathname==='/api/auth/me')return reply({user:data.user,csrf_token:data.user?'fixture-csrf':null});
      if(url.pathname==='/api/games'){
        if(method==='GET')return reply({games:[data.game]});
        assert.equal(data.paused,true,'This QA never creates a game, even in its fixture');
        return reply({detail:message},503);
      }
      if(url.pathname==='/api/games/fixture-game')return reply(data.game);
      if(url.pathname==='/api/games/fixture-game/actions'){
        assert.ok(['resume','move','message'].includes(body.action));
        data.game={...data.game,status:'active',version:data.game.version+1};
        return reply(data.game);
      }
      throw new Error('Unexpected fixture API: '+method+' '+url.pathname);
    }
    const relative=url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,'');
    if(!['index.html','app.js','style.css','pieces.js'].includes(relative))return route.fulfill({status:404,body:''});
    return route.fulfill({path:path.resolve(__dirname,'../../static',relative),contentType:relative.endsWith('.js')?'text/javascript':relative.endsWith('.css')?'text/css':'text/html'});
  });
  data.page=await context.newPage();data.page.on('pageerror',error=>errors.push(error.message));
  await data.page.goto(origin+'/'+(options.existing?'?game=fixture-game':''));
  await data.page.waitForFunction(()=>document.getElementById('connection-status').classList.contains('online'));
  return data;
}
const creations=data=>data.calls.filter(call=>call.method==='POST'&&call.path==='/api/games');
(async()=>{
  const browser=await launchBrowser();
  try{
    await fs.mkdir(outputDir,{recursive:true});
    const visitor=await fixture(browser,{user:null}),page=visitor.page;
    assert.equal(await page.locator('#identity-dialog').isVisible(),false,'Pause explanation precedes guest registration');
    assert.equal(await page.locator('#new-games-notice').isVisible(),true);
    assert.match(await page.locator('#new-games-notice').textContent(),/API costs/);
    assert.equal(await page.locator('#new-games-notice-text').textContent(),displayedMessage);
    assert.equal(await page.locator('#new-games-notice-text a').getAttribute('href'),guide);
    assert.equal(await page.locator('#new-games-guide').getAttribute('href'),guide);
    await page.locator('#welcome-new').click();
    await page.waitForFunction(()=>!document.getElementById('new-check-availability').disabled);
    assert.equal(await page.locator('#side-options').isVisible(),false);
    assert.equal(await page.locator('#play-white').isDisabled(),true);
    assert.equal(await page.locator('#new-deployment-guide').getAttribute('href'),guide);
    assert.equal(await page.locator('#new-description').textContent(),displayedMessage);
    assert.equal(await page.locator('#new-description a').getAttribute('href'),guide);
    await page.locator('#new-dialog').screenshot({path:path.join(outputDir,'new-game-pause-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.locator('#new-dialog').screenshot({path:path.join(outputDir,'new-game-pause-mobile.png')});
    await page.locator('#new-dialog .dialog-close').click();
    await page.locator('#account-button').click();
    assert.equal(await page.locator('#login-tab').isVisible(),true,'Sign-in stays available');
    assert.equal(await page.locator('#login-tab').getAttribute('class'),'active','Paused visitors are offered sign-in first');
    assert.equal(creations(visitor).length,0);

    const existing=await fixture(browser,{existing:true}),gamePage=existing.page;
    await gamePage.locator('#resume-game').waitFor({state:'visible'});
    await gamePage.locator('#resume-game').click();
    await gamePage.waitForFunction(()=>document.getElementById('resume-game').hidden);
    await gamePage.locator('[data-square="e2"]').click();await gamePage.locator('[data-square="e4"]').click();
    await gamePage.waitForFunction(()=>!document.getElementById('message-input').disabled);
    await gamePage.locator('#message-input').fill('A fixture message');await gamePage.locator('#send-message').click();
    await gamePage.waitForFunction(()=>!document.getElementById('message-input').disabled);
    assert.deepEqual(existing.calls.filter(call=>call.path.endsWith('/actions')).map(call=>call.body.action),['resume','move','message']);
    await gamePage.locator('#new-game').click();await gamePage.locator('#new-saved-games').click();
    await gamePage.locator('.saved-game').waitFor({state:'visible'});
    assert.equal(creations(existing).length,0);

    const stale=await fixture(browser,{paused:false});
    await stale.page.locator('#new-game').click();
    await stale.page.waitForFunction(()=>!document.getElementById('play-white').disabled);
    stale.paused=true;
    await stale.page.locator('#play-white').click();
    await stale.page.locator('#new-error').waitFor({state:'visible'});
    await stale.page.waitForFunction(()=>document.getElementById('new-title').textContent==='New games are paused');
    assert.equal(creations(stale).length,1,'Stale client receives and displays server rejection');
    assert.equal(await stale.page.locator('#new-error').textContent(),displayedMessage);
    assert.equal(await stale.page.locator('#new-error a').getAttribute('href'),guide);
    assert.equal(await stale.page.locator('#side-options').isVisible(),false);

    const legacy=await fixture(browser,{policyStatus:404});
    await legacy.page.locator('#new-game').click();
    await legacy.page.waitForFunction(()=>!document.getElementById('play-white').disabled);
    assert.equal(await legacy.page.locator('#new-games-notice').isVisible(),false,'Older self-hosted server remains compatible');
    assert.equal(creations(legacy).length,0);
    assert.deepEqual(errors,[]);
    console.log('New-game pause QA passed: public notice, sign-in, saved games, resume/move/chat, stale-client rejection, legacy fallback, desktop/mobile; no live requests.');
  }finally{for(const context of contexts)await context.close();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
