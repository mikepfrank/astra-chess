// Optional browser QA dependency; never imported by the web service.
const fs=require('node:fs/promises'),path=require('node:path');
let chromium;
try{({chromium}=require(process.env.ASTRA_PLAYWRIGHT_MODULE||'playwright'));}
catch(error){throw new Error('Install optional Playwright or set ASTRA_PLAYWRIGHT_MODULE to its module directory. See tests/browser/README.md.',{cause:error});}
const outputDir=path.resolve(__dirname,'../../var/browser-qa');
const fixtureOrigin='http://127.0.0.1:8793';
function launchBrowser(){
  const channel=process.env.ASTRA_BROWSER_CHANNEL||'chrome';
  return chromium.launch({headless:true,...(channel==='chromium'?{}:{channel})});
}
async function loadFixtureAccess(){
  const access=JSON.parse(await fs.readFile(path.join(outputDir,'replay-ui-access.json'),'utf8'));
  if(access.origin!==fixtureOrigin||!/^browser-qa-[a-f0-9]{32}$/.test(access.fixture_id||'')){
    throw new Error('This is not a current disposable browser QA fixture. Start fixture_server.py.');
  }
  const response=await fetch(fixtureOrigin+'/api/browser-qa/fixture',{signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw new Error('The disposable fixture server is not available.');
  const marker=await response.json();
  if(marker.fixture_id!==access.fixture_id||marker.model_calls_allowed!==false){
    throw new Error('Fixture identity mismatch; refusing to mutate a different server.');
  }
  return access;
}
function publicOrigin(){
  const args=process.argv.slice(2);
  if(args.length!==2||args[0]!=='--origin')throw new Error('Usage: node tests/browser/public_readonly.cjs --origin https://your-host.example');
  const url=new URL(args[1]);
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.pathname!=='/'||url.search||url.hash){
    throw new Error('Supply an HTTP(S) origin without credentials, path, query or fragment.');
  }
  return url.origin;
}
async function bounded(promise,label,timeoutMs=10000){
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(label+' timed out')),timeoutMs);})]);}
  finally{clearTimeout(timer);}
}
module.exports={chromium,launchBrowser,outputDir,fixtureOrigin,loadFixtureAccess,publicOrigin,bounded};
