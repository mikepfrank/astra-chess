"""Manual game journal and evidence recorder. Never controls a browser or chooses a move."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace
from astra_chess import write_json, run_query, session_status
from astra_engine.rules import Position, START_FEN, square_name

ROOT=Path(__file__).resolve().parent
GAME=ROOT/'engine-games'/'wally-2026-09-07'

def now(): return datetime.now(timezone.utc).isoformat()
def load(): return json.loads((GAME/'game.json').read_text())
def save(g): write_json(GAME/'game.json',g)
def position(g): return Position.from_fen(g['fens'][-1])
def add(g,move):
    p=position(g); m=p.parse_uci(move)
    g['san'].append(p.san(m));g['uci'].append(m.uci());g['fens'].append(p.play(m).fen())
def accept_pending(g, submitted=None):
    if g.get('pending'):
        add(g,g['pending']['uci'])
        if submitted:
            g['turns'][-1]['submitted_utc']=submitted
            g['turns'][-1]['seconds_to_submit']=(datetime.fromisoformat(submitted.replace('Z','+00:00'))-datetime.fromisoformat(g['turns'][-1]['observed_utc'].replace('Z','+00:00'))).total_seconds()
        g['pending']=None
def make_query(g,args,default=False):
    p=position(g);turn=g['turns'][-1]
    number=turn['move']; n=len(turn['queries'])+1
    query={'label':f'Wally game 8, move {number}: '+(args.label or turn['concern']),
           'mode':'probe' if args.goal else 'analyze','fen':p.fen(),'history_fens':g['fens'][:-1],
           'depth':args.depth,'seconds':args.seconds,'candidates':args.candidates}
    if args.after:query['after']=args.after.split(',')
    if args.root_moves:query['root_moves']=args.root_moves.split(',')
    if args.goal:query['goal']=json.loads(args.goal)
    stem=GAME/f'turn-{number:02d}-query-{n}'
    request=stem.with_suffix('.request.json');output=stem.with_suffix('.json')
    write_json(request,query)
    run_query(SimpleNamespace(request=request,output=output,html=None,session=GAME/'clock.json'))
    turn['queries'].append(str(output.relative_to(ROOT)));save(g)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['init','turn','query','choose','status','finish'])
    ap.add_argument('--opponent');ap.add_argument('--initial');ap.add_argument('--concern',default='')
    ap.add_argument('--observed-utc');ap.add_argument('--submitted-utc');ap.add_argument('--move');ap.add_argument('--note',default='')
    ap.add_argument('--label',default='');ap.add_argument('--seconds',type=float,default=3);ap.add_argument('--depth',type=int,default=5)
    ap.add_argument('--candidates',type=int,default=3);ap.add_argument('--root-moves');ap.add_argument('--after');ap.add_argument('--goal')
    ap.add_argument('--result');ap.add_argument('--termination',default='normal');ap.add_argument('--png',action='store_true')
    a=ap.parse_args();GAME.mkdir(parents=True,exist_ok=True)
    if a.command=='init':
        if (GAME/'game.json').exists():raise ValueError('Game already exists')
        save({'event':'Astra Search Lab trial','date':'2026.09.07','round':8,'white':'Astra (Ultra)','black':'Wally','black_elo':1800,'result':'*','uci':[],'san':[],'fens':[START_FEN],'turns':[],'pending':None})
        print('Journal initialized');return
    g=load()
    if a.command=='turn':
        accept_pending(g,a.submitted_utc)
        if a.opponent:
            p=position(g); found=[m for m in p.legal_moves() if p.san(m).rstrip('+#')==a.opponent.rstrip('+#')]
            if len(found)!=1:raise ValueError('Observed SAN must identify exactly one legal move: '+a.opponent)
            add(g,found[0].uci())
        p=position(g)
        if p.turn!=0:raise ValueError('Expected White to move')
        if not a.initial:raise ValueError('Record initial candidate before searching')
        p.parse_uci(a.initial)
        observed=a.observed_utc or now()
        age=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(observed.replace('Z','+00:00'))).total_seconds())
        write_json(GAME/'clock.json',{'started_monotonic':time.monotonic()-age,'started_utc':observed,'turn_seconds':60,'engine_seconds':12,'reserve_seconds':8,'engine_seconds_used':0.0,'calls':0})
        g['turns'].append({'move':p.fullmove,'observed_utc':observed,'initial_candidate':a.initial,'concern':a.concern,'queries':[]})
        save(g);print(p.ascii());make_query(g,a)
    elif a.command=='query':make_query(g,a)
    elif a.command=='choose':
        p=position(g);m=p.parse_uci(a.move);status=session_status(json.loads((GAME/'clock.json').read_text()))
        g['pending']={'uci':m.uci(),'san':p.san(m)}
        g['turns'][-1].update(selected_move=m.uci(),selected_san=p.san(m),assessment=a.note,changed_candidate=m.uci()!=g['turns'][-1]['initial_candidate'],decision_clock=status)
        save(g);child=p.play(m);print(p.san(m));print(child.ascii());print(json.dumps(status))
        if a.png:
            from board_scratchpad import render
            render({'board':{square_name(i):pc for i,pc in enumerate(child.board) if pc!='.'},'last_edits':[m.uci()]},GAME/'candidate.png',f'{p.fullmove}. {p.san(m)} — candidate')
    elif a.command=='status':
        print(position(g).ascii());print(json.dumps(session_status(json.loads((GAME/'clock.json').read_text()))))
    elif a.command=='finish':
        accept_pending(g,a.submitted_utc)
        if a.result not in ('1-0','0-1','1/2-1/2'):raise ValueError('Final result required')
        g['result']=a.result;g['termination']=a.termination;save(g)
        header={'Event':g['event'],'Site':'https://www.chess.com/','Date':g['date'],'Round':'8','White':g['white'],'Black':'Wally','BlackElo':'1800','Result':a.result,'Termination':a.termination,'TimeControl':'-'}
        pgn='\n'.join(f'[{key} "{value}"]' for key,value in header.items())+'\n\n'
        for i,san in enumerate(g['san']):pgn+=(f'{i//2+1}. ' if i%2==0 else '')+san+' '
        pgn+=a.result+'\n';(GAME/'astra-vs-wally-engine-2026-09-07.pgn').write_text(pgn,encoding='utf-8');print(pgn)

if __name__=='__main__':main()
