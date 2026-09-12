// Fully intercepted operator UI QA: no site, account, game, mail or model access.
const {launchBrowser,outputDir}=require('./support.cjs');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const origin='http://monitor-preview.local';
const protectedUser={id:'operator-fixture',name:'Operator preview',protected:true};
const noReplay={saved:false,building:false,shared:false,listed:false};
function game(overrides={}){return {game_id:'game-one',name:'Player preview',human_side:'white',status:'active',result:null,human_outcome:null,termination:null,ply:18,last_move:'9… Ne4',created_at:'2026-09-12T19:00:00+00:00',updated_at:'2026-09-12T20:00:00+00:00',last_human_activity:'2026-09-12T19:58:00+00:00',worker_state:'idle',active_response:false,waiting_for:'human',replays:{moves:{...noReplay},chat:{...noReplay}},...overrides};}
function inventory(){return {schema_version:1,as_of:'2026-09-12T20:10:00+00:00',timezone:'UTC',summary:{total_games:3,player_games:3,qa_games:0,finished_player_games:1,unfinished_player_games:2,excluded_games:2},activity:{active_responses:1,building_replays:0,reserved_tokens:0,idle_snapshot:false},today_budget:{day:'2026-09-12',tokens:1234567,turns:67,reserved:0},max_daily_tokens:100000000,games:[game(),game({game_id:'game-two',name:'Completed preview',human_side:'black',status:'finished',human_outcome:'loss',termination:'checkmate',last_move:'17. Bxd7#',updated_at:'2026-09-12T20:05:00+00:00',replays:{moves:{...noReplay,saved:true,shared:true},chat:{...noReplay,saved:true,shared:true,listed:true}}}),game({game_id:'game-three',name:'<img src=x onerror=alert(1)> & "Player"',active_response:true,worker_state:'calculating',waiting_for:'astra',updated_at:'2026-09-12T20:09:00+00:00'})]};}
const contexts=[],errors=[];
async function fixture(browser,options={}){
  const data={snapshot:inventory(),user:{...protectedUser},operator:true,status:200,requests:0,calls:[],hold:null,...options};
  const context=await browser.newContext({viewport:options.mobile?{width:390,height:844}:{width:1280,height:1000}});contexts.push(context);
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url());
    assert.equal(url.origin,origin,'No external requests are permitted');
    if(url.pathname.startsWith('/api/')){
      data.calls.push({path:url.pathname,method:request.method()});
      if(url.pathname==='/api/operator/games'){
        assert.equal(request.method(),'GET');
        data.requests++;
        if(data.hold){const held=data.hold;data.hold=null;return held(route);}
        return route.fulfill({status:data.status,json:data.status===200?data.snapshot:{detail:'Fixture access/error'}});
      }
      if(url.pathname==='/api/auth/me')return route.fulfill({json:{user:data.user,operator:data.operator,email_reset_available:false,csrf_token:data.user?'fixture-csrf':null}});
      if(url.pathname==='/api/config')return route.fulfill({json:{player_available:true,player_mode:'test',model:'display-fixture'}});
      if(url.pathname==='/api/auth/login'){data.user={...protectedUser};data.operator=data.loginOperator!==false;return route.fulfill({json:{user:data.user,csrf_token:'fixture-csrf'}});}
      if(url.pathname==='/api/auth/memory')return route.fulfill({json:{enabled:false,text:''}});
      if(url.pathname==='/api/games')return route.fulfill({json:{games:[]}});
      throw Error('Unexpected fixture API: '+url.pathname);
    }
    const relative=url.pathname==='/'?'index.html':url.pathname==='/monitor/'?'monitor.html':url.pathname.replace(/^\/static\//,'');
    if(!['index.html','app.js','style.css','pieces.js','monitor.html','monitor.js','monitor.css'].includes(relative))return route.fulfill({status:404,body:''});
    return route.fulfill({path:path.resolve(__dirname,'../../static',relative),contentType:relative.endsWith('.js')?'text/javascript':relative.endsWith('.css')?'text/css':'text/html'});
  });
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));data.page=page;data.context=context;
  await page.clock.install();
  await page.goto(origin+(options.start||'/monitor/'));
  if(!options.start)await page.waitForFunction(()=>!document.getElementById('monitor-refresh').disabled);
  else await page.waitForFunction(()=>document.getElementById('connection-status').classList.contains('online'));
  return data;
}
async function refresh(data){await data.page.locator('#monitor-refresh').click();await data.page.waitForFunction(()=>!document.getElementById('monitor-refresh').disabled);}
async function visible(data,hidden){await data.page.evaluate(value=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>value});document.dispatchEvent(new Event('visibilitychange'));},hidden);}

(async()=>{
  const browser=await launchBrowser();
  try{
    await fs.mkdir(outputDir,{recursive:true});
    const owner=await fixture(browser);
    assert.equal(await owner.page.locator('#monitor-rows tr').count(),3);
    assert.match(await owner.page.locator('#monitor-rows tr').first().innerText(),/<img src=x onerror=alert\(1\)>/);
    assert.equal(await owner.page.locator('#monitor-rows img').count(),0,'Player names are text, never markup');
    assert.match(await owner.page.locator('#monitor-rows').innerText(),/Astra won; checkmate/);
    assert.match(await owner.page.locator('#monitor-rows').innerText(),/Listed · with chat/);
    assert.match(await owner.page.locator('#monitor-rows').innerText(),/Unlisted link · moves only/);
    assert.match(await owner.page.locator('#monitor-rows').innerText(),/Awaiting human move/);
    assert.match(await owner.page.locator('#monitor-rows').innerText(),/Astra calculating/);
    assert.match(await owner.page.locator('#monitor-excluded').innerText(),/2 known test games/);
    await owner.page.locator('#monitor-search').fill('completed');assert.equal(await owner.page.locator('#monitor-rows tr').count(),1);
    await owner.page.locator('#monitor-filter').selectOption('unfinished');assert.equal(await owner.page.locator('#monitor-rows tr').count(),0);assert.equal(await owner.page.locator('#monitor-empty').isVisible(),true);
    await owner.page.locator('#monitor-search').fill('');assert.equal(await owner.page.locator('#monitor-rows tr').count(),2);
    await owner.page.locator('#monitor-filter').selectOption('all');
    await owner.page.screenshot({path:path.join(outputDir,'monitor-desktop.png'),fullPage:true});
    owner.snapshot.games[1].active_response=true;owner.snapshot.games[1].worker_state='compacting';await refresh(owner);
    assert.match(await owner.page.locator('#monitor-rows').innerText(),/Astra won; checkmate · Astra compacting \(post-game chat\)/,'Finished outcomes retain current post-game worker activity');
    owner.snapshot.games[1].active_response=false;owner.snapshot.games[1].worker_state='idle';

    owner.status=503;await refresh(owner);
    assert.equal(await owner.page.locator('#monitor-rows tr').count(),3,'Failed refresh preserves last snapshot');
    assert.match(await owner.page.locator('#monitor-status').innerText(),/Stale snapshot/);
    owner.status=200;await refresh(owner);assert.doesNotMatch(await owner.page.locator('#monitor-status').innerText(),/Stale/);
    const before=owner.requests;await owner.page.clock.runFor(30001);await owner.page.waitForFunction(()=>!document.getElementById('monitor-refresh').disabled);
    assert.equal(owner.requests,before+1,'Visible monitor polls once each interval');
    await visible(owner,true);const hiddenRequests=owner.requests;await owner.page.clock.runFor(65000);assert.equal(owner.requests,hiddenRequests,'Hidden monitor does not poll');
    await visible(owner,false);await owner.page.waitForFunction(()=>!document.getElementById('monitor-refresh').disabled);assert.equal(owner.requests,hiddenRequests+1,'Visibility triggers immediate refresh');

    let release;owner.hold=route=>new Promise(resolve=>{release=async()=>{await route.fulfill({json:owner.snapshot});resolve();};});
    await owner.page.locator('#monitor-refresh').click();await owner.page.waitForFunction(()=>document.getElementById('monitor-refresh').disabled);
    assert.ok(release);const heldRequests=owner.requests;
    await owner.page.evaluate(()=>{document.getElementById('monitor-refresh').click();window.dispatchEvent(new Event('online'));document.dispatchEvent(new Event('visibilitychange'));});
    assert.equal(owner.requests,heldRequests,'Manual/visibility/online events cannot overlap an active request');
    await release();await owner.page.waitForFunction(()=>!document.getElementById('monitor-refresh').disabled);

    let releaseTimedOut;owner.hold=route=>new Promise(resolve=>{releaseTimedOut=async()=>{await route.fulfill({json:owner.snapshot}).catch(()=>{});resolve();};});
    await owner.page.locator('#monitor-refresh').click();await owner.page.waitForFunction(()=>document.getElementById('monitor-refresh').disabled);
    await owner.page.clock.runFor(10001);await owner.page.waitForFunction(()=>!document.getElementById('monitor-refresh').disabled);
    assert.match(await owner.page.locator('#monitor-status').innerText(),/Stale snapshot/,'Requests have a deadline');await releaseTimedOut();

    owner.status=401;await refresh(owner);
    assert.equal(await owner.page.locator('#monitor-data').isVisible(),false);assert.equal(await owner.page.locator('#monitor-rows').innerText(),'');
    assert.doesNotMatch(await owner.page.locator('body').innerText(),/Completed preview|1,234,567/,'Expired/logout session clears all private fields');
    assert.equal(await owner.page.locator('#monitor-sign-in').getAttribute('href'),'/?monitor=1');
    owner.status=200;await refresh(owner);
    await owner.page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide')));
    assert.equal(await owner.page.locator('#monitor-rows').innerText(),'','Leaving page scrubs cached private DOM');
    await owner.page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
    await owner.page.waitForFunction(()=>document.getElementById('monitor-rows').children.length===3);
    let releaseHidden;owner.hold=route=>new Promise(resolve=>{releaseHidden=async()=>{await route.fulfill({json:owner.snapshot}).catch(()=>{});resolve();};});
    await owner.page.locator('#monitor-refresh').click();await owner.page.waitForFunction(()=>document.getElementById('monitor-refresh').disabled);
    await visible(owner,true);assert.equal(await owner.page.locator('#monitor-rows').innerText(),'','Hidden tabs clear private data immediately');
    owner.status=401;await releaseHidden();assert.equal(await owner.page.locator('#monitor-rows').innerText(),'','An older response cannot repopulate a hidden tab');
    await visible(owner,false);await owner.page.waitForFunction(()=>!document.getElementById('monitor-refresh').disabled);
    assert.match(await owner.page.locator('#monitor-access-title').innerText(),/Sign in/);assert.equal(await owner.page.locator('#monitor-rows').innerText(),'','Visibility restores through fresh authorization');

    const denied=await fixture(browser,{status:403});assert.match(await denied.page.locator('#monitor-access-title').innerText(),/cannot view/);assert.equal(await denied.page.locator('#monitor-data').isVisible(),false);
    const anonymous=await fixture(browser,{status:401});assert.match(await anonymous.page.locator('#monitor-access-title').innerText(),/Sign in/);
    const mobile=await fixture(browser,{mobile:true});
    assert.equal(await mobile.page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'Mobile page does not overflow');
    assert.equal(await mobile.page.locator('.monitor-table-wrap').evaluate(el=>el.scrollWidth>el.clientWidth),true,'Mobile table scrolls inside its own region');
    await mobile.page.screenshot({path:path.join(outputDir,'monitor-mobile.png'),fullPage:true});

    const login=await fixture(browser,{start:'/?monitor=1&next=https://outside.invalid/',user:null,operator:false});
    assert.equal(await login.page.locator('#identity-title').innerText(),'Welcome back.');
    assert.equal(await login.page.locator('#monitor-link').isVisible(),false);
    await login.page.locator('#identity-name').fill('Operator preview');await login.page.locator('#identity-password').fill('fixture-password');await login.page.locator('#identity-submit').click();
    await login.page.waitForURL(origin+'/monitor/');await login.page.waitForFunction(()=>document.getElementById('monitor-rows').children.length===3);
    const ordinary=await fixture(browser,{start:'/',operator:false});assert.equal(await ordinary.page.locator('#monitor-link').isVisible(),false);
    const mainOwner=await fixture(browser,{start:'/'});assert.equal(await mainOwner.page.locator('#monitor-link').getAttribute('href'),'/monitor/');assert.equal(await mainOwner.page.locator('#monitor-link').isVisible(),true);
    const wrongLogin=await fixture(browser,{start:'/?monitor=1',user:null,operator:false,loginOperator:false});
    await wrongLogin.page.locator('#identity-name').fill('Ordinary preview');await wrongLogin.page.locator('#identity-password').fill('fixture-password');await wrongLogin.page.locator('#identity-submit').click();
    await wrongLogin.page.waitForFunction(()=>document.getElementById('toast').textContent.includes('does not have monitor access'));
    assert.equal(new URL(wrongLogin.page.url()).pathname,'/');assert.equal(await wrongLogin.page.locator('#monitor-link').isVisible(),false);
    assert.deepEqual(errors,[]);console.log('Monitor browser QA passed: private access, escaped names, filters/statuses/replays, stale recovery, bounded visible polling, no overlap, logout/pagehide clearing, desktop/mobile and safe sign-in return.');
  }finally{for(const context of contexts)await context.close();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
