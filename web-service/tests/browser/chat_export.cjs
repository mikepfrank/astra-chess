// Synthetic, fully intercepted RTF exports. No live game, account or model calls.
const {launchBrowser,outputDir}=require('./support.cjs');
const {execFileSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const app=path.resolve(__dirname,'../..'),origin='https://chat-export-preview.local';
const python=process.env.ASTRA_TEST_PYTHON||path.join(app,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const fixture=JSON.parse(execFileSync(python,['-c',[
  'import json','from astra_web.config import Config','from astra_web.chess_game import new_game, snapshot',
  "config=Config(model_profile='openrouter-glm',persona='arcturus')",
  "game=new_game({'id':'export-user','name':'Export preview'},'white',config)",
  'print(json.dumps(snapshot(game)))',
].join('\n')],{cwd:app,encoding:'utf8'}));
const rtf='{\\rtf1\\ansi\\uc1 Synthetic chess transcript\\par 1. e4\\par Arcturus: Hello, curator.}';
const rtfNotes='{\\rtf1\\ansi\\uc1 Synthetic chess transcript\\par AI internal note: saved assistant analysis.}';
(async()=>{
  const browser=await launchBrowser();
  try{
    await fs.mkdir(outputDir,{recursive:true});
    const context=await browser.newContext({viewport:{width:1280,height:1000},acceptDownloads:true});
    let authenticated=true,responseMode='ok',holdGame=null,releaseGame=null,holdExport=false,releaseExport=null;
    const games={first:{...structuredClone(fixture),id:'first'},second:{...structuredClone(fixture),id:'second',status:'finished',result:'1-0',termination:'resignation'},third:{...structuredClone(fixture),id:'third',status:'suspended'}};
    const errors=[],posts=[],exports=[];
    await context.addInitScript(()=>{
      window.__picker={mode:'ok',calls:[],writes:[],closed:0,aborted:0,handles:0};
      window.__savePicker=async options=>{
        const p=window.__picker;p.calls.push(options);
        if(p.mode==='cancel')throw new DOMException('User cancelled','AbortError');
        if(p.mode==='blocked')throw new DOMException('Unavailable in this browser','SecurityError');
        if(p.mode==='hold')await new Promise(resolve=>{p.release=resolve;});
        return {async createWritable(){p.handles++;return {
          async write(blob){if(p.mode==='write-error')throw new Error('Disk is full');p.writes.push(await blob.text());if(p.mode==='hold-write')await new Promise(resolve=>{p.releaseWrite=resolve;});},
          async close(){p.closed++;},async abort(){p.aborted++;},
        };}};
      };
      window.showSaveFilePicker=window.__savePicker;
    });
    await context.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      assert.equal(url.origin,origin,'Unexpected external request');
      if(request.method()==='POST'){
        posts.push(url.pathname);assert.equal(url.pathname,'/api/auth/logout');authenticated=false;return route.fulfill({json:{ok:true}});
      }
      assert.equal(request.method(),'GET');
      if(url.pathname==='/api/auth/me')return route.fulfill({json:{user:authenticated?{id:'export-user',name:'Export preview',protected:true}:null,csrf_token:authenticated?'synthetic-only':null}});
      if(url.pathname==='/api/config')return route.fulfill({json:{player_available:true,player_mode:'codex',player_name:'Arcturus',model:fixture.model,reasoning:'max'}});
      if(url.pathname==='/api/auth/memory')return route.fulfill({json:{enabled:false,text:''}});
      if(url.pathname==='/api/auth/recovery')return route.fulfill({json:{available:false}});
      if(url.pathname==='/api/games')return route.fulfill({json:{games:Object.values(games)}});
      if(url.pathname.endsWith('/chat.rtf')){
        exports.push(url.pathname+url.search);assert.equal(request.headers().accept,'application/rtf');
        const includeNotes=url.searchParams.get('include_notes')==='true';
        if(includeNotes)assert.equal(games[url.pathname.split('/')[3]].status,'finished','Internal notes are for completed games only');
        if(holdExport)await new Promise(resolve=>{releaseExport=resolve;});
        if(responseMode==='expired')return route.fulfill({status:401,json:{detail:'Session expired'}});
        if(responseMode==='failed')return route.fulfill({status:503,json:{detail:'Export temporarily unavailable'}});
        if(responseMode==='html')return route.fulfill({contentType:'text/html',body:'Not a transcript'});
        return route.fulfill({contentType:'application/rtf',headers:{'Content-Disposition':'attachment; filename="synthetic.rtf"','Cache-Control':'no-store'},body:includeNotes?rtfNotes:rtf});
      }
      if(url.pathname.startsWith('/api/games/')){
        if(!authenticated)return route.fulfill({status:401,json:{detail:'Session expired'}});
        const id=url.pathname.slice('/api/games/'.length);assert.ok(games[id]);
        if(id===holdGame)await new Promise(resolve=>{releaseGame=resolve;});
        return route.fulfill({json:games[id]});
      }
      const relative=url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,'');
      if(!['index.html','app.js','style.css','pieces.js'].includes(relative))return route.fulfill({status:404,body:''});
      return route.fulfill({path:path.join(app,'static',relative),contentType:relative.endsWith('.js')?'text/javascript':relative.endsWith('.css')?'text/css':'text/html'});
    });
    const page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
    const button=page.locator('#export-chat'),dialog=page.locator('#chat-export-dialog'),notes=page.locator('#chat-export-notes'),downloadButton=page.locator('#chat-export-download');
    async function ready(){await button.waitFor({state:'visible'});await page.waitForFunction(()=>!document.getElementById('export-chat').disabled);}
    async function openOptions(){await button.focus();await page.keyboard.press('Enter');await dialog.waitFor({state:'visible'});assert.equal(await notes.isChecked(),false,'Internal notes default off every time');}
    async function downloadCurrent(){await downloadButton.focus();await page.keyboard.press('Enter');}
    async function click(includeNotes=false){await openOptions();if(includeNotes)await notes.check();await downloadCurrent();}
    async function mode(value){await page.evaluate(value=>{window.__picker.mode=value;},value);}
    async function stats(){return page.evaluate(()=>({calls:window.__picker.calls.length,writes:window.__picker.writes.length,closed:window.__picker.closed,aborted:window.__picker.aborted,handles:window.__picker.handles}));}
    async function chooseGame(index){await page.locator('#games-button').click();await page.locator('#game-list .saved-game').nth(index).click();}
    await page.goto(origin+'/');await page.locator('#account-button').filter({hasText:'Export preview'}).waitFor();assert.equal(await button.isHidden(),true,'No game means no export');
    await page.goto(origin+'/?game=first');await ready();
    assert.equal(await button.locator('xpath=ancestor::footer').count(),1,'Export belongs at the screen bottom');
    await page.locator('.site-footer').screenshot({path:path.join(outputDir,'chat-export-desktop.png')});
    await openOptions();assert.equal(await notes.isDisabled(),true);assert.equal(await notes.locator('xpath=..').textContent()," Include AI's internal notes?");
    assert.match(await page.locator('#chat-export-notes-help').textContent(),/saved assistant notes, not hidden reasoning/);
    assert.equal(await page.locator('#chat-export-notes-unavailable').isVisible(),true);
    await dialog.screenshot({path:path.join(outputDir,'chat-export-options-active.png')});
    await page.locator('#chat-export-cancel').click();await dialog.waitFor({state:'hidden'});assert.equal((await stats()).calls,0);assert.equal(exports.length,0);
    await openOptions();await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});assert.equal((await stats()).calls,0);
    await page.setViewportSize({width:390,height:844});await button.scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.locator('.site-footer').screenshot({path:path.join(outputDir,'chat-export-mobile.png')});
    await click();await page.waitForFunction(()=>window.__picker.closed===1);await ready();
    assert.equal(exports.length,1);assert.equal(await page.evaluate(()=>window.__picker.writes[0]),rtf);
    const pickerOptions=await page.evaluate(()=>window.__picker.calls[0]);assert.match(pickerOptions.suggestedName,/^chess-chat-\d{4}-\d{2}-\d{2}-first\.rtf$/);assert.deepEqual(pickerOptions.types[0].accept,{'application/rtf':['.rtf']});
    // Cancellation does not fetch anything, create a file, or report an error.
    await mode('cancel');await click();await ready();assert.equal(exports.length,1);assert.equal((await stats()).handles,1);
    // Picker must complete before the private request begins; changing games cancels it.
    await mode('hold');await click();await page.waitForFunction(()=>typeof window.__picker.release==='function');assert.equal(exports.length,1);
    holdGame='second';await chooseGame(1);await button.waitFor({state:'hidden'});assert.ok(releaseGame);
    await page.evaluate(()=>window.__picker.release());assert.equal(exports.length,1);
    holdGame=null;releaseGame();releaseGame=null;await ready();
    await mode('ok');await click();await page.waitForFunction(()=>window.__picker.closed===2);await ready();assert.equal(exports.at(-1),'/api/games/second/chat.rtf');
    await chooseGame(2);await ready();await openOptions();assert.equal(await notes.isDisabled(),true);await downloadCurrent();await page.waitForFunction(()=>window.__picker.closed===3);await ready();assert.equal(exports.at(-1),'/api/games/third/chat.rtf','Suspended games also export');
    // Completed games alone can opt in. Cancel/reopen and each subsequent export reset the option.
    await chooseGame(1);await ready();await openOptions();assert.equal(await notes.isEnabled(),true);assert.equal(await page.locator('#chat-export-notes-unavailable').isHidden(),true);
    await notes.check();await page.locator('#chat-export-cancel').click();await dialog.waitFor({state:'hidden'});await openOptions();
    await page.setViewportSize({width:1280,height:1000});await dialog.screenshot({path:path.join(outputDir,'chat-export-options-desktop.png')});
    await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await dialog.screenshot({path:path.join(outputDir,'chat-export-options-mobile.png')});
    await notes.check();await downloadCurrent();await page.waitForFunction(()=>window.__picker.closed===4);await ready();assert.equal(exports.at(-1),'/api/games/second/chat.rtf?include_notes=true');assert.equal(await page.evaluate(()=>window.__picker.writes.at(-1)),rtfNotes);
    await click();await page.waitForFunction(()=>window.__picker.closed===5);await ready();assert.equal(exports.at(-1),'/api/games/second/chat.rtf');assert.equal(await page.evaluate(()=>window.__picker.writes.at(-1)),rtf);
    // Programmatic saved-game selection also closes and clears an open options dialog.
    await openOptions();await notes.check();await page.evaluate(()=>document.getElementById('games-button').click());await page.locator('#game-list .saved-game').nth(2).click();await ready();await dialog.waitFor({state:'hidden'});assert.equal(await notes.isChecked(),false);
    // An exposed-but-blocked native picker falls back to an ordinary file download.
    await mode('blocked');let downloaded=page.waitForEvent('download');await click();let download=await downloaded;await ready();
    assert.match(download.suggestedFilename(),/^chess-chat-.*-third\.rtf$/);assert.equal(await fs.readFile(await download.path(),'utf8'),rtf);
    await page.evaluate(()=>{window.showSaveFilePicker=undefined;});downloaded=page.waitForEvent('download');await click();download=await downloaded;await ready();assert.equal(await fs.readFile(await download.path(),'utf8'),rtf);
    await page.evaluate(()=>{window.showSaveFilePicker=window.__savePicker;});await mode('ok');
    // Failure responses are displayed, never saved as bogus RTF files.
    let before=await stats();responseMode='failed';await click();await page.locator('#toast').filter({hasText:'Export temporarily unavailable'}).waitFor();await ready();assert.equal((await stats()).handles,before.handles);
    responseMode='html';await click();await page.locator('#toast').filter({hasText:'did not return a rich-text transcript'}).waitFor();await ready();assert.equal((await stats()).handles,before.handles);
    responseMode='ok';await mode('write-error');await click();await page.locator('#toast').filter({hasText:'Disk is full'}).waitFor();await ready();assert.equal((await stats()).aborted,before.aborted+1);assert.equal((await stats()).closed,before.closed);
    // A game change while reading/writing discards the old private export.
    await mode('hold-write');await click();await page.waitForFunction(()=>typeof window.__picker.releaseWrite==='function');before=await stats();
    await chooseGame(0);await ready();await page.evaluate(()=>window.__picker.releaseWrite());await page.waitForFunction(count=>window.__picker.aborted===count,before.aborted+1);assert.equal((await stats()).closed,before.closed);
    // An in-flight authenticated response is also invalid after sign-out.
    await mode('ok');holdExport=true;await click();await page.waitForFunction(()=>document.getElementById('export-chat').disabled);await page.waitForTimeout(50);assert.ok(releaseExport);
    await page.locator('#account-button').click();await page.locator('#logout').click();await page.locator('#identity-dialog').waitFor({state:'visible'});assert.equal(await button.isHidden(),true);
    holdExport=false;releaseExport();releaseExport=null;
    authenticated=true;await page.goto(origin+'/?game=first');await ready();responseMode='expired';await click();await button.waitFor({state:'hidden'});await page.locator('#toast').filter({hasText:'Sign in again to export'}).waitFor();assert.equal((await stats()).handles,0);
    assert.deepEqual(posts,['/api/auth/logout']);assert.deepEqual(errors,[]);
    console.log('Chat export UI passed: compact desktop/mobile options; notes default off, finished-only opt-in, query and reset; keyboard/cancel; picker-before-fetch; unavailable/blocked picker downloads; MIME/server/disk failures; game-switch/dialog/write/auth expiry/logout safeguards. All requests intercepted.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
