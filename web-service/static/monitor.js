const $=id=>document.getElementById(id);
const intervalMs=30000,deadlineMs=10000;
let snapshot=null,timer=null,controller=null,requestVersion=0,stopped=false;
const number=value=>Number.isFinite(value)?value.toLocaleString():'—';
function date(value){const parsed=new Date(value);return value&&!Number.isNaN(parsed.valueOf())?parsed.toLocaleString():null;}
function append(parent,tag,text,className){const node=document.createElement(tag);node.textContent=text;if(className)node.className=className;parent.append(node);return node;}
function workerStatus(row){return {compacting:'Astra compacting',calculating:'Astra calculating',queued:'Astra queued'}[row.worker_state]||'Astra thinking';}
function status(row){
  if(row.status==='finished'){
    const outcome={win:'Human won',loss:'Astra won',draw:'Draw'}[row.human_outcome]||'Finished';
    const reason={checkmate:'checkmate',resignation:'resignation',stalemate:'stalemate',agreement:'draw agreed',insufficient_material:'insufficient material',fifty_moves:'fifty-move rule',threefold_repetition:'repetition',timeout:'time expired'}[row.termination]||String(row.termination||'').replaceAll('_',' ');
    return outcome+(reason?'; '+reason:'')+(row.active_response?' · '+workerStatus(row)+' (post-game chat)':'');
  }
  if(row.status==='suspended')return 'Suspended · can resume';
  if(row.active_response)return workerStatus(row);
  if(['error','interrupted'].includes(row.worker_state))return 'Astra interrupted · retry available';
  if(row.waiting_for==='human')return 'Awaiting human move';
  if(row.waiting_for==='astra')return 'Awaiting Astra';
  return 'Unfinished';
}
function replays(cell,row){
  let any=false;
  for(const [key,label] of [['chat','with chat'],['moves','moves only']]){
    const item=row.replays?.[key];if(!item)continue;
    const state=item.listed?'Listed':item.shared?'Unlisted link':item.saved?'Saved':null;
    if(state){append(cell,'span',state+' · '+label,'monitor-replay');any=true;}
    if(item.building){append(cell,'span','Building · '+label,'monitor-detail');any=true;}
  }
  if(!any)cell.textContent='—';
}
function renderRows(){
  if(!snapshot)return;
  const query=$('monitor-search').value.trim().toLocaleLowerCase(),filter=$('monitor-filter').value;
  const games=snapshot.games.filter(row=>(!query||String(row.name).toLocaleLowerCase().includes(query))&&(filter==='all'||(row.status==='finished')===(filter==='finished')));
  games.sort((a,b)=>(Date.parse(b.updated_at)||0)-(Date.parse(a.updated_at)||0)||String(a.game_id).localeCompare(String(b.game_id)));
  const fragment=document.createDocumentFragment();
  for(const row of games){
    const tr=document.createElement('tr'),player=append(tr,'td','');
    append(player,'span',row.name||'Unknown','monitor-player');
    const started=date(row.created_at),updated=date(row.updated_at);
    if(started)append(player,'span','Started '+started,'monitor-detail');
    if(updated&&updated!==started)append(player,'span','Updated '+updated,'monitor-detail');
    append(tr,'td',{white:'White',black:'Black'}[row.human_side]||'—');
    append(tr,'td',row.last_move||'No moves yet');
    append(tr,'td',status(row),row.active_response?'monitor-working':'');
    replays(append(tr,'td',''),row);fragment.append(tr);
  }
  $('monitor-rows').replaceChildren(fragment);$('monitor-empty').hidden=games.length!==0;
  $('monitor-count').textContent=`${number(games.length)} of ${number(snapshot.games.length)} games`;
}
function render(data){
  snapshot=data;$('monitor-access').hidden=true;$('monitor-data').hidden=false;
  const summary=$('monitor-summary');summary.replaceChildren();
  for(const [value,label] of [[data.summary.player_games,'Player games'],[data.summary.finished_player_games,'Finished'],[data.summary.unfinished_player_games,'Unfinished'],[data.activity.active_responses,'Astra responses in progress']]){
    const card=append(summary,'div','');append(card,'strong',number(value));append(card,'span',label);
  }
  const budget=data.today_budget;
  $('monitor-budget').textContent=budget?`UTC daily usage (${budget.day}): ${number(budget.tokens)} tokens of ${number(data.max_daily_tokens)} · ${number(budget.turns)} model actions`:'No model usage recorded today.';
  $('monitor-excluded').hidden=!data.summary.excluded_games;
  $('monitor-excluded').textContent=`${number(data.summary.excluded_games)} known test games excluded from this table. Active response counts include the whole service.`;
  renderRows();
}
function clearPrivate(){
  snapshot=null;$('monitor-data').hidden=true;
  for(const id of ['monitor-summary','monitor-rows','monitor-count','monitor-budget','monitor-excluded'])$(id).replaceChildren();
  $('monitor-search').value='';$('monitor-filter').value='all';
}
function access(statusCode){
  clearPrivate();$('monitor-access').hidden=false;
  const denied=statusCode===403;
  $('monitor-access-title').textContent=denied?'This account cannot view the monitor.':'Sign in to view the monitor.';
  $('monitor-access-detail').textContent=denied?'Return to the board and sign out, then sign in with the authorized account.':'Use your authorized player account. Site activity is private.';
  $('monitor-sign-in').textContent=denied?'Return to your account':'Sign in';
  $('monitor-sign-in').href=denied?'/':'/?monitor=1';
  $('monitor-status').textContent=denied?'Operator access required.':'Your session is not signed in.';$('monitor-status').classList.remove('stale');
}
function schedule(){clearTimeout(timer);if(!document.hidden&&!stopped)timer=setTimeout(refresh,intervalMs);}
function pauseAndClear(){
  requestVersion++;clearTimeout(timer);controller?.abort();controller=null;clearPrivate();
  $('monitor-refresh').disabled=false;$('monitor-access').hidden=true;$('monitor-status').textContent='Checking access…';$('monitor-status').classList.remove('stale');
}
async function refresh(){
  if(controller||document.hidden||stopped)return;
  clearTimeout(timer);const version=++requestVersion,activeController=new AbortController();controller=activeController;
  const deadline=setTimeout(()=>activeController.abort(),deadlineMs);$('monitor-refresh').disabled=true;
  if(!snapshot)$('monitor-status').textContent='Checking site activity…';
  let keepPolling=true;
  try{
    const response=await fetch('/api/operator/games',{headers:{Accept:'application/json'},credentials:'same-origin',cache:'no-store',signal:activeController.signal});
    if(version!==requestVersion||stopped)return;
    if([401,403].includes(response.status)){access(response.status);keepPolling=false;return;}
    if(!response.ok)throw new Error('Unavailable');
    const data=await response.json();
    if(version!==requestVersion||stopped)return;
    if(!Array.isArray(data.games)||!data.summary||!data.activity||!date(data.as_of))throw new Error('Invalid snapshot');
    render(data);$('monitor-status').textContent='Updated '+date(data.as_of)+' · refreshes every 30 seconds';$('monitor-status').classList.remove('stale');
  }catch{
    if(version!==requestVersion||stopped)return;
    $('monitor-status').textContent=snapshot?'Stale snapshot from '+date(snapshot.as_of)+'. Refresh failed; retrying automatically.':'Could not load site activity. Check your connection, then refresh.';
    $('monitor-status').classList.add('stale');
  }finally{
    clearTimeout(deadline);
    if(version===requestVersion){controller=null;$('monitor-refresh').disabled=false;if(keepPolling)schedule();}
  }
}
$('monitor-refresh').addEventListener('click',refresh);
$('monitor-search').addEventListener('input',renderRows);
$('monitor-filter').addEventListener('change',renderRows);
document.addEventListener('visibilitychange',()=>{if(document.hidden)pauseAndClear();else refresh();});
window.addEventListener('online',refresh);
window.addEventListener('pagehide',()=>{stopped=true;pauseAndClear();});
window.addEventListener('pageshow',()=>{if(stopped){stopped=false;$('monitor-refresh').disabled=false;refresh();}});
refresh();
