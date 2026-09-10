"""Idle-state and preservation check for a coordinated development restart."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

data_dir = Path(__file__).resolve().parents[1] / 'var'
database = data_dir / 'astra.sqlite3'
with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
    states = [json.loads(r[0]) for r in db.execute('SELECT state FROM games ORDER BY id')]
busy = [s['id'] for s in states if s['active_started'] is not None
        or s.get('compaction_pause') or s['worker']['state'] in {'queued', 'thinking', 'calculating', 'compacting'}]
if busy:
    print(json.dumps({'idle': False, 'active_responses': len(busy)}))
    sys.exit(2)
fields = ('id', 'human_side', 'astra_side', 'fen', 'moves', 'messages', 'status',
          'result', 'thread_id', 'own_moves', 'clock_used')
payload = [{key: s.get(key) for key in fields} for s in states]
digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
checkpoint = data_dir / 'qa' / 'restart-checkpoint.json'
if '--verify' in sys.argv:
    match = json.loads(checkpoint.read_text())['sha256'] == digest
    print(json.dumps({'idle': True, 'game_state_preserved': match}))
    sys.exit(0 if match else 3)
checkpoint.parent.mkdir(parents=True, exist_ok=True)
checkpoint.write_text(json.dumps({'sha256': digest}), encoding='utf-8')
print(json.dumps({'idle': True, 'games': len(states)}))
