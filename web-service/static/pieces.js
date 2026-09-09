/* Original vector chess pieces, adapted from templates/replay.template.html. */
const drawings = {
  p: '<circle cx="22.5" cy="11" r="5"/><path d="M19 16h7l1 5c-2 5-1 9 3 13H15c4-4 5-8 3-13z"/><path d="M17 20h11M14 34h17l2 5H12z"/>',
  r: '<path d="M13 18h19l-3 5v8l4 3H12l4-3v-8z"/><path d="M11 8h6v5h4V8h4v5h4V8h5v11H11zM16 23h13M10 34h25l2 5H8z"/>',
  n: '<path d="M12 34c0-7 6-9 8-15l-7 4-5-5 8-10 1-5 6 5c10 0 14 10 11 19l-2 7z"/><path d="M25 13c6 4 7 11 3 17" fill="none"/><circle cx="19" cy="13" r="1.2" fill="currentColor" stroke="none"/><path d="M10 34h25l2 5H8z"/>',
  b: '<circle cx="22.5" cy="6" r="2"/><path d="M22.5 8C11 17 12 22 19 24l-3 8h13l-3-8c7-2 8-7-3.5-16z"/><path d="m25 12-6 8M15 32h15v3H15zM10 35h25l2 4H8z"/>',
  q: '<path d="m11 13 6 8 5.5-12 5.5 12 6-8-4 16H15zM15 29h15l3 5H12zM10 34h25l2 5H8z"/><circle cx="10.5" cy="10.5" r="2.5"/><circle cx="22.5" cy="6.5" r="2.5"/><circle cx="34.5" cy="10.5" r="2.5"/>',
  k: '<path d="M20.5 3h4v4h4v4h-4v5h-4v-5h-4V7h4z"/><path d="M16 28c-2-5-7-7-5-12 2-4 8-3 11.5 2C26 13 32 12 34 16c2 5-3 7-5 12z"/><path d="M16 28h13l4 6H12zM10 34h25l2 5H8zM22.5 18v10"/>'
};
export const pieceNames = {p:'pawn',r:'rook',n:'knight',b:'bishop',q:'queen',k:'king'};
export const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
export const squareName = i => 'abcdefgh'[i % 8] + (Math.floor(i / 8) + 1);
export const squareIndex = name => 'abcdefgh'.indexOf(name[0]) + (Number(name[1]) - 1) * 8;
export const pieceSide = p => p === p.toUpperCase() ? 'white' : 'black';
export function pieceImage(piece) {
  const kind = String(piece).toLowerCase();
  if (!drawings[kind]) return document.createTextNode('');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox','0 0 45 45');
  svg.setAttribute('aria-hidden','true');
  svg.setAttribute('focusable','false');
  svg.classList.add('piece-svg', pieceSide(piece));
  // Only the fixed, authored drawings above are inserted as markup.
  svg.innerHTML = drawings[kind];
  return svg;
}
export function boardFromFen(fen) {
  const board = Array(64).fill('.');
  String(fen).split(' ')[0].split('/').forEach((rank,row) => {
    let file = 0;
    for (const p of rank) {
      if (/^[1-8]$/.test(p)) file += Number(p);
      else { board[(7-row)*8+file] = p; file += 1; }
    }
  });
  return board;
}
export function renderCaptures(element, moves, side, humanSide='white') {
  element.replaceChildren();
  const captures = moves.filter((m,index) => {
    const mover = m.actor === 'human' ? humanSide : m.actor === 'astra' ? (humanSide === 'white' ? 'black' : 'white') : (index % 2 ? 'black' : 'white');
    return mover === side && typeof m.captured === 'string' && pieceNames[m.captured.toLowerCase()];
  }).map(m => m.captured);
  captures.sort((a,b) => 'qrbnp'.indexOf(a.toLowerCase()) - 'qrbnp'.indexOf(b.toLowerCase()));
  for (const p of captures) element.append(pieceImage(p));
  element.setAttribute('aria-label', `${side} has captured ${captures.length ? captures.map(p => pieceNames[p.toLowerCase()]).join(', ') : 'no pieces'}`);
}
export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  return s >= 3600 ? `${Math.floor(s/3600)}:${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}` : `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
}
export class BoardView {
  constructor(element, {onMove=()=>{}, onPromotion=async moves=>moves[0], onSelect=()=>{}}={}) {
    this.element=element; this.onMove=onMove; this.onPromotion=onPromotion; this.onSelect=onSelect;
    this.selected=null; this.fen=null; this.flipped=false; this.cells=new Map(); this.busy=false;
    element.setAttribute('role','group');
    element.setAttribute('aria-label','Chessboard. Use arrow keys to navigate; Enter or Space to select a square; Escape to clear.');
    for (let i=0;i<64;i++) {
      const cell=document.createElement('button');
      cell.type='button'; cell.className='square'; cell.dataset.square=squareName(i); cell.tabIndex=i===0?0:-1;
      cell.addEventListener('click',()=>this.activate(i));
      cell.addEventListener('focus',()=>{ for(const c of this.cells.values()) c.tabIndex=c===cell?0:-1; });
      cell.addEventListener('keydown',e=>this.key(e,i));
      this.cells.set(i,cell); element.append(cell);
    }
  }
  set({fen,board=boardFromFen(fen),legalMoves=[],side='white',enabled=false,lastMove=null,flipped=this.flipped}) {
    if (fen!==this.fen) this.selected=null;
    this.fen=fen; this.board=board; this.legalMoves=legalMoves; this.side=side; this.enabled=enabled; this.lastMove=lastMove; this.flipped=flipped;
    this.render();
  }
  render() {
    const targets=this.selected===null?[]:this.legalMoves.filter(m=>m.slice(0,2)===squareName(this.selected)).map(m=>m.slice(2,4));
    for (const [i,cell] of this.cells) {
      const file=i%8, rank=Math.floor(i/8), p=this.board[i]||'.', sq=squareName(i);
      const x=this.flipped?7-file:file, y=this.flipped?rank:7-rank;
      cell.style.gridColumn=x+1; cell.style.gridRow=y+1;
      cell.className='square '+((file+rank)%2?'light':'dark');
      cell.classList.toggle('selected',this.selected===i);
      cell.classList.toggle('legal',this.enabled&&targets.includes(sq));
      cell.classList.toggle('last',!!this.lastMove && [this.lastMove.slice(0,2),this.lastMove.slice(2,4)].includes(sq));
      cell.classList.toggle('occupied',p!=='.');
      cell.setAttribute('aria-pressed',String(this.selected===i));
      cell.setAttribute('aria-label',`${sq}${p!=='.'?', '+pieceSide(p)+' '+pieceNames[p.toLowerCase()]:', empty'}${targets.includes(sq)?', legal destination':''}`);
      cell.replaceChildren();
      if(p!=='.')cell.append(pieceImage(p));
      if(x===0){const label=document.createElement('span');label.className='coordinate rank';label.textContent=rank+1;cell.append(label);}
      if(y===7){const label=document.createElement('span');label.className='coordinate file';label.textContent='abcdefgh'[file];cell.append(label);}
    }
  }
  async activate(i) {
    if(!this.enabled||this.busy)return;
    const sq=squareName(i), p=this.board[i];
    if(this.selected!==null) {
      const moves=this.legalMoves.filter(m=>m.slice(0,4)===squareName(this.selected)+sq);
      if(moves.length) {
        this.busy=true;
        try { const move=moves.length>1?await this.onPromotion(moves,this.side):moves[0]; if(move)await this.onMove(move); }
        finally {this.busy=false; this.selected=null; this.render();}
        return;
      }
    }
    this.selected = this.selected===i ? null : (p!=='.'&&pieceSide(p)===this.side&&this.legalMoves.some(m=>m.slice(0,2)===sq)?i:null);
    this.render(); this.onSelect(this.selected===null?'Select one of your pieces.':`${pieceNames[p.toLowerCase()]} on ${sq} selected. Choose a highlighted square.`);
  }
  key(event,i) {
    if(event.key==='Escape'){this.selected=null;this.render();return;}
    const deltas={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,1],ArrowDown:[0,-1]};
    if(!deltas[event.key])return;
    event.preventDefault();
    const sign=this.flipped?-1:1, [dx,dy]=deltas[event.key], x=i%8+dx*sign, y=Math.floor(i/8)+dy*sign;
    if(x>=0&&x<8&&y>=0&&y<8)this.cells.get(y*8+x).focus();
  }
}
