import {BoardView, START_FEN, pieceImage, pieceNames, renderCaptures, formatClock} from './pieces.js';

const $=id=>document.getElementById(id);
const state={user:null,csrf:null,config:null,game:null,gameId:null,pending:false,mode:'register',next:null,polling:false,resetToken:null,messageKey:null,availabilityChecking:false,availabilityError:null,lastAvailabilityCheck:0};
let toastTimer, pollTimer, promotionResolve, confirmResolve;
const titleCase=text=>String(text||'').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const parseDate=value=>new Date(typeof value==='number'&&value<1e12?value*1000:value);
function toast(text){$('toast').textContent=text;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
function showError(id,error){$(id).textContent=error.message||String(error);$(id).hidden=false;}
function openDialog(id){const dialog=$(id);if(!dialog.open)dialog.showModal();}
function closeDialog(id){$(id).close();}
function connection(online,text){$('connection-status').classList.toggle('online',online);$('connection-status').lastChild.textContent=text;}
async function api(path,{method='GET',body,signal}={}){
  const headers={Accept:'application/json'};
  if(body!==undefined)headers['Content-Type']='application/json';
  if(method!=='GET'&&state.csrf)headers['X-CSRF-Token']=state.csrf;
  const response=await fetch(path,{method,headers,credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',signal});
  const data=await response.json().catch(()=>({}));
  if(!response.ok){
    let detail=data.detail||data.message||`Request failed (${response.status}).`;
    if(Array.isArray(detail))detail=detail.map(d=>d.msg||String(d)).join(' ');
    if(typeof detail==='object')detail=detail.message||JSON.stringify(detail);
    const error=new Error(String(detail));error.status=response.status;throw error;
  }
  return data;
}
async function refreshIdentity(){const result=await api('/api/auth/me');setIdentity(result);return result;}
function setIdentity(result){
  state.user=result.user;state.csrf=result.csrf_token||state.csrf;
  if(result.email_reset_available!==undefined)state.emailResetAvailable=result.email_reset_available;
  $('account-button').textContent=state.user?state.user.name:'Take a seat';
  if(!state.game)$('bottom-name').textContent=state.user?.name||'You';
  $('human-avatar').textContent=(state.user?.name||'Y').slice(0,1).toUpperCase();
}
function playerReady(){return state.config?.player_available===true&&!state.availabilityError;}
function updateAvailability(){
  const available=playerReady();
  const checking=state.availabilityChecking;
  const testing=state.config?.player_mode==='test';
  $('availability-banner').hidden=available&&!testing;
  const unavailableText=state.availabilityError?'The server could not be reached. Check your connection, then try again.':state.config?.player_mode==='disabled'?'Live play is not enabled on this server yet. The operator needs to enable Astra before a game can start.':'Astra is currently unavailable. Check again shortly; the operator may need to restore the player connection.';
  $('availability-text').textContent=testing&&available?'Test environment: games here use a scripted test opponent to check the interface. This is not live Astra play.':unavailableText;
  $('availability-check').hidden=available;
  $('availability-check').disabled=checking;
  $('availability-check').textContent=checking?'Checking…':'Check availability';
  $('play-white').disabled=!available||checking||state.pending;$('play-black').disabled=!available||checking||state.pending;
  $('side-options').hidden=!available||checking;
  $('new-title').textContent=checking?'Checking Astra…':available?'Which side is yours?':'Astra is unavailable';
  $('new-description').textContent=checking?'Checking whether the player is ready for a new game.':available?'White makes the first move. Black has the first reply.':'A new game cannot start until Astra is connected.';
  $('new-availability').hidden=available||checking;
  $('new-availability').textContent=unavailableText;
  $('new-check-availability').hidden=available;
  $('new-check-availability').disabled=checking;
  $('new-check-availability').textContent=checking?'Checking…':'Check again';
  $('new-saved-games').hidden=!state.user;
  $('new-saved-note').textContent=state.user?'You are still signed in. Your account and saved games remain available; you can return to the board without starting a game.':'You can return to the board and check again later. No game has been started.';
  $('welcome-title').textContent=available?'Take a seat.':'Astra is unavailable';
  $('welcome-description').textContent=available?'Choose a side and meet Astra across the board.':'Live play is not ready yet. Check availability or return to one of your saved games.';
  $('welcome-new').textContent=available?'Start a game ↗':'Check availability';
  $('new-game').textContent=available?'New game':'Player availability';
  if(state.config){
    $('model-detail').textContent=`Player: ${state.config.model||'configured by operator'}${state.config.reasoning?' · '+state.config.reasoning+' reasoning':''}. ${state.config.suspend_hours?`Inactive games suspend after ${state.config.suspend_hours} hours and can be resumed.`:''}`;
  }
}
async function refreshAvailability(){
  if(state.availabilityChecking)return playerReady();
  state.availabilityChecking=true;updateAvailability();
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),8000);
  try{state.config=await api('/api/config',{signal:controller.signal});state.availabilityError=null;}
  catch(error){state.availabilityError=error.message;}
  finally{clearTimeout(timeout);state.availabilityChecking=false;state.lastAvailabilityCheck=Date.now();updateAvailability();}
  return playerReady();
}
const board=new BoardView($('board'),{
  onMove:move=>act('move',{move}),
  onPromotion:choosePromotion,
  onSelect:text=>$('board-hint').textContent=text
});
board.set({fen:START_FEN});
$('white-choice-piece').append(pieceImage('K'));$('black-choice-piece').append(pieceImage('k'));

function renderMoves(){
  const moves=state.game?.moves||[];
  $('move-count').textContent=moves.length?`${moves.length} ${moves.length===1?'ply':'plies'}`:'No moves yet';
  const list=$('moves');const atBottom=list.scrollHeight-list.scrollTop-list.clientHeight<35;
  list.replaceChildren();
  if(!moves.length){const empty=document.createElement('p');empty.className='empty-note';empty.textContent='The first move is still ahead.';list.append(empty);return;}
  for(let i=0;i<moves.length;i+=2){
    const row=document.createElement('div');row.className='move-row';
    const number=document.createElement('span');number.className='move-number';number.textContent=i/2+1+'.';row.append(number);
    for(let offset=0;offset<2;offset++){
      const token=document.createElement('span');token.className='move-token';
      if(moves[i+offset]){token.textContent=moves[i+offset].san;token.classList.toggle('latest',i+offset===moves.length-1);}
      row.append(token);
    }list.append(row);
  }
  if(atBottom)list.scrollTop=list.scrollHeight;
}
function renderMessages(){
  const messages=state.game?.messages||[];
  const key=JSON.stringify(messages.map(m=>[m.id,m.text,m.author]));
  if(key===state.messageKey)return;state.messageKey=key;
  const log=$('messages');const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<60;
  log.replaceChildren();
  if(!messages.length){
    const empty=document.createElement('div');empty.className='conversation-empty';
    const heading=document.createElement('p');heading.textContent=state.game?'The board is set.':'More than a silent opponent.';
    const text=document.createElement('span');text.textContent=state.game?'Say hello, ask a question, or make your move.':'Ask about an idea, talk through the last move, or simply enjoy the game.';
    empty.append(heading,text);log.append(empty);return;
  }
  for(const message of messages){
    const article=document.createElement('article');article.className='message '+(['human','astra','system'].includes(message.author)?message.author:'system');
    const heading=document.createElement('div');heading.className='message-heading';
    const author=document.createElement('span');author.className='message-author';author.textContent=message.author==='astra'?'Astra':message.author==='human'?(state.user?.name||'You'):'Game';
    const time=document.createElement('span');const date=parseDate(message.created_at);time.textContent=Number.isNaN(date.getTime())?'':date.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
    const body=document.createElement('p');body.className='message-body';body.textContent=message.text;
    heading.append(author,time);article.append(heading,body);log.append(article);
  }
  if(atBottom)log.scrollTop=log.scrollHeight;
}
function statusText(game){
  if(game.status==='finished')return `${game.result||'Game over'} · ${titleCase(game.termination||'Game finished')}`;
  if(game.status==='suspended')return 'This game is resting. Resume whenever you are ready.';
  if(game.worker?.state==='error')return game.worker.message||'Astra was interrupted. Your game is saved; try resuming the player.';
  if(game.worker?.state==='disabled')return game.worker.message||'Astra is unavailable. Your game is saved.';
  if(game.worker?.state==='queued')return 'Your game is queued. Astra will be with you shortly.';
  if(game.worker?.state==='thinking')return 'Astra is thinking. You can keep the conversation going.';
  const turn=game.fen.split(' ')[1]==='w'?'white':'black';
  return turn===game.human_side?'Your move. Take your time.':'Astra’s move. Considering the position.';
}
function renderGame(game){
  if(state.game?.id===game.id&&Number(game.version)<Number(state.game.version))return;
  const boardChanged=state.game?.fen!==game.fen;
  const oldPly=state.game?.ply;
  state.game=game;state.gameId=game.id;
  $('welcome-overlay').hidden=true;
  const side=game.human_side, turn=game.fen.split(' ')[1]==='w'?'white':'black';
  const active=game.status==='active', humanTurn=turn===side;
  const bottomSide=board.flipped?'black':'white', topSide=bottomSide==='white'?'black':'white';
  board.set({fen:game.fen,board:game.board,legalMoves:game.legal_moves||[],side,enabled:active&&humanTurn&&!state.pending,lastMove:game.moves?.at(-1)?.uci,flipped:board.flipped});
  const name=state.user?.name||game.name||'You';
  $('top-name').textContent=topSide===side?name:'Astra';
  $('bottom-name').textContent=bottomSide===side?name:'Astra';
  $('top-detail').textContent=titleCase(topSide)+(topSide===side?' · Your side':' · Deliberation + calculation');
  $('bottom-detail').textContent=titleCase(bottomSide)+(bottomSide===side?' · Your side':' · Deliberation + calculation');
  const topHuman=topSide===side;
  $('top-avatar').textContent=topHuman?name.slice(0,1).toUpperCase():'A';
  $('top-avatar').className='avatar '+(topHuman?'human-avatar':'astra-avatar');
  $('human-avatar').textContent=topHuman?'A':name.slice(0,1).toUpperCase();
  $('human-avatar').className='avatar '+(topHuman?'astra-avatar':'human-avatar');
  $('top-status').textContent=game.status==='finished'?'GAME COMPLETE':turn===topSide?(topHuman?'YOUR MOVE':titleCase(game.worker?.state||'Thinking').toUpperCase()):'';
  $('bottom-status').textContent=game.status==='finished'?'GAME COMPLETE':turn===bottomSide?(topHuman?'ASTRA’S MOVE':'YOUR MOVE'):'';
  $('top-status').classList.toggle('active',active&&turn===topSide);$('bottom-status').classList.toggle('active',active&&turn===bottomSide);
  $('astra-clock').textContent=formatClock(game.clock?.remaining_seconds);
  $('astra-clock').title='Astra’s remaining thinking time';
  // Keep the only clock attached to Astra even when the board is flipped.
  const clockHost=topHuman?$('bottom-status').parentElement:$('top-status').parentElement;
  clockHost.append($('astra-clock'));
  renderCaptures($('top-captures'),game.moves||[],topSide,side);
  renderCaptures($('bottom-captures'),game.moves||[],bottomSide,side);
  $('game-status-text').textContent=statusText(game);
  $('game-status').className='game-status '+(game.status==='finished'?'finished':game.worker?.state==='thinking'?'thinking':game.worker?.state==='error'?'error':'');
  $('draw-banner').hidden=!game.draw_offer||game.status==='finished';
  $('draw-text').textContent=game.draw_offer==='astra'?'Astra offers a draw.':'Your draw offer is pending.';
  $('accept-draw').hidden=game.draw_offer!=='astra';$('decline-draw').hidden=game.draw_offer!=='astra';
  $('offer-draw').disabled=!active||!!game.draw_offer||state.pending;
  $('resign').disabled=game.status==='finished'||state.pending;
  $('claim-draw').hidden=!game.claimable||!active||!humanTurn;
  $('resume-game').hidden=game.status!=='suspended';
  $('retry-worker').hidden=!['error','disabled'].includes(game.worker?.state)||game.status==='finished';
  $('share-game').hidden=game.status!=='finished';
  $('download-pgn').hidden=false;$('download-pgn').href=`/api/games/${encodeURIComponent(game.id)}/pgn`;
  $('message-input').disabled=game.status!=='active'||state.pending;
  $('send-message').disabled=game.status!=='active'||state.pending||!$('message-input').value.trim();
  for(const id of ['accept-draw','decline-draw','claim-draw','resume-game','retry-worker'])$(id).disabled=state.pending;
  if(boardChanged)$('board-hint').textContent=humanTurn?'Your move: select a piece, then a highlighted square.':'You can inspect the board while Astra thinks.';
  if(oldPly!==game.ply||!$('moves').querySelector('.move-row'))renderMoves();
  renderMessages();connection(true,'Connected');
}
function rememberGame(id){
  const url=new URL(location.href);url.searchParams.set('game',id);history.replaceState(null,'',url);
  if(state.user)try{localStorage.setItem('astra-game-'+state.user.id,id);}catch{}
}
async function loadGame(id){
  const game=await api(`/api/games/${encodeURIComponent(id)}`);
  board.flipped=game.human_side==='black';state.messageKey=null;state.game=null;
  renderGame(game);rememberGame(id);return game;
}
async function poll(){
  clearTimeout(pollTimer);
  if(state.polling)return;
  if(document.hidden){pollTimer=setTimeout(poll,10000);return;}
  state.polling=true;
  try{
    if($('new-dialog').open&&!playerReady()&&Date.now()-state.lastAvailabilityCheck>10000)await refreshAvailability();
    if(state.gameId&&state.user&&!state.pending){
      const id=state.gameId;
      const game=await api(`/api/games/${encodeURIComponent(id)}`);
      if(state.gameId===id)renderGame(game);
    }
  }catch(error){
    connection(false,'Reconnecting');
    if(error.status===401){state.user=null;state.gameId=null;state.game=null;clearPrivateView();await refreshIdentity().catch(()=>{});toast('Your session has expired. Sign in again to return to your game.');}
  }finally{state.polling=false;pollTimer=setTimeout(poll,2000);}
}
function clearPrivateView(){
  state.messageKey=null;board.set({fen:START_FEN,flipped:false});
  $('welcome-overlay').hidden=false;$('top-name').textContent='Astra';$('bottom-name').textContent='You';
  $('top-detail').textContent='Your opponent';$('bottom-detail').textContent='Choose White or Black';
  $('top-status').textContent='READY WHEN YOU ARE';$('bottom-status').textContent='';
  $('top-captures').replaceChildren();$('bottom-captures').replaceChildren();$('astra-clock').textContent='—';
  $('game-status-text').textContent='A fresh game, at your own pace.';$('game-status').className='game-status';
  $('message-input').value='';$('message-input').disabled=true;$('send-message').disabled=true;
  $('offer-draw').disabled=true;$('resign').disabled=true;
  for(const id of ['draw-banner','claim-draw','resume-game','retry-worker','share-game','download-pgn'])$(id).hidden=true;
  renderMessages();renderMoves();
}
async function act(action,extra={}){
  if(!state.game||state.pending)return false;
  const game=state.game;state.pending=true;renderGame(game);
  try{
    const result=await api(`/api/games/${encodeURIComponent(game.id)}/actions`,{method:'POST',body:{action,...extra,version:game.version,request_id:crypto.randomUUID()}});
    if(state.gameId===game.id)renderGame(result);
    return true;
  }catch(error){
    toast(error.status===409?'The game changed before that action arrived. The board has been refreshed; please try again.':error.message);
    try{const fresh=await api(`/api/games/${encodeURIComponent(game.id)}`);if(state.gameId===game.id)renderGame(fresh);}catch{}
    return false;
  }finally{state.pending=false;if(state.game)renderGame(state.game);}
}
function choosePromotion(moves,side){
  const options=$('promotion-options');options.replaceChildren();
  return new Promise(resolve=>{
    promotionResolve=resolve;
    for(const kind of ['q','r','b','n']){
      const move=moves.find(m=>m[4]===kind);if(!move)continue;
      const button=document.createElement('button');button.type='button';button.className='promotion-choice';
      button.append(pieceImage(side==='white'?kind.toUpperCase():kind));
      const name=document.createElement('span');name.textContent=pieceNames[kind];button.append(name);
      button.addEventListener('click',()=>{promotionResolve=null;closeDialog('promotion-dialog');resolve(move);});options.append(button);
    }openDialog('promotion-dialog');
  });
}
function cancelPromotion(){const resolve=promotionResolve;promotionResolve=null;closeDialog('promotion-dialog');resolve?.(null);}
$('cancel-promotion').addEventListener('click',cancelPromotion);
$('promotion-dialog').addEventListener('cancel',event=>{event.preventDefault();cancelPromotion();});
function confirmAction(title,description,label){
  $('confirm-title').textContent=title;$('confirm-description').textContent=description;$('confirm-accept').textContent=label;
  openDialog('confirm-dialog');return new Promise(resolve=>confirmResolve=resolve);
}
function finishConfirm(value){closeDialog('confirm-dialog');confirmResolve?.(value);confirmResolve=null;}
$('confirm-cancel').addEventListener('click',()=>finishConfirm(false));$('confirm-accept').addEventListener('click',()=>finishConfirm(true));
$('confirm-dialog').addEventListener('cancel',event=>{event.preventDefault();finishConfirm(false);});

function setIdentityMode(mode){
  state.mode=mode;$('identity-error').hidden=true;$('identity-password').value='';
  $('identity-tabs').hidden=!['register','login'].includes(mode);
  $('register-tab').classList.toggle('active',mode==='register');$('login-tab').classList.toggle('active',mode==='login');
  const titles={register:'What should we call you?',login:'Welcome back.',protect:'Keep your seat.',forgot:'Recover your account.',reset:'Choose a new password.'};
  const descriptions={register:'A guest name is all you need. This browser will remember your seat.',login:'Sign in to return to your games from any device.',protect:'Add a password to keep this name across devices and enable optional memory.',forgot:'Enter your account name. If recovery is configured, a reset link will be sent to its email address.',reset:'Use at least 10 characters. This will replace your previous password.'};
  $('identity-title').textContent=titles[mode];$('identity-description').textContent=descriptions[mode];
  $('name-field').hidden=['protect','reset'].includes(mode);$('identity-name').required=!['protect','reset'].includes(mode);
  $('password-field').hidden=mode==='forgot';$('identity-password').required=['login','protect','reset'].includes(mode);
  $('identity-password').minLength=mode==='login'?1:10;
  $('identity-password').autocomplete=mode==='login'?'current-password':'new-password';
  $('password-label').textContent=mode==='register'?'Password (optional; at least 10 characters)':'Password';
  $('password-help').hidden=!['register','protect'].includes(mode);
  $('email-field').hidden=!(state.emailResetAvailable&&mode==='protect');
  $('guest-warning').hidden=mode!=='register';
  $('identity-submit').textContent={register:'Take a seat',login:'Sign in',protect:'Protect my account',forgot:'Send reset link',reset:'Set new password'}[mode];
  $('forgot-password').hidden=mode!=='login'||!state.emailResetAvailable;
  if(mode==='protect')$('identity-name').value=state.user?.name||'';
}
function showIdentity(mode='register',next=null){state.next=next;setIdentityMode(mode);openDialog('identity-dialog');}
async function requireUser(next){if(state.user){await next();return;}showIdentity('register',next);}
$('register-tab').addEventListener('click',()=>setIdentityMode('register'));
$('login-tab').addEventListener('click',()=>setIdentityMode('login'));
$('forgot-password').addEventListener('click',()=>setIdentityMode('forgot'));
$('identity-password').addEventListener('input',()=>{$('email-field').hidden=!(state.emailResetAvailable&&['register','protect'].includes(state.mode)&&$('identity-password').value);});
$('identity-form').addEventListener('submit',async event=>{
  event.preventDefault();$('identity-error').hidden=true;$('identity-submit').disabled=true;
  const mode=state.mode;
  let payload={name:$('identity-name').value.trim(),password:$('identity-password').value};
  if(['register','protect'].includes(mode))payload.email=$('email-field').hidden?'':$('identity-email').value.trim();
  if(mode==='protect')delete payload.name;
  if(mode==='forgot')payload={name:payload.name};
  if(mode==='reset')payload={token:state.resetToken,password:payload.password};
  try{
    const result=await api('/api/auth/'+mode,{method:'POST',body:payload});
    if(mode==='forgot'){
      $('identity-description').textContent='If that account has recovery enabled, a reset link has been sent. Check your email.';
      $('identity-form').reset();return;
    }
    if(mode==='reset'){
      state.resetToken=null;const url=new URL(location.href);url.hash='';history.replaceState(null,'',url);
      toast('Password updated. You can sign in with your new password.');
      setIdentityMode('login');return;
    }
    if(result.user)setIdentity(result);else await refreshIdentity();
    closeDialog('identity-dialog');$('identity-form').reset();
    toast(mode==='protect'?'Your account is now protected.':`Welcome, ${state.user.name}.`);
    const next=state.next;state.next=null;if(next)await next();
    else if(mode==='login')await showGames();
  }catch(error){showError('identity-error',error);}
  finally{$('identity-submit').disabled=false;}
});
$('account-button').addEventListener('click',async()=>{
  if(!state.user){showIdentity();return;}
  $('account-title').textContent=state.user.name;
  $('account-description').textContent=state.user.protected?'Your account is protected with a password.':'A guest account, remembered by this browser. Add a password to keep access across devices.';
  $('protect-account').hidden=state.user.protected;$('memory-section').hidden=!state.user.protected;
  if(state.user.protected)try{const memory=await api('/api/auth/memory');$('memory-enabled').checked=memory.enabled;$('memory-text').value=memory.text||'';}catch(error){toast(error.message);}
  openDialog('account-dialog');
});
$('protect-account').addEventListener('click',()=>{closeDialog('account-dialog');showIdentity('protect');});
$('memory-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{await api('/api/auth/memory',{method:'PUT',body:{enabled:$('memory-enabled').checked,text:$('memory-text').value}});toast('Memory preferences saved.');}
  catch(error){toast(error.message);}finally{button.disabled=false;}
});
$('logout').addEventListener('click',async()=>{
  if(!state.user.protected&&!await confirmAction('Leave this guest seat?','This guest identity has no password. Signing out may lose access to its games; add a password first if you want to keep it.','Sign out'))return;
  try{
    await api('/api/auth/logout',{method:'POST',body:{}});closeDialog('account-dialog');
    state.game=null;state.gameId=null;state.messageKey=null;
    const url=new URL(location.href);url.searchParams.delete('game');history.replaceState(null,'',url);
    // A reload clears every view of the previous player's private game.
    location.reload();
  }catch(error){toast(error.message);}
});
async function showNewGame(){$('new-error').hidden=true;openDialog('new-dialog');await refreshAvailability();}
for(const id of ['new-game','welcome-new'])$(id).addEventListener('click',showNewGame);
$('new-check-availability').addEventListener('click',refreshAvailability);
$('availability-check').addEventListener('click',refreshAvailability);
$('new-saved-games').addEventListener('click',()=>{closeDialog('new-dialog');requireUser(showGames);});
async function newGame(side){
  if(state.pending||state.availabilityChecking)return;
  if(!playerReady()){await refreshAvailability();return;}
  if(!state.user){closeDialog('new-dialog');showIdentity('register',async()=>{await showNewGame();if(playerReady())await newGame(side);});return;}
  state.pending=true;updateAvailability();$('new-error').hidden=true;
  try{
    const game=await api('/api/games',{method:'POST',body:{side}});
    board.flipped=side==='black';state.game=null;state.messageKey=null;
    renderGame(game);rememberGame(game.id);closeDialog('new-dialog');$('message-input').value='';$('message-count').textContent='0 / 2000';
  }catch(error){showError('new-error',error);await refreshAvailability();}
  finally{state.pending=false;updateAvailability();if(state.game)renderGame(state.game);}
}
$('play-white').addEventListener('click',()=>newGame('white'));$('play-black').addEventListener('click',()=>newGame('black'));
async function showGames(){
  openDialog('games-dialog');$('game-list').textContent='Loading your games…';
  try{
    const {games}=await api('/api/games');$('game-list').replaceChildren();
    if(!games.length){const note=document.createElement('p');note.className='muted';note.textContent='Your first scoresheet is waiting. Start a new game to take a seat.';$('game-list').append(note);return;}
    for(const game of games){
      const button=document.createElement('button');button.className='saved-game';button.type='button';
      const title=document.createElement('strong');title.textContent=`You as ${titleCase(game.human_side)} · ${game.status==='finished'?(game.result||'Finished'):titleCase(game.status)}`;
      const subtitle=document.createElement('span');const date=parseDate(game.updated_at);subtitle.textContent=`${game.ply} ${game.ply===1?'ply':'plies'}${Number.isNaN(date.getTime())?'':' · '+date.toLocaleString()}`;
      button.append(title,subtitle);button.addEventListener('click',async()=>{button.disabled=true;try{await loadGame(game.id);closeDialog('games-dialog');}catch(error){toast(error.message);}finally{button.disabled=false;}});
      $('game-list').append(button);
    }
  }catch(error){$('game-list').textContent=error.message;}
}
$('games-button').addEventListener('click',()=>requireUser(showGames));
$('flip-board').addEventListener('click',()=>{board.flipped=!board.flipped;if(state.game)renderGame(state.game);else board.set({fen:START_FEN,flipped:board.flipped});});
$('resign').addEventListener('click',async()=>{if(await confirmAction('Resign this game?','This ends the game with a win for Astra. Your moves and conversation will remain in your games.','Resign game'))await act('resign');});
$('offer-draw').addEventListener('click',()=>act('offer_draw'));
$('accept-draw').addEventListener('click',async()=>{if(await confirmAction('Accept the draw?','The game will finish as a draw by agreement.','Accept draw'))await act('accept_draw');});
$('decline-draw').addEventListener('click',()=>act('decline_draw'));
$('claim-draw').addEventListener('click',()=>act('claim_draw'));
$('resume-game').addEventListener('click',()=>act('resume'));
$('retry-worker').addEventListener('click',()=>act('retry'));
$('message-input').addEventListener('input',()=>{$('message-count').textContent=`${$('message-input').value.length} / 2000`;$('send-message').disabled=state.pending||!$('message-input').value.trim()||state.game?.status!=='active';});
$('message-input').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();$('message-form').requestSubmit();}});
$('message-form').addEventListener('submit',async event=>{
  event.preventDefault();const text=$('message-input').value.trim();if(!text)return;
  if(await act('message',{text})){if($('message-input').value.trim()===text)$('message-input').value='';$('message-input').dispatchEvent(new Event('input'));$('messages').scrollTop=$('messages').scrollHeight;}
});
$('share-game').addEventListener('click',()=>{$('share-commentary').checked=false;$('share-result').hidden=true;$('share-error').hidden=true;openDialog('share-dialog');});
$('create-share').addEventListener('click',async()=>{
  if(!state.game)return;
  $('create-share').disabled=true;$('share-error').hidden=true;
  try{
    const result=await api(`/api/games/${encodeURIComponent(state.game.id)}/share`,{method:'POST',body:{include_commentary:$('share-commentary').checked}});
    const url=new URL(result.url,location.origin);
    if(url.origin!==location.origin)throw new Error('The server returned an unexpected replay address.');
    $('share-url').value=url.href;$('open-share').href=url.href;$('share-result').hidden=false;
  }catch(error){showError('share-error',error);}finally{$('create-share').disabled=false;}
});
$('copy-share').addEventListener('click',async()=>{try{await navigator.clipboard.writeText($('share-url').value);toast('Replay link copied.');}catch{$('share-url').focus();$('share-url').select();toast('Select and copy the replay link.');}});
$('revoke-share').addEventListener('click',async()=>{
  if(!state.game)return;
  try{await api(`/api/games/${encodeURIComponent(state.game.id)}/share`,{method:'DELETE'});$('share-result').hidden=true;toast('The replay link has been revoked.');}catch(error){showError('share-error',error);}
});
for(const button of document.querySelectorAll('[data-close]'))button.addEventListener('click',()=>button.closest('dialog').close());
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
window.addEventListener('online',()=>poll());
async function initialize(){
  try{
    const [identity,config]=await Promise.all([api('/api/auth/me'),api('/api/config')]);
    setIdentity(identity);state.config=config;updateAvailability();connection(true,'Connected');
    const reset=new URLSearchParams(location.hash.slice(1)).get('reset');
    if(reset){state.resetToken=reset;showIdentity('reset');}
    else if(!state.user)showIdentity();
    else{
      let id=new URL(location.href).searchParams.get('game');
      if(!id)try{id=localStorage.getItem('astra-game-'+state.user.id);}catch{}
      if(id)try{await loadGame(id);}catch(error){toast(error.message);}
    }
  }catch(error){connection(false,'Unavailable');state.availabilityError=error.message;updateAvailability();toast(error.message);}
  poll();
}
initialize();
