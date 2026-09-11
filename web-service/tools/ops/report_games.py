"""Read-only operator inventory; never load a player, engine, or credentials."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BUSY_WORKERS = {'queued', 'thinking', 'calculating', 'compacting'}


@contextmanager
def read_database(data_dir):
    path = Path(data_dir).expanduser().resolve(strict=True) / 'astra.sqlite3'
    if not path.is_file():
        raise ValueError('The source data directory must contain astra.sqlite3.')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def table_names(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _zone(name):
    if name in ('UTC', 'Etc/UTC'):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        raise ValueError('Timezone data is unavailable for ' + name +
                         '. Use UTC or install the Python tzdata package in the operator environment.') from None


def _stamp(value, zone):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, zone).isoformat(timespec='seconds')
    except (ValueError, OverflowError, OSError):
        return None


def _variant_rows(db, tables):
    result = {}
    def entry(game_id, include):
        return result.setdefault(game_id, {}).setdefault('chat' if include else 'moves',
            {'saved': False, 'building': False, 'shared': False, 'listed': False})
    # Process retired metadata first so newer variant rows take precedence.
    for table in ('replay_archives', 'replay_versions'):
        if table in tables:
            for row in db.execute('SELECT game_id,include_commentary,state FROM ' + table):
                item = entry(row['game_id'], row['include_commentary'])
                item['saved'] = row['state'] == 'ready'
                item['building'] = row['state'] == 'building'
    if 'replay_variant_jobs' in tables:
        for row in db.execute('SELECT game_id,include_commentary,state FROM replay_variant_jobs'):
            entry(row['game_id'], row['include_commentary'])['building'] = row['state'] == 'building'
    for table, listed in (('replay_unlisted', False), ('replay_publications', True), ('replay_variant_shares', None)):
        if table in tables:
            fields = 'game_id,include_commentary' + (',listed' if listed is None else '')
            for row in db.execute('SELECT ' + fields + ' FROM ' + table):
                item = entry(row['game_id'], row['include_commentary'])
                item['shared'] = True
                item['listed'] = bool(row['listed']) if listed is None else listed
    return result


def inventory(db, *, timezone_name='UTC', qa_names=(), now=None):
    zone = _zone(timezone_name)
    now = now or datetime.now(timezone.utc)
    tables = table_names(db)
    if 'games' not in tables:
        raise ValueError('This database has no game records table.')
    variants = _variant_rows(db, tables)
    explicit_qa = set(qa_names)
    rows = []
    for row in db.execute('SELECT id,state FROM games ORDER BY updated DESC,id'):
        state = json.loads(row['state'])
        moves = state.get('moves', [])
        ply = len(moves)
        status = state.get('status', 'unknown')
        worker = state.get('worker', {}).get('state', 'unknown')
        busy = (worker in BUSY_WORKERS or state.get('active_started') is not None or bool(state.get('compaction_pause')))
        color = state.get('human_side')
        outcome = None
        if status == 'finished':
            result = state.get('result')
            if result == '1/2-1/2':
                outcome = 'draw'
            elif result in ('1-0', '0-1') and color in ('white', 'black'):
                outcome = 'win' if (result == '1-0') == (color == 'white') else 'loss'
        fen = state.get('fen', '').split()
        to_move = {'w': 'white', 'b': 'black'}.get(fen[1]) if len(fen) > 1 else None
        waiting_for = None
        if status == 'active' and to_move is not None:
            waiting_for = 'human' if to_move == color else 'astra'
        replays = {name: variants.get(row['id'], {}).get(name,
                   {'saved': False, 'building': False, 'shared': False, 'listed': False}) for name in ('moves', 'chat')}
        rows.append(dict(game_id=row['id'], name=state.get('name', 'Unknown'), human_side=color,
                         classification='qa' if state.get('name') in explicit_qa else 'player',
                         status=status, result=state.get('result'), human_outcome=outcome,
                         termination=state.get('termination') or None, ply=ply,
                         last_move=f"{(ply + 1) // 2}{'.' if ply % 2 else '…'} {moves[-1].get('san', '?')}" if moves else None,
                         created_at=_stamp(state.get('created_at'), zone),
                         last_human_activity=_stamp(state.get('last_human_activity'), zone),
                         updated_at=_stamp(state.get('updated_at'), zone), worker_state=worker,
                         active_response=busy, waiting_for=waiting_for, replays=replays))
    budget = [] if 'budget' not in tables else [dict(row) for row in db.execute('SELECT day,turns,tokens,reserved FROM budget ORDER BY day')]
    today = next((row for row in budget if row['day'] == now.astimezone(timezone.utc).date().isoformat()), None)
    active = sum(row['active_response'] for row in rows)
    building = sum(item['building'] for game in variants.values() for item in game.values())
    reserved = sum(row['reserved'] for row in budget)
    player_rows = [row for row in rows if row['classification'] == 'player']
    return dict(schema_version=1, as_of=now.astimezone(timezone.utc).isoformat(timespec='seconds'), timezone=timezone_name,
                summary=dict(total_games=len(rows), player_games=len(player_rows), qa_games=len(rows) - len(player_rows),
                             finished_player_games=sum(row['status'] == 'finished' for row in player_rows),
                             unfinished_player_games=sum(row['status'] != 'finished' for row in player_rows)),
                activity=dict(active_responses=active, building_replays=building, reserved_tokens=reserved,
                              idle_snapshot=not (active or building or reserved)),
                today_budget=today, games=rows)


def report(data_dir, **options):
    with read_database(data_dir) as db:
        return inventory(db, **options)


def _cell(value):
    value = '—' if value is None else str(value)
    return html.escape(value, quote=False).replace('|', '&#124;').replace('\r', ' ').replace('\n', ' ')


def markdown(data):
    summary = data['summary']
    lines = [f"Game inventory as of {_cell(data['as_of'])} ({_cell(data['timezone'])}).", '',
             f"{summary['player_games']} player games: {summary['finished_player_games']} finished, "
             f"{summary['unfinished_player_games']} unfinished. {summary['qa_games']} games matched explicit QA names.", '',
             '| Player | Group | Side | Status | Last move | Human outcome | Last player activity | Replays |',
             '|---|---|---|---|---|---|---|---|']
    for row in data['games']:
        replay_labels = []
        for variant, value in row['replays'].items():
            flags = [name for name in ('saved', 'building', 'shared', 'listed') if value[name]]
            if flags:
                replay_labels.append(variant + ': ' + ', '.join(flags))
        values = (row['name'], row['classification'], row['human_side'], row['status'], row['last_move'],
                  row['human_outcome'], row['last_human_activity'], '; '.join(replay_labels) or None)
        lines.append('| ' + ' | '.join(_cell(value) for value in values) + ' |')
    active = data['activity']
    lines.extend(['', f"Active responses: {active['active_responses']}; replay builds: {active['building_replays']}; "
                  f"reserved tokens: {active['reserved_tokens']:,}."])
    if data['today_budget'] is not None:
        budget = data['today_budget']
        lines.append(f"UTC daily ledger ({budget['day']}): {budget['turns']} model actions; {budget['tokens']:,} tokens.")
    lines.extend(['', 'Unfinished games are saved games, not evidence that a player is currently online. '
                  'An idle snapshot does not reserve a maintenance window.'])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--timezone', default='UTC', help='IANA timezone, such as America/Chicago; UTC needs no timezone package')
    parser.add_argument('--qa-name', action='append', default=[], help='Exact known QA display name; repeat for each approved fixture name')
    format_options = parser.add_mutually_exclusive_group()
    format_options.add_argument('--json', action='store_true', help='Write JSON to stdout')
    format_options.add_argument('--markdown', action='store_true', help='Write Markdown to stdout (default)')
    parser.add_argument('--require-idle', action='store_true', help='Exit 2 when this snapshot has responses/builds/reservations; never stop anything')
    args = parser.parse_args(argv)
    try:
        data = report(args.data_dir, timezone_name=args.timezone, qa_names=args.qa_name)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, 'Unable to inventory game records: ' + str(error) + '\n')
    print(json.dumps(data, indent=2, ensure_ascii=False) if args.json else markdown(data), end='\n' if args.json else '')
    return 2 if args.require_idle and not data['activity']['idle_snapshot'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
