import {BoardView,START_FEN,renderCaptures} from './pieces.js';
const $=id=>document.getElementById(id);
const board=new BoardView($('board'));
let data,index=0,playing=false,timer;
const moveButtons=[];
const titleCase=text=>String(text||'').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
function stop(){playing=false;clearTimeout(timer);$('play').textContent=index===data.moves.length?'Replay':'Play';$('play').setAttribute('aria-label',index===data.moves.length?'Replay from the beginning':'Play replay');$('play').setAttribute('aria-pressed','false');}
function show(ply){
  index=Math.max(0,Math.min(data.moves.length,Number(ply)||0));
  const move=data.moves[index-1],fen=move?.fen||data.initial_fen||START_FEN;
  board.set({fen,flipped:board.flipped,lastMove:move?.uci});
  const bottomSide=board.flipped?'black':'white',topSide=bottomSide==='white'?'black':'white';
  const turn=fen.split(' ')[1]==='w'?'white':'black';
  for(const [location,side] of [['top',topSide],['bottom',bottomSide]]){
    const human=side===data.human_side;
    $(location+'-name').textContent=human?data.name:'Astra';
    $(location+'-detail').textContent=titleCase(side);
    $(location+'-status').textContent=index===data.moves.length?'GAME COMPLETE':turn===side?'TO MOVE':'';
    $(location+'-status').classList.toggle('active',index<data.moves.length&&turn===side);
    $(location+'-avatar').textContent=human?String(data.name||'Player').slice(0,1).toUpperCase():'A';
    $(location+'-avatar').className='avatar '+(human?'human-avatar':'astra-avatar');
    renderCaptures($(location+'-captures'),data.moves.slice(0,index),side,data.human_side);
  }
  let label=index?`${Math.ceil(index/2)}${index%2?'.':'…'} ${move.san}`:'Starting position';
  if(index===data.moves.length)label+=` · ${data.result||'Finished'} · ${titleCase(data.termination||'Game complete')}`;
  $('position-label').textContent=label;
  $('replay-slider').value=index;$('replay-slider').setAttribute('aria-valuetext',label);
  $('first').disabled=$('previous').disabled=index===0;$('next').disabled=$('last').disabled=index===data.moves.length;
  for(const [ply,button] of moveButtons){button.classList.toggle('current',ply===index);if(ply===index)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');}
  const current=moveButtons.find(([ply])=>ply===index)?.[1];
  if(current){const list=$('moves');if(current.offsetTop<list.scrollTop||current.offsetTop>list.scrollTop+list.clientHeight-30)list.scrollTop=current.offsetTop-list.offsetTop-list.clientHeight/2;}
  renderCommentary();
  if(!playing)$('play').textContent=index===data.moves.length?'Replay':'Play';
}
function renderCommentary(){
  const container=$('messages');container.replaceChildren();
  const all=data.messages||[];
  const messages=all.filter(message=>Number(message.ply)===index);
  if(!messages.length){
    const empty=document.createElement('div');empty.className='conversation-empty';
    const heading=document.createElement('p');heading.textContent=all.length?'A quiet moment.':'The moves tell the story.';
    const note=document.createElement('span');note.textContent=all.length?'No messages were recorded at this position. Step through the game to read the conversation alongside the moves.':'No commentary was included in this shared replay.';
    empty.append(heading,note);container.append(empty);
  }else{
    for(const message of messages){
      const article=document.createElement('article');article.className='message '+(['human','astra','system'].includes(message.author)?message.author:'system');
      const header=document.createElement('div');header.className='message-heading';
      const author=document.createElement('span');author.className='message-author';author.textContent=message.author==='human'?data.name:message.author==='astra'?'Astra':'Game';
      const body=document.createElement('p');body.className='message-body';body.textContent=message.text;
      header.append(author);article.append(header,body);container.append(article);
    }
  }
}
function buildMoves(){
  const list=$('moves');list.replaceChildren();
  $('move-count').textContent=`${data.moves.length} ${data.moves.length===1?'ply':'plies'}`;
  if(!data.moves.length){const note=document.createElement('p');note.className='empty-note';note.textContent='No moves were played.';list.append(note);}
  for(let i=0;i<data.moves.length;i+=2){
    const row=document.createElement('div');row.className='move-row';
    const number=document.createElement('span');number.className='move-number';number.textContent=i/2+1+'.';row.append(number);
    for(let offset=0;offset<2;offset++){
      const move=data.moves[i+offset];
      if(!move){row.append(document.createElement('span'));continue;}
      const button=document.createElement('button');button.type='button';button.className='move-token';button.textContent=move.san;
      button.setAttribute('aria-label',`Move ${i/2+1}, ${offset?'Black':'White'}, ${move.san}`);
      const ply=i+offset+1;button.addEventListener('click',()=>{stop();show(ply);});moveButtons.push([ply,button]);row.append(button);
    }list.append(row);
  }
}
function advance(){
  if(!playing)return;
  if(index>=data.moves.length){stop();return;}
  show(index+1);timer=setTimeout(advance,1800);
}
$('first').addEventListener('click',()=>{stop();show(0);});
$('previous').addEventListener('click',()=>{stop();show(index-1);});
$('next').addEventListener('click',()=>{stop();show(index+1);});
$('last').addEventListener('click',()=>{stop();show(data.moves.length);});
$('replay-slider').addEventListener('input',event=>{stop();show(event.target.value);});
$('flip-board').addEventListener('click',()=>{board.flipped=!board.flipped;show(index);});
$('play').addEventListener('click',()=>{
  if(playing){stop();return;}
  if(index===data.moves.length)show(0);
  playing=true;$('play').textContent='Pause';$('play').setAttribute('aria-label','Pause replay');$('play').setAttribute('aria-pressed','true');timer=setTimeout(advance,900);
});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&data)stop();});
async function initialize(){
  try{
    const token=location.pathname.split('/').filter(Boolean).at(-1);
    if(!token||token==='replay')throw new Error('This replay link is incomplete.');
    const response=await fetch(`/api/replays/${encodeURIComponent(token)}`,{headers:{Accept:'application/json'},credentials:'omit',cache:'no-store'});
    if(!response.ok)throw new Error(response.status===404?'The link may have been revoked, or the replay is no longer available.':'The replay could not be loaded. Please try again later.');
    data=await response.json();
    if(!Array.isArray(data.moves))throw new Error('The replay data is incomplete.');
    data.name=data.name||'Player';
    $('replay-title').textContent=`${data.name} & Astra`;
    document.title=`${data.name} vs Astra · Shared replay`;
    $('replay-result').textContent=`${data.result||'Finished'} · ${titleCase(data.termination||'Game complete')}`;
    $('replay-slider').max=data.moves.length;board.flipped=data.human_side==='black';
    $('commentary-disclosure').textContent=data.messages?.length?'The player explicitly chose to share this game’s conversation. Messages are shown at their recorded position.':'The player shared the moves. No conversation is displayed.';
    buildMoves();show(0);$('replay-content').hidden=false;
  }catch(error){$('replay-error-detail').textContent=error.message;$('replay-error').hidden=false;}
  finally{$('replay-loading').hidden=true;}
}
initialize();
