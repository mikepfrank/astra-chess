// Fully intercepted UI QA: no server, real email, account or model is accessed.
const {launchBrowser,outputDir}=require('./support.cjs');
const fs=require('node:fs/promises'),path=require('node:path');
const assert=require('node:assert/strict');
const origin='http://recovery-preview.local';
const password='fixture-password-only';
const emptyRecovery=()=>({available:true,email:null,verified:false,pending_email:null,pending_expires_at:null});
const protectedUser={id:'recovery-fixture',name:'Recovery preview',protected:true};
const fixtures=[],errors=[];

async function fixture(browser,options={}){
  const data={user:{...protectedUser},recovery:emptyRecovery(),calls:[],holdGet:null,holdPost:null,...options};
  const context=await browser.newContext({viewport:{width:1280,height:1000}});
  fixtures.push(context);
  await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),method=request.method();
    assert.equal(url.origin,origin,'No external requests are allowed');
    if(url.pathname.startsWith('/api/')){
      const body=method==='GET'?null:request.postDataJSON();
      data.calls.push({path:url.pathname,method,body,headers:request.headers()});
      const reply=(json,status=200)=>route.fulfill({json,status});
      if(url.pathname==='/api/config'){
        const config={player_available:true,player_mode:'test',model:'display-fixture'};
        if(data.holdConfig){const hold=data.holdConfig;data.holdConfig=null;return hold(route,config);}
        return reply(config);
      }
      if(url.pathname==='/api/auth/me')return data.failMe?reply({detail:'Fixture unavailable'},503):reply({user:data.user,csrf_token:data.user?'fixture-csrf':null,email_reset_available:data.recovery.available,recovery:data.user?.protected?data.recovery:undefined});
      if(url.pathname==='/api/auth/memory')return reply({enabled:false,text:'Fixture memory'});
      if(url.pathname==='/api/games')return reply({games:[]});
      if(url.pathname==='/api/auth/recovery'){
        if(method==='GET'){
          if(data.holdGet){const hold=data.holdGet;data.holdGet=null;return hold(route,structuredClone(data.recovery));}
          return reply(data.recovery);
        }
        assert.equal(request.headers()['x-csrf-token'],'fixture-csrf');
        if(data.holdPost){const hold=data.holdPost;data.holdPost=null;return hold(route,body);}
        if(body.password!==password)return reply({detail:'Current password is incorrect.'},403);
        if(body.email===null)data.recovery={...emptyRecovery(),available:data.recovery.available};
        else data.recovery={...data.recovery,pending_email:body.email,pending_expires_at:Date.now()/1000+3600};
        return reply({ok:true,message:body.email?'Check your email and confirm the link to enable recovery.':'Recovery email removed.',recovery:data.recovery});
      }
      if(url.pathname==='/api/auth/verify-email'){
        if(body.token==='expired-fixture-token')return reply({detail:'This confirmation link has expired or was already used.'},400);
        return reply({ok:true,message:'Recovery email confirmed.'});
      }
      if(url.pathname==='/api/auth/reset'){
        if(data.holdAuth){const hold=data.holdAuth;data.holdAuth=null;return hold(route,body,data);}
        if(body.token!=='reset-fixture-token')return reply({detail:'Invalid or expired reset link.'},400);
        if(data.revokeOnReset)data.user=null;
        return reply({ok:true});
      }
      if(url.pathname==='/api/auth/forgot')return reply({ok:true});
      if(url.pathname==='/api/auth/logout'){data.user=null;return reply({ok:true});}
      if(['/api/auth/protect','/api/auth/register','/api/auth/login'].includes(url.pathname)){
        if(data.holdAuth){const hold=data.holdAuth;data.holdAuth=null;return hold(route,body,data);}
        if(data.failAuth)return reply({detail:'Fixture unavailable'},503);
        data.user={...protectedUser};
        if(body.email)data.recovery={...data.recovery,pending_email:body.email,pending_expires_at:Date.now()/1000+3600};
        return reply({user:data.user,csrf_token:'fixture-csrf',email_reset_available:data.recovery.available,recovery:data.recovery});
      }
      throw Error('Unexpected fixture API: '+method+' '+url.pathname);
    }
    const relative=url.pathname==='/'?'index.html':url.pathname.replace(/^\/static\//,'');
    if(!['index.html','app.js','style.css','pieces.js'].includes(relative))return route.fulfill({status:404,body:''});
    return route.fulfill({path:path.resolve(__dirname,'../../static',relative),contentType:relative.endsWith('.js')?'text/javascript':relative.endsWith('.css')?'text/css':'text/html'});
  });
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  data.page=page;data.context=context;
  await page.goto(origin+'/'+(options.fragment||''));
  if(options.waitReady!==false)await page.waitForFunction(()=>document.getElementById('connection-status').classList.contains('online'));
  return data;
}
async function account(data){
  await data.page.locator('#account-button').click();
  await data.page.waitForFunction(()=>!document.getElementById('recovery-refresh').disabled);
}
async function save(data,email,enteredPassword=password,button='recovery-save'){
  if(email!==undefined)await data.page.locator('#recovery-email').fill(email);
  await data.page.locator('#recovery-password').fill(enteredPassword);
  await data.page.locator('#'+button).click();
  await data.page.waitForFunction(()=>!document.getElementById('recovery-refresh').disabled);
}
const calls=(data,path)=>data.calls.filter(call=>call.path==='/api/auth/'+path&&call.method==='POST');

(async()=>{
  const browser=await launchBrowser();
  try{
    await fs.mkdir(outputDir,{recursive:true});
    const owner=await fixture(browser);await account(owner);
    assert.match(await owner.page.locator('#recovery-status').textContent(),/No confirmed recovery email/);
    await owner.page.locator('#recovery-email').fill('new@example.test');
    await owner.page.locator('#recovery-save').click();assert.equal(calls(owner,'recovery').length,0,'Password is required');
    await save(owner,'new@example.test');
    assert.match(await owner.page.locator('#recovery-pending').textContent(),/Awaiting confirmation: new@example.test/);
    assert.equal(await owner.page.locator('#recovery-password').inputValue(),'');
    await owner.page.locator('#recovery-email').fill('unfinished edit');
    await owner.page.locator('#recovery-resend').click();assert.equal(calls(owner,'recovery').length,1,'Resend still requires the password');
    await save(owner,undefined,'wrong-password','recovery-resend');
    assert.match(await owner.page.locator('#recovery-error').textContent(),/Current password is incorrect/);
    await owner.page.locator('#recovery-refresh').click();
    await owner.page.waitForFunction(()=>!document.getElementById('recovery-resend').disabled);
    await save(owner,undefined,password,'recovery-resend');
    assert.equal(calls(owner,'recovery').at(-1).body.email,'new@example.test');
    owner.recovery={available:true,email:'original@example.test',verified:true,pending_email:null,pending_expires_at:null};
    await owner.page.locator('#recovery-refresh').click();
    await owner.page.waitForFunction(()=>document.getElementById('recovery-status').textContent.includes('Recovery enabled'));
    await save(owner,'replacement@example.test');
    assert.match(await owner.page.locator('#recovery-status').textContent(),/original@example.test/);
    assert.match(await owner.page.locator('#recovery-pending').textContent(),/replacement@example.test.*current confirmed address remains active/);
    assert.equal(await owner.page.locator('#messages').textContent().then(text=>text.includes('@example.test')),false);
    await owner.page.locator('#account-dialog').screenshot({path:path.join(outputDir,'recovery-desktop.png')});
    await owner.page.setViewportSize({width:390,height:844});
    assert.equal(await owner.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    assert.equal(await owner.page.locator('#account-dialog').evaluate(el=>el.scrollWidth<=el.clientWidth),true);
    await owner.page.locator('#account-dialog').screenshot({path:path.join(outputDir,'recovery-mobile.png')});
    await save(owner,'unfinished edit',password,'recovery-remove');
    assert.match(await owner.page.locator('#recovery-status').textContent(),/No confirmed recovery email/);
    assert.equal(owner.recovery.pending_email,null);assert.equal(owner.recovery.email,null);

    const legacy=await fixture(browser,{recovery:{...emptyRecovery(),email:'legacy@example.test'}});await account(legacy);
    assert.match(await legacy.page.locator('#recovery-status').textContent(),/Not yet confirmed.*not enabled/);
    assert.equal(await legacy.page.locator('#recovery-resend').isVisible(),true);
    await save(legacy,undefined,password,'recovery-resend');
    assert.equal(legacy.recovery.verified,false);

    const unavailable=await fixture(browser,{recovery:{...emptyRecovery(),available:false,email:'saved@example.test',verified:true}});await account(unavailable);
    assert.equal(await unavailable.page.locator('#recovery-unavailable').isVisible(),true);
    assert.equal(await unavailable.page.locator('#recovery-save').isHidden(),true);
    await save(unavailable,undefined,password,'recovery-remove');
    assert.equal(await unavailable.page.locator('#recovery-form').isHidden(),true);

    const verify=await fixture(browser,{user:null,fragment:'#verify-email=verify-fixture-token'});
    assert.equal(new URL(verify.page.url()).hash,'');assert.equal(calls(verify,'verify-email').length,0);
    assert.equal(await verify.page.locator('#verify-email-dialog').isVisible(),true);
    await verify.page.locator('#verify-email-confirm').click();
    await verify.page.waitForFunction(()=>document.getElementById('verify-email-confirm').hidden);
    assert.match(await verify.page.locator('#verify-email-status').textContent(),/Email confirmed/);
    assert.deepEqual(calls(verify,'verify-email').map(call=>call.body),[{token:'verify-fixture-token'}]);
    assert.equal(verify.user,null,'Verification does not log in');
    await verify.page.locator('#verify-email-account').click();
    assert.equal(await verify.page.locator('#identity-title').textContent(),'Welcome back.');
    await verify.page.locator('#forgot-password').click();
    await verify.page.locator('#identity-name').fill('Fixture account');await verify.page.locator('#identity-submit').click();
    await verify.page.waitForFunction(()=>document.getElementById('identity-description').textContent.includes('spam folder'));
    assert.deepEqual(calls(verify,'forgot')[0].body,{name:'Fixture account'});

    const expired=await fixture(browser,{user:null,fragment:'#verify-email=expired-fixture-token'});
    await expired.page.locator('#verify-email-confirm').click();await expired.page.locator('#verify-email-error').waitFor();
    assert.match(await expired.page.locator('#verify-email-error').textContent(),/expired.*sign in.*resend/i);
    assert.equal(await expired.page.locator('#verify-email-confirm').isHidden(),true);
    await expired.page.locator('#verify-email-dialog').screenshot({path:path.join(outputDir,'recovery-expired-link.png')});

    const canceled=await fixture(browser,{user:null,fragment:'#verify-email=cancel-fixture-token'});
    await canceled.page.keyboard.press('Escape');await canceled.page.locator('#account-button').click();
    assert.equal(calls(canceled,'verify-email').length,0);assert.equal(new URL(canceled.page.url()).hash,'');
    await canceled.page.evaluate(()=>{location.hash='verify-email=same-tab-fixture-token';});
    await canceled.page.locator('#verify-email-dialog').waitFor();assert.equal(new URL(canceled.page.url()).hash,'');
    assert.equal(calls(canceled,'verify-email').length,0);
    await canceled.page.locator('#verify-email-confirm').click();
    await canceled.page.waitForFunction(()=>document.getElementById('verify-email-confirm').hidden);
    assert.equal(calls(canceled,'verify-email')[0].body.token,'same-tab-fixture-token');

    const reset=await fixture(browser,{user:null,fragment:'#reset=reset-fixture-token'});
    assert.equal(new URL(reset.page.url()).hash,'');
    await reset.page.locator('#identity-password').fill(password);await reset.page.locator('#identity-submit').click();
    await reset.page.waitForFunction(()=>document.getElementById('identity-title').textContent==='Welcome back.');
    assert.deepEqual(calls(reset,'reset')[0].body,{token:'reset-fixture-token',password});
    assert.equal(reset.user,null,'Reset preserves cross-browser sign-in flow');
    await reset.page.evaluate(()=>{location.hash='reset=reset-fixture-token';});
    await reset.page.waitForFunction(()=>document.getElementById('identity-title').textContent==='Choose a new password.');
    assert.equal(new URL(reset.page.url()).hash,'');
    await reset.page.locator('#identity-password').fill(password);await reset.page.locator('#identity-submit').click();
    await reset.page.waitForFunction(()=>document.getElementById('identity-title').textContent==='Welcome back.');
    assert.equal(calls(reset,'reset').length,2);

    const guest=await fixture(browser,{user:{id:'guest-fixture',name:'Guest preview',protected:false}});
    await guest.page.locator('#account-button').click();assert.equal(await guest.page.locator('#recovery-section').isHidden(),true);
    await guest.page.locator('#protect-account').click();
    await guest.page.locator('#identity-password').fill(password);await guest.page.locator('#identity-email').fill('guest@example.test');
    await guest.page.locator('#identity-submit').click();
    await guest.page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Check your email'));
    assert.equal(calls(guest,'protect')[0].body.email,'guest@example.test');
    const register=await fixture(browser,{user:null});
    assert.equal(await register.page.locator('#email-field').isHidden(),true);
    await register.page.locator('#identity-password').fill(password);assert.equal(await register.page.locator('#email-field').isVisible(),true);
    await register.page.locator('#identity-name').fill('New fixture');await register.page.locator('#identity-email').fill('register@example.test');
    await register.page.locator('#identity-submit').click();
    await register.page.waitForFunction(()=>document.getElementById('toast').textContent.includes('Check your email'));
    const noEmail=await fixture(browser,{user:null,recovery:{...emptyRecovery(),available:false}});
    await noEmail.page.locator('#identity-password').fill(password);assert.equal(await noEmail.page.locator('#email-field').isHidden(),true);

    const delayed=await fixture(browser);let releaseGet;
    delayed.holdGet=(route,json)=>new Promise(resolve=>{releaseGet=async()=>{await route.fulfill({json}).catch(()=>{});resolve();};});
    await delayed.page.locator('#account-button').click();await delayed.page.waitForFunction(()=>document.getElementById('recovery-refresh').disabled);
    await delayed.page.keyboard.press('Escape');
    delayed.recovery={...emptyRecovery(),email:'fresh@example.test',verified:true};
    await account(delayed);await releaseGet();
    assert.match(await delayed.page.locator('#recovery-status').textContent(),/fresh@example.test/);
    let releasePost;
    delayed.holdPost=(route,body)=>new Promise(resolve=>{releasePost=async()=>{await route.fulfill({json:{ok:true,recovery:{...emptyRecovery(),pending_email:body.email}}}).catch(()=>{});resolve();};});
    await delayed.page.locator('#recovery-email').fill('stale@example.test');await delayed.page.locator('#recovery-password').fill(password);
    await delayed.page.locator('#recovery-save').click();await delayed.page.waitForFunction(()=>document.getElementById('recovery-refresh').disabled);
    await delayed.page.locator('#logout').click();
    await delayed.page.waitForFunction(()=>document.getElementById('identity-dialog').open);
    await releasePost();
    assert.equal(await delayed.page.locator('#account-dialog').isHidden(),true);
    assert.equal(await delayed.page.locator('#recovery-password').inputValue(),'');
    assert.equal(await delayed.page.locator('body').textContent().then(text=>text.includes('stale@example.test')),false);

    const auth=await fixture(browser,{user:null});let releaseLogin,signalLogin;
    const loginStarted=new Promise(resolve=>{signalLogin=resolve;});
    auth.holdAuth=(route,body,data)=>new Promise(resolve=>{
      releaseLogin=async()=>{
        data.user={...protectedUser};
        await route.fulfill({json:{ok:true},headers:{'set-cookie':'qa_session=authenticated-fixture; HttpOnly; Path=/; SameSite=Lax'}});
        resolve();
      };signalLogin();
    });
    await auth.page.locator('#login-tab').click();await auth.page.locator('#identity-name').fill('Login fixture');
    await auth.page.locator('#identity-password').fill(password);await auth.page.locator('#identity-submit').click();await loginStarted;
    for(const selector of ['#register-tab','#identity-dialog [data-close]','#forgot-password'])assert.equal(await auth.page.locator(selector).isDisabled(),true);
    await auth.page.keyboard.press('Escape');assert.equal(await auth.page.locator('#identity-dialog').isVisible(),true);
    await auth.page.evaluate(()=>{location.hash='verify-email=queued-during-login';});
    await auth.page.waitForFunction(()=>location.hash==='');
    assert.equal(await auth.page.locator('#verify-email-dialog').isHidden(),true,'Link waits until authentication settles');
    await releaseLogin();await auth.page.locator('#verify-email-dialog').waitFor();
    assert.equal(await auth.page.locator('#account-button').textContent(),protectedUser.name);
    const sessionCookie=(await auth.context.cookies()).find(cookie=>cookie.name==='qa_session');
    assert.equal(sessionCookie?.httpOnly,true);assert.equal(sessionCookie?.value,'authenticated-fixture');
    assert.equal(await auth.page.evaluate(()=>document.cookie.includes('qa_session')),false);
    assert.ok(auth.calls.filter(call=>call.path==='/api/auth/me').length>=2,'Auth is reconciled through /me');

    let releaseConfig,signalConfig;const configStarted=new Promise(resolve=>{signalConfig=resolve;});
    const boot=await fixture(browser,{user:null,waitReady:false,fragment:'#verify-email=initial-link',holdConfig:(route,json)=>new Promise(resolve=>{
      releaseConfig=async()=>{await route.fulfill({json});resolve();};signalConfig();
    })});
    await configStarted;await boot.page.locator('#verify-email-account').click();
    await boot.page.locator('#identity-name').fill('Initialization fixture');await boot.page.locator('#identity-password').fill(password);
    await boot.page.locator('#identity-submit').click();
    await boot.page.waitForFunction(()=>document.getElementById('account-button').textContent==='Recovery preview');
    await releaseConfig();await boot.page.waitForFunction(()=>document.getElementById('connection-status').classList.contains('online'));
    assert.equal(await boot.page.locator('#account-button').textContent(),protectedUser.name,'Late initial anonymous /me must not overwrite login');
    assert.equal(await boot.page.locator('#identity-dialog').isHidden(),true);

    const ownReset=await fixture(browser,{fragment:'#reset=reset-fixture-token'});let releaseReset,signalReset;
    const resetStarted=new Promise(resolve=>{signalReset=resolve;});
    ownReset.holdAuth=(route,body,data)=>new Promise(resolve=>{releaseReset=async()=>{data.user=null;await route.fulfill({json:{ok:true}});resolve();};signalReset();});
    await ownReset.page.locator('#identity-password').fill(password);await ownReset.page.locator('#identity-submit').click();await resetStarted;
    await ownReset.page.evaluate(()=>{location.hash='verify-email=queued-during-reset';});
    await ownReset.page.waitForFunction(()=>location.hash==='');await releaseReset();
    await ownReset.page.locator('#verify-email-dialog').waitFor();
    assert.equal(await ownReset.page.locator('#account-button').textContent(),'Take a seat','Reset reconciles the revoked signed-in session');
    await ownReset.page.locator('#verify-email-account').click();
    assert.equal(await ownReset.page.locator('#identity-title').textContent(),'Welcome back.');
    await ownReset.page.locator('#forgot-password').click();await ownReset.page.locator('#identity-name').fill('Own reset fixture');
    await ownReset.page.locator('#identity-submit').click();
    await ownReset.page.waitForFunction(()=>document.getElementById('identity-description').textContent.includes('spam folder'));
    assert.equal(calls(ownReset,'forgot').at(-1).headers['x-csrf-token'],undefined,'Revoked CSRF is cleared after same-browser reset');

    const uncertain=await fixture(browser,{user:null});uncertain.failAuth=true;uncertain.failMe=true;
    await uncertain.page.locator('#login-tab').click();await uncertain.page.locator('#identity-name').fill('Uncertain fixture');
    await uncertain.page.locator('#identity-password').fill(password);await uncertain.page.locator('#identity-submit').click();
    await uncertain.page.locator('#identity-reload').waitFor();
    assert.match(await uncertain.page.locator('#identity-error').textContent(),/could not confirm your sign-in status/);
    assert.equal(await uncertain.page.locator('#identity-submit').isDisabled(),true);
    await uncertain.page.keyboard.press('Escape');assert.equal(await uncertain.page.locator('#identity-dialog').isVisible(),true);
    uncertain.failAuth=false;uncertain.failMe=false;await uncertain.page.locator('#identity-reload').click();
    await uncertain.page.waitForFunction(()=>document.getElementById('identity-dialog').open&&!document.getElementById('identity-submit').disabled);
    assert.equal(await uncertain.page.locator('#account-button').textContent(),'Take a seat');
    assert.deepEqual(errors,[]);
    console.log('Recovery UI checks passed: add/change/resend/remove, password and CSRF, legacy/unavailable states, explicit verification and used links, startup/same-tab fragment removal, canceled/queued links, cross-browser and signed-in resets, guest protection/registration, stale close/logout responses, delayed authentication/initialization, uncertain-auth reload, desktop/mobile. All network responses intercepted; no email sent.');
  }finally{for(const context of fixtures)await context.close();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
