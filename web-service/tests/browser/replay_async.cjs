const {launchBrowser,fixtureOrigin,loadFixtureAccess,bounded}=require('./support.cjs');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const base=fixtureOrigin;
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
(async()=>{
  const browser=await launchBrowser();
  try{
    const access=await loadFixtureAccess();
    const context=await browser.newContext({viewport:{width:1280,height:1100}});
    await context.addCookies([{name:'astra_session',value:access.cookie,url:base,sameSite:'Strict',httpOnly:true}]);
    const page=await context.newPage(),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const endpoint=base+'/api/games/'+access.game+'/archive';
    const movesId='a'.repeat(32),chatId='b'.repeat(32);
    const moves={state:'ready',archive_id:movesId,include_commentary:false,download_url:endpoint+'/download?archive_id='+movesId,generated_at:1789060000,shared:false,listed:false,share_url:null,shared_archive_id:null,shared_include_commentary:null,error:null,legacy_share_url:null};
    const chat={state:'ready',archive_id:chatId,include_commentary:true,download_url:endpoint+'/download?archive_id='+chatId,generated_at:1789060001,shared:true,listed:true,share_url:base+'/games/async-fixture-chat/',shared_archive_id:chatId,shared_include_commentary:true,error:null,legacy_share_url:null};
    const envelope=(variant,selected)=>({...selected,selected_variant:variant,variants:{moves,chat:variant==='chat'?selected:chat}});
    const firstGetSeen=deferred(),releaseFirstGet=deferred(),mutationSeen=deferred(),releaseMutation=deferred();
    let delayedMoves=true,buildingAdmitted=false,interceptedMutations=0,interceptedGets=0;
    const refreshError='Synthetic refresh failure: your previous saved version is still available.';
    await page.route(endpoint+'**',async route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.pathname!==new URL(endpoint).pathname)return route.continue();
      const send=body=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
      if(request.method()==='POST'){
        interceptedMutations++;
        assert.deepEqual(request.postDataJSON(),{include_commentary:true});
        mutationSeen.resolve();await releaseMutation.promise;
        buildingAdmitted=true;
        return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify(envelope('chat',{...chat,state:'building',pending_archive_id:'c'.repeat(32)}))});
      }
      assert.equal(request.method(),'GET');interceptedGets++;
      const variant=url.searchParams.get('variant');assert.ok(['moves','chat'].includes(variant));
      if(variant==='moves'&&delayedMoves){
        delayedMoves=false;firstGetSeen.resolve();await releaseFirstGet.promise;
        try{await send(envelope('moves',moves));}catch{}
        return;
      }
      if(variant==='chat'&&buildingAdmitted)return send(envelope('chat',{...chat,error:refreshError}));
      return send(envelope(variant,variant==='chat'?chat:moves));
    });
    await page.goto(base+'/?game='+access.game);
    await page.locator('#save-replay').click();await bounded(firstGetSeen.promise,'First GET');
    assert.equal(await page.locator('#archive-variant-chat').isEnabled(),true);
    await page.locator('#archive-variant-chat').click();
    await page.waitForFunction(()=>!document.getElementById('generate-archive').disabled);
    releaseFirstGet.resolve();await page.waitForTimeout(150);
    assert.equal(await page.locator('#archive-variant-chat').getAttribute('aria-selected'),'true');
    assert.equal(await page.locator('#archive-variant-moves').getAttribute('aria-selected'),'false');
    assert.equal(await page.locator('#archive-listed').isChecked(),true);
    assert.equal(await page.locator('#download-archive').getAttribute('href'),base+chat.download_url.replace(base,''));
    assert.match(await page.locator('#archive-details').textContent(),/Includes the complete conversation/);
    await page.locator('#generate-archive').click();await bounded(mutationSeen.promise,'Mutation interception');
    assert.equal(await page.locator('#archive-variant-moves').isDisabled(),true);
    assert.equal(await page.locator('#archive-variant-chat').isDisabled(),true);
    await page.evaluate(()=>document.getElementById('archive-variant-moves').click());
    assert.equal(await page.locator('#archive-variant-chat').getAttribute('aria-selected'),'true');
    releaseMutation.resolve();
    await page.waitForFunction(()=>document.getElementById('archive-status').textContent.includes('Constructing'));
    assert.equal(await page.locator('#archive-variant-moves').isEnabled(),true);
    assert.equal(await page.locator('#archive-variant-chat').isEnabled(),true);
    assert.equal(await page.locator('#download-archive').isVisible(),true);
    assert.equal(await page.locator('#download-archive').getAttribute('href'),chat.download_url);
    assert.match(await page.locator('#archive-ready-title').textContent(),/saved version is still available/);
    assert.equal(await page.locator('#share-archive').isDisabled(),true);
    await page.locator('#archive-error').waitFor({state:'visible',timeout:10000});
    assert.equal(await page.locator('#archive-error').textContent(),refreshError);
    assert.equal(await page.locator('#download-archive').isVisible(),true);
    assert.equal(await page.locator('#download-archive').getAttribute('href'),chat.download_url);
    assert.equal(await page.locator('#generate-archive').isEnabled(),true);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({syntheticArchiveResponses:true,delayedGetCannotReplaceSelectedVariant:true,listingCheckboxStayedWithChat:true,tabsDisabledDuringMutation:true,priorDownloadVisibleDuringRefresh:true,failedRefreshErrorVisible:true,failedRefreshDownloadPreserved:true,realBackendMutations:0,interceptedMutations,interceptedGets,pageErrors:errors.length}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
