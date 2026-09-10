"""Manual read-only display fixtures, no model, credentials or live database."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from astra_web import chess_game as game
from astra_web.config import Config, APP_ROOT
import uvicorn

app = FastAPI()
app.mount('/static', StaticFiles(directory=APP_ROOT / 'static'), name='static')

@app.get('/')
def index():
    html=(APP_ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
    for name in ('app.js','style.css'):
        stamp=(APP_ROOT / 'static' / name).stat().st_mtime_ns
        html=html.replace('/static/'+name, '/static/'+name+'?fixture='+str(stamp))
    return HTMLResponse(html, headers={'Cache-Control':'no-store'})

@app.get('/api/auth/me')
def me():
    return {'user': {'id':'evaluation-qa', 'name':'Display fixture', 'has_password':False}, 'csrf_token':'not-a-live-session'}

@app.get('/api/config')
def config():
    return {'player_available':True, 'player_mode':'test', 'model':'display-fixture', 'reasoning':'none', 'suspend_hours':36}

@app.get('/api/games/{name}')
def fixture(name):
    human_side='black' if name.endswith('-white') else 'white'
    s=game.new_game({'id':'evaluation-qa','name':'Display fixture'}, human_side, Config())
    s['id']=name
    if name == 'checkmate':
        line=['f2f3','e7e5','g2g4','d8h4']
    elif name == 'initial':
        line=[]
    else:
        line=['e2e4','e7e5','g1f3','b8c6']
        if name == 'human-reply':
            line += ['f1b5']
    if name.startswith(('compacting-', 'thinking-', 'calculating-')):
        line=['e2e4','e7e5'] if human_side=='black' else ['e2e4','e7e5','g1f3']
    for i,uci in enumerate(line):
        game.apply_move(s, uci, 'human' if game.side_to_move(s)==human_side else 'astra')
    v=game.snapshot(s)
    if name.startswith(('compacting-', 'thinking-', 'calculating-')):
        compacting=name.startswith('compacting-')
        v['worker']={'state':name.split('-')[0],'message':'Display fixture'}
        v['clock'].update(remaining_seconds=5100 if compacting else 5100-int(time.time())%30,
                          paused=compacting,pause_reason='compaction' if compacting else None)
    v['last_astra_evaluation']={'score_pawns':-0.12,'mate_in_moves':None,'mate_for':None,'ply':3,'uci':'b8c6','san':'Nc6','completed_depth':5}
    if name in ('mate','losing-mate','mate-proof'):
        v['last_astra_evaluation'].update(score_pawns=None,mate_in_moves=3,mate_for='astra' if name=='mate' else 'opponent')
    if name == 'mate-proof':
        v['last_astra_evaluation'].update(mate_for='astra',source='goal_probe',completed_depth=6)
    if name in ('initial','missing'):
        v['last_astra_evaluation']=None
    return v

if __name__ == '__main__':
    uvicorn.run(app,host='127.0.0.1',port=8790,access_log=False)
