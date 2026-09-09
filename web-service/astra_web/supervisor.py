"""Bounded orchestration. Only this supervisor can spend resources or submit Astra moves."""
import asyncio
import contextlib
import json
import math
import os
from pathlib import Path
import secrets
import sys
import time
from .config import REPO_ROOT
from .store import DailyResourceLimit
from . import chess_game as game


def interruption_kind(error):
    if isinstance(error, asyncio.CancelledError):
        return 'service_interrupted'
    if isinstance(error, TimeoutError):
        return 'time_limit'
    if isinstance(error, (ConnectionError, OSError)):
        return 'connection_error'
    text = str(error).lower()
    if 'token' in text and any(word in text for word in ('limit', 'allowance', 'budget')):
        return 'token_limit'
    return 'harness_error'


class Supervisor:
    def __init__(self, config, store, identity, player_factory=None):
        self.config, self.store, self.identity = config, store, identity
        self.slots = asyncio.Semaphore(config.max_workers)
        self.tasks = {}
        self.rerun = set()
        self.stopping = False
        self.player_factory = player_factory

    @property
    def available(self):
        return self.player_factory is not None or (self.config.player_mode == 'codex' and bool(os.getenv('OPENAI_API_KEY')))

    def recover(self):
        self.store.recover_reservations()
        for state in self.store.list():
            if (state['active_started'] is not None or state.get('compaction_pause')
                    or state['worker']['state'] in ('thinking', 'queued', 'compacting', 'calculating')):
                def recover_one(s):
                    ended = time.time()
                    clock_was_active = s['active_started'] is not None
                    if clock_was_active:
                        # Persisted admission deadline bounds a crashed worker's uncertain charge.
                        elapsed = game.active_clock_elapsed(s, ended)
                        if s.get('active_deadline') is not None:
                            allocation = max(0, s['active_deadline'] - s['active_started'] - s.get('active_paused_seconds', 0))
                            elapsed = min(elapsed, allocation)
                        game.finish_compaction(s, ended, 'service_restart')
                        s.setdefault('clock_events', []).append({'started_at': s['active_started'],
                            'ended_at': ended, 'charged_seconds': elapsed,
                            'paused_seconds': s.get('active_paused_seconds', 0.0),
                            'own_moves_before_credit': s['own_moves'], 'ply': len(s['moves']),
                            'fen': s['fen'], 'outcome': 'interrupted', 'error_kind': 'service_restart'})
                        s['clock_used'] += elapsed
                        s['active_started'] = None
                    game.finish_compaction(s, ended, 'service_restart')
                    if clock_was_active or s['status'] != 'finished':
                        s['active_paused_seconds'] = 0.0
                        s['active_deadline'] = None
                    s['worker'] = {'state': 'error', 'message': (
                        'The service restarted. Your conversation is saved; retry when ready.'
                        if s['status'] == 'finished' else
                        'The service restarted. Your game is saved; resume when ready.')}
                self.store.mutate(state['id'], recover_one, kind='restart_recovery')
        self.suspend_inactive()

    def refund_retry_clock(self, state, db, request_id=None):
        """Apply only a human-requested retry refund, within Store.mutate's lock.

        Legacy clock intervals require a matching failed worker event sequence.
        Missing or ambiguous evidence never causes a guessed refund.
        """
        if (state['status'] != 'active' or state['active_started'] is not None
                or state['worker']['state'] not in {'error', 'disabled'}
                or game.side_to_move(state) != state['astra_side']):
            return
        ply = len(state['moves'])
        blocks, current = [], None
        rows = db.execute("SELECT id,at,kind,data FROM events WHERE game_id=? AND kind IN "
                          "('worker_started','clock_settled','worker_error','worker_completed','astra_action','restart_recovery','operator_clock_set') ORDER BY id",
                          (state['id'],)).fetchall()
        for row in rows:
            if row['kind'] == 'operator_clock_set':
                # An explicit operator baseline supersedes every earlier charge.
                blocks.clear()
                current = None
                continue
            try:
                data = json.loads(row['data'])
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            if row['kind'] == 'worker_started':
                if current is not None:
                    blocks.append(current)
                current = {'start': row, 'data': data, 'settled': [], 'failed': False, 'completed': False} if data.get('ply') == ply else None
            elif current is not None:
                if row['kind'] in {'clock_settled', 'restart_recovery'} and data.get('ply') == ply:
                    detail = data.get('request') or {}
                    current['settled'].append(row)
                    if row['kind'] == 'restart_recovery' or isinstance(detail, dict) and detail.get('outcome') == 'interrupted':
                        current['failed'] = True
                elif row['kind'] == 'worker_error' and data.get('ply', ply) == ply:
                    current['failed'] = True
                elif row['kind'] == 'worker_completed':
                    current['completed'] = True
                elif (row['kind'] == 'astra_action' and isinstance(data.get('request'), dict)
                      and data['request'].get('action') in {'move', 'resign', 'accept_draw', 'claim_draw'}):
                    current['completed'] = True
        if current is not None:
            blocks.append(current)

        eligible, used_indices = [], set()
        for block in blocks:
            if not block['failed'] or block['completed'] or len(block['settled']) != 1:
                continue
            started, settled = block['start'], block['settled'][0]
            start_detail = block['data'].get('request') or {}
            if isinstance(start_detail, dict) and start_detail.get('fen', state['fen']) != state['fen']:
                continue
            matches = []
            for index, event in enumerate(state.get('clock_events', [])):
                if (not isinstance(event, dict) or index in used_indices or event.get('refund_id')
                        or event.get('refunded_seconds') is not None
                        or event.get('own_moves_before_credit') != state['own_moves']
                        or event.get('ply', ply) != ply or event.get('fen', state['fen']) != state['fen']
                        or event.get('outcome', 'interrupted') != 'interrupted'):
                    continue
                values = [event.get(key) for key in ('started_at', 'ended_at', 'charged_seconds')]
                if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
                    continue
                begin, end, charged = values
                if (charged > 0 and charged <= end - begin + 0.000001
                        and begin <= started['at'] <= end <= settled['at']):
                    matches.append((index, event))
            if len(matches) == 1:
                index, event = matches[0]
                used_indices.add(index)
                eligible.append({'clock_event_index': index, 'started_event_id': started['id'],
                    'settled_event_id': settled['id'], 'seconds': event['charged_seconds'],
                    'error_kind': event.get('error_kind') or 'legacy_harness_interruption'})
        amount = sum(item['seconds'] for item in eligible)
        before = state['clock_used']
        if not amount or not math.isfinite(before) or amount > before + 0.000001:
            return
        stamp, refund_id = time.time(), secrets.token_hex(12)
        state['clock_used'] = max(0.0, before - amount)
        refund = {'id': refund_id, 'at': stamp, 'reason': 'human_requested_retry_after_interruption',
                  'request_id': request_id, 'ply': ply, 'fen': state['fen'], 'seconds': amount,
                  'clock_used_before': before, 'clock_used_after': state['clock_used'], 'attempts': eligible}
        for item in eligible:
            state['clock_events'][item['clock_event_index']].update(refund_id=refund_id,
                refunded_at=stamp, refunded_seconds=item['seconds'])
        state.setdefault('clock_refunds', []).append(refund)
        self.store._event(db, state['id'], 'retry_clock_refund', refund)

    def suspend_inactive(self):
        cutoff = time.time() - self.config.suspend_hours * 3600
        for state in self.store.list():
            if state['status'] == 'active' and state['last_human_activity'] < cutoff and state['id'] not in self.tasks:
                self.store.mutate(state['id'], lambda s: s.update(status='suspended', worker={'state': 'idle', 'message': 'Game saved. Resume whenever you are ready.'}), kind='suspended')

    def schedule(self, game_id):
        if self.stopping:
            return
        if game_id in self.tasks:
            self.rerun.add(game_id)
            return
        state = self.store.get(game_id)
        if state['status'] not in {'active', 'finished'}:
            return
        if not self.available:
            self.store.mutate(game_id, lambda s: s.update(worker={'state': 'disabled', 'message': 'Astra is waiting for the operator to configure the model connection. Your game is saved.'}), kind='worker_unavailable')
            return
        if len(self.tasks) >= 16:
            self.store.mutate(game_id, lambda s: s.update(worker={'state': 'error', 'message': 'All waiting places are occupied. Your game is saved; retry shortly.'}), kind='queue_full')
            return
        self.store.mutate(game_id, lambda s: s.update(worker={'state': 'queued', 'message': 'Waiting for Astra’s next available place.'}), kind='queued')
        self.tasks[game_id] = asyncio.create_task(self._run(game_id))

    async def close(self):
        self.stopping = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel(self, game_id):
        self.rerun.discard(game_id)
        task = self.tasks.get(game_id)
        if task:
            task.cancel()
            try:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            finally:
                # A task cancelled before its coroutine starts never reaches
                # _run's finally block. Do not remove a newer queued response.
                if self.tasks.get(game_id) is task:
                    self.tasks.pop(game_id, None)
                    if game_id in self.rerun and not self.stopping:
                        self.rerun.discard(game_id)
                        self.schedule(game_id)
                if game_id not in self.tasks:
                    state = self.store.get(game_id)
                    if state['status'] == 'finished' and state['worker']['state'] == 'queued':
                        self.store.mutate(game_id, lambda s: s.update(worker={'state': 'idle', 'message': ''}),
                            kind='worker_cancelled')

    async def _run(self, game_id):
        try:
            async with self.slots:
                await self._active_run(game_id)
        except asyncio.CancelledError:
            raise
        except DailyResourceLimit:
            # Admission spent nothing. Do not automatically retry the same denial.
            self.rerun.discard(game_id)
            self.store.mutate(game_id, lambda s: s.update(worker={'state': 'error',
                'error_code': DailyResourceLimit.code, 'message': DailyResourceLimit.public_message}),
                kind='worker_admission_denied', body={'error_code': DailyResourceLimit.code})
        except Exception as error:
            # Internal error text belongs in operator evidence, not a player-facing traceback.
            self.store.audit(game_id, 'worker_error', {'type': type(error).__name__, 'message': str(error)[:1000]})
            self.store.mutate(game_id, lambda s: s.update(worker={'state': 'error', 'message': 'Astra’s response was interrupted. Your game and conversation are saved; you can retry.'}), kind='worker_error')
        finally:
            self.tasks.pop(game_id, None)
            if game_id in self.rerun and not self.stopping:
                self.rerun.discard(game_id)
                self.schedule(game_id)

    async def _active_run(self, game_id):
        state = self.store.get(game_id)
        if state['status'] not in {'active', 'finished'}:
            return
        post_game = state['status'] == 'finished'
        if not post_game and state['engine_fingerprint'] != game.fingerprint():
            raise ValueError('Engine revision changed; restore the recorded revision before continuing this game.')
        own_turn = not post_game and game.side_to_move(state) == state['astra_side']
        balance = game.clock(state)['remaining_seconds']
        if own_turn and balance <= 0:
            self.store.mutate(game_id, lambda s: s.update(worker={'state': 'error', 'message': 'Astra’s earned thinking allowance is exhausted. The game remains saved.'}), kind='clock_exhausted')
            return
        reservation = self.store.reserve()
        started = time.monotonic()
        wall_started = time.time()
        own_moves = state['own_moves']
        horizon = max(1, 40 - own_moves) if own_moves < 40 else max(12, 60 - own_moves)
        if own_turn:
            allocation = min(self.config.ordinary_seconds, balance, balance / horizon)
        else:
            allocation = self.config.ordinary_seconds if post_game else min(60, self.config.ordinary_seconds)
        critical_allocation = min(self.config.critical_seconds, balance, 2 * balance / horizon) if own_turn else allocation
        control = {'deadline': started + allocation, 'queries': 0, 'candidate': False, 'root_query': False,
                   'chosen': False, 'tokens': None, 'usage_complete': False, 'public_messages': 0, 'ply': len(state['moves']),
                   'stopped_clock': False, 'query_paths': [], 'attempt_id': secrets.token_hex(12), 'error_kind': None,
                   'allocation': allocation, 'paused_seconds': 0.0, 'pause': None, 'pause_items': set()}
        def thinking_worker(s):
            return {'state': 'thinking', 'message': (
                'Astra is considering your message.' if s['status'] == 'finished'
                else 'Astra is considering the position.')}

        def begin(s):
            s['worker'] = thinking_worker(s)
            if not post_game:
                s['compaction_pause'] = None
                s['active_paused_seconds'] = 0.0
            if own_turn:
                s['active_started'] = wall_started
                s['active_deadline'] = wall_started + allocation
        self.store.mutate(game_id, begin, kind='worker_started', body={'attempt_id': control['attempt_id'],
            'ply': control['ply'], 'fen': state['fen'], 'own_turn': own_turn})

        def stop_clock(s, outcome=None):
            if own_turn and s['active_started'] is not None:
                ended = time.time()
                charged = game.active_clock_elapsed(s, ended)
                remaining = game.clock(s)['remaining_seconds']
                game.finish_compaction(s, ended, 'interrupted')
                s.setdefault('clock_events', []).append({'started_at': s['active_started'], 'ended_at': ended,
                    'charged_seconds': charged, 'own_moves_before_credit': s['own_moves'],
                    'paused_seconds': s.get('active_paused_seconds', 0.0),
                    'remaining_before_credit': remaining, 'attempt_id': control['attempt_id'],
                    'ply': control['ply'], 'fen': state['fen'], 'outcome': outcome or ('interrupted' if control['error_kind'] else 'completed'),
                    'error_kind': control['error_kind']})
                s['clock_used'] += charged
                s['active_started'] = None
                s['active_deadline'] = None
                s['active_paused_seconds'] = 0.0
                control['stopped_clock'] = True

        def remaining_turn():
            now = control['pause']['monotonic'] if control['pause'] else time.monotonic()
            return max(0.0, control['deadline'] - now)

        async def tool(name, args):
            if not isinstance(args, dict):
                raise ValueError('Tool arguments must be an object.')
            if name == '_thread':
                thread_id = str(args['thread_id'])
                if len(thread_id) > 150:
                    raise ValueError('Invalid thread identifier')
                self.store.mutate(game_id, lambda s: s.update(thread_id=thread_id), kind='thread_saved', increment=False)
                return {}
            if name == '_usage':
                control['tokens'] = max(control['tokens'] or 0, int(args['tokens']))
                if control['tokens'] > self.config.max_turn_tokens:
                    raise ValueError('Response token allowance reached')
                return {}
            if name == '_compaction':
                phase, item_id = args.get('phase'), args.get('item_id')
                if (set(args) != {'phase', 'item_id'} or phase not in {'started', 'completed'}
                        or not isinstance(item_id, str) or not 1 <= len(item_id) <= 200):
                    raise ValueError('Invalid compaction lifecycle event.')
                pause = control['pause']
                if phase == 'started':
                    if item_id in control['pause_items']:
                        return {}
                    if pause:
                        raise ValueError('Overlapping compaction intervals are unsupported.')
                    if remaining_turn() <= 0:
                        raise ValueError('The response allowance is exhausted.')
                    stamp, monotonic = time.time(), time.monotonic()
                    def pause_clock(s):
                        s['compaction_pause'] = {'item_id': item_id, 'attempt_id': control['attempt_id'],
                            'started_at': stamp, 'clock_paused': s['active_started'] is not None}
                        s['worker'] = {'state': 'compacting', 'message': 'Astra is preparing conversation context.'}
                    self.store.mutate(game_id, pause_clock, kind='compaction_started', body=args)
                    control['pause_items'].add(item_id)
                    control['pause'] = {'item_id': item_id, 'monotonic': monotonic}
                elif pause and pause['item_id'] == item_id:
                    duration = max(0.0, time.monotonic() - pause['monotonic'])
                    stamp = time.time()
                    def resume_clock(s):
                        before = s.get('active_paused_seconds', 0.0)
                        game.finish_compaction(s, stamp, 'completed')
                        if s.get('active_deadline') is not None:
                            s['active_deadline'] += s.get('active_paused_seconds', 0.0) - before
                        if s['worker']['state'] == 'compacting':
                            s['worker'] = thinking_worker(s)
                    self.store.mutate(game_id, resume_clock, kind='compaction_completed',
                        body=dict(args, paused_seconds=duration))
                    control['paused_seconds'] += duration
                    control['deadline'] += duration
                    control['pause'] = None
                else:
                    # Never infer missing start time or refund retrospectively.
                    control['pause_items'].add(item_id)
                return {}
            current = self.store.get(game_id)
            if current['status'] == 'finished' and name not in {'chess_status', 'chess_query_details', 'chess_comment'}:
                raise ValueError('The game is finished. You may discuss it and inspect saved queries; further chess actions are unavailable.')
            if current['status'] not in {'active', 'finished'} and name != 'chess_comment':
                raise ValueError('The game is no longer active.')
            if remaining_turn() <= 0:
                raise ValueError('The response allowance is exhausted.')
            if name == 'chess_status':
                result = game.model_snapshot(current)
                result['remaining_turn_seconds'] = remaining_turn()
                result['memory'] = self.identity.memory_for_user(current['user_id'])
                result['current_attempt'] = {'candidate_recorded': control['candidate'],
                    'root_query_completed': control['root_query'], 'move_accepted': control['chosen']}
                return result
            if control['pause']:
                raise ValueError('Chess actions are unavailable during context compaction.')
            if name == 'chess_query_details':
                if set(args) - {'query_index', 'candidate_rank'}:
                    raise ValueError('Use a saved query index and optional candidate rank.')
                index = args.get('query_index')
                if type(index) is not int or not 0 <= index < len(current['queries']):
                    raise ValueError('Unknown saved query index.')
                folder = (self.config.data_dir / 'games' / game_id / 'queries').resolve()
                path = (self.config.data_dir / current['queries'][index]['path']).resolve()
                if not path.is_relative_to(folder) or path.stat().st_size > 2_000_000:
                    raise ValueError('Invalid saved query evidence.')
                details = json.loads(path.read_text(encoding='utf-8'))
                rank = args.get('candidate_rank')
                if rank is not None:
                    if type(rank) is not int or not 1 <= rank <= len(details.get('candidates', [])):
                        raise ValueError('Unknown candidate rank.')
                    return {'query_index': index, 'start_fen': details['start_fen'],
                            'candidate': details['candidates'][rank - 1]}
                return details
            if name == 'chess_comment':
                if set(args) != {'text'}:
                    raise ValueError('Expected text only')
                await emit(args['text'])
                return {'sent': True}
            if len(current['moves']) != control['ply']:
                raise ValueError('The actual board changed. End this response; a fresh turn is queued.')
            if name == 'chess_critical':
                if not own_turn or set(args) != {'reason'} or not 1 <= len(str(args['reason'])) <= 1000:
                    raise ValueError('A concrete critical-position reason is required.')
                control['allocation'] = critical_allocation
                control['deadline'] = started + critical_allocation + control['paused_seconds']
                self.store.mutate(game_id, lambda s: s.update(active_deadline=wall_started + critical_allocation
                    + s.get('active_paused_seconds', 0.0)), kind='critical', body=args, increment=False)
                return {'remaining_turn_seconds': remaining_turn()}
            if name == 'chess_candidate':
                if set(args) != {'move', 'concern'} or not 1 <= len(str(args['concern'])) <= 2000:
                    raise ValueError('Record a legal candidate and a concrete concern.')
                game.position(current).parse_uci(args['move'])
                self.store.mutate(game_id, lambda s: s['candidates'].append(dict(ply=control['ply'], **args)), kind='candidate', body=args, increment=False)
                control['candidate'] = True
                return {'recorded': True}
            if name == 'chess_query':
                if control['chosen']:
                    raise ValueError('The move is already submitted.')
                if not control['candidate']:
                    raise ValueError('Record an independent candidate and concern before searching.')
                if control['queries'] >= self.config.max_queries:
                    raise ValueError('This turn has reached its query limit.')
                control['queries'] += 1
                # A fixed forty-second reserve would make searches impossible
                # once the rolling allocation shrinks below forty seconds.
                reserve = min(40, control['allocation'] / 3)
                available = remaining_turn() - reserve
                if available < 0.2:
                    raise ValueError('Use the remaining time to review and choose your move.')
                self.store.mutate(game_id, lambda s: s.update(worker={
                    'state': 'calculating', 'message': 'Astra’s tactical engine is calculating.'}),
                    kind='calculation_started', body={'attempt_id': control['attempt_id']})
                completed = False
                try:
                    result, path = await self._query(game_id, current, args, available)
                    completed = True
                finally:
                    def calculation_ended(s):
                        # Never overwrite a newer lifecycle state while a query
                        # is being cancelled or the human ends the game.
                        if s['worker']['state'] == 'calculating':
                            s['worker'] = ({'state': 'thinking', 'message': 'Astra is considering the position.'}
                                if s['status'] == 'active' else {'state': 'idle', 'message': ''})
                    self.store.mutate(game_id, calculation_ended, kind='calculation_ended',
                        body={'attempt_id': control['attempt_id'], 'completed': completed})
                control['query_paths'].append(path)
                if not args.get('after') and not result.get('fallback', False):
                    control['root_query'] = True
                self.store.mutate(game_id, lambda s: s['queries'].append({'ply': control['ply'], 'path': path}), kind='query_completed', increment=False)
                from .engine_view import compact_result
                view = compact_result(result)
                view['query_index'] = len(current['queries'])
                return view
            if name == 'chess_choose':
                if set(args) - {'action', 'move', 'note'} or not isinstance(args.get('note'), str) or not 1 <= len(args['note']) <= 2000:
                    raise ValueError('Supply action, optional move and a concise decision note.')
                action = args.get('action')
                if action == 'move' and (not own_turn or not control['candidate'] or not control['root_query']):
                    raise ValueError('A move requires your turn, an independent candidate and a completed current-position query.')
                if control['chosen']:
                    raise ValueError('An action has already completed this turn.')
                def choose(s):
                    if len(s['moves']) != control['ply'] or s['status'] != 'active':
                        raise ValueError('The actual game has changed.')
                    if action == 'move':
                        stop_clock(s, 'accepted_action')
                        game.apply_move(s, args['move'], 'astra')
                    elif action == 'resign':
                        stop_clock(s, 'accepted_action')
                        game.finish(s, '1-0' if s['human_side'] == 'white' else '0-1', 'resignation')
                    elif action == 'claim_draw':
                        if not own_turn or not game.claimable(s, args.get('move')):
                            raise ValueError('No valid draw claim.')
                        stop_clock(s, 'accepted_action')
                        game.finish(s, '1/2-1/2', 'draw_claim')
                    elif action == 'offer_draw':
                        s['draw_offer'] = 'astra'
                    elif action == 'accept_draw':
                        if s['draw_offer'] != 'human':
                            raise ValueError('There is no opponent draw offer.')
                        stop_clock(s, 'accepted_action')
                        game.finish(s, '1/2-1/2', 'agreement')
                    elif action == 'decline_draw':
                        if s['draw_offer'] != 'human':
                            raise ValueError('There is no opponent draw offer.')
                        s['draw_offer'] = None
                    else:
                        raise ValueError('Unsupported chess action.')
                    s['decisions'].append(dict(ply=control['ply'], **args))
                self.store.mutate(game_id, choose, kind='astra_action', body=args)
                control['chosen'] = action in {'move', 'resign', 'accept_draw', 'claim_draw'}
                return {'accepted': True, 'game': game.model_snapshot(self.store.get(game_id))}
            raise ValueError('Unknown tool. Only the chess service tools are available.')

        async def emit(text):
            if not isinstance(text, str) or not text.strip():
                return
            if control['public_messages'] >= 8:
                raise ValueError('Public commentary allowance reached.')
            control['public_messages'] += 1
            self.store.mutate(game_id, lambda s: game.message(s, 'astra', text), kind='astra_commentary')

        player = None
        try:
            if self.player_factory:
                player = self.player_factory(self.config)
            else:
                from .codex_bridge import CodexPlayer
                player = CodexPlayer(self.config)
            snapshot = game.model_snapshot(self.store.get(game_id))
            snapshot['memory'] = self.identity.memory_for_user(state['user_id'])
            snapshot['remaining_turn_seconds'] = allocation
            run = asyncio.create_task(player.run(game_id, snapshot, tool, emit, thread_id=state['thread_id']))
            try:
                while not run.done():
                    if remaining_turn() <= 0:
                        raise TimeoutError('Astra response deadline reached')
                    await asyncio.wait({run}, timeout=min(0.25, max(.01, remaining_turn())))
                result = await run
                if result and result.get('usage_tokens') is not None:
                    control['tokens'] = result['usage_tokens']
                    control['usage_complete'] = True
                latest = self.store.get(game_id)
                if own_turn and not control['chosen'] and latest['status'] == 'active' and len(latest['moves']) == control['ply']:
                    raise ValueError('The player finished without submitting a move.')
                self.store.mutate(game_id, lambda s: s.update(worker={'state': 'idle', 'message': ''}), kind='worker_completed')
            finally:
                if not run.done():
                    run.cancel()
                with contextlib.suppress(BaseException):
                    await run
        except BaseException as error:
            control['error_kind'] = interruption_kind(error)
            raise
        finally:
            try:
                if player:
                    await player.close()
            except BaseException as error:
                control['error_kind'] = control['error_kind'] or interruption_kind(error)
                raise
            finally:
                def settle(s):
                    stop_clock(s)
                    game.finish_compaction(s, time.time(), 'interrupted')
                    if s['worker']['state'] in {'thinking', 'compacting', 'calculating'}:
                        if (not post_game and s['status'] == 'finished'
                                and control['error_kind'] == 'service_interrupted'):
                            # A human ending the game intentionally cancels play.
                            # A later conversation failure remains retryable.
                            s['worker'] = {'state': 'idle', 'message': ''}
                        else:
                            s['worker'] = {'state': 'error', 'message': 'Astra’s response stopped. Your game and conversation are saved; retry when ready.'}
                try:
                    self.store.mutate(game_id, settle, kind='response_settled' if post_game else 'clock_settled', body={'elapsed': time.monotonic()-started,
                        'tokens': control['tokens'], 'attempt_id': control['attempt_id'], 'ply': control['ply'],
                        'outcome': 'accepted_action' if control['chosen'] else 'interrupted' if control['error_kind'] else 'completed',
                        'error_kind': control['error_kind']})
                finally:
                    charge = control['tokens'] if control['usage_complete'] else max(reservation[1], control['tokens'] or 0)
                    self.store.settle(reservation, charge)

    async def _query(self, game_id, state, args, available):
        allowed = {'seconds', 'depth', 'candidates', 'after', 'root_moves', 'goal', 'proof_only'}
        if set(args) - allowed:
            raise ValueError('Unsupported query fields; position and history are supplied by the server.')
        seconds = args.get('seconds', 15)
        depth = args.get('depth', 8)
        candidates = args.get('candidates', 3)
        if isinstance(seconds, bool) or not isinstance(seconds, (int,float)) or not 0 < seconds <= 180:
            raise ValueError('Query seconds must be greater than zero and at most 180.')
        if type(depth) is not int or not 1 <= depth <= 32 or type(candidates) is not int or not 1 <= candidates <= 10:
            raise ValueError('Depth must be 1–32; candidates must be 1–10.')
        after = args.get('after', [])
        if not isinstance(after, list) or len(after) > 12:
            raise ValueError('Hypothetical continuations must contain at most 12 moves.')
        request = dict(args, mode='probe' if args.get('goal') else 'analyze', fen=state['fen'],
                       history_fens=game.history(state), seconds=min(seconds, available), depth=depth,
                       candidates=candidates, diagnostics=True)
        request.setdefault('proof_only', True) if args.get('goal') else None
        from astra_chess import prepare
        prepare(request)
        folder = self.config.data_dir / 'games' / game_id / 'queries'
        folder.mkdir(parents=True, exist_ok=True)
        query_id = f'{len(state["moves"]):04d}-{secrets.token_hex(6)}'
        req_path, out_path = folder / f'{query_id}.request.json', folder / f'{query_id}.result.json'
        req_path.write_text(json.dumps(request, indent=2), encoding='utf-8')
        env = {k:v for k,v in os.environ.items() if k in {'SystemRoot','WINDIR','TEMP','TMP','PATH','LANG'}}
        proc = await asyncio.create_subprocess_exec(sys.executable, '-s', str(REPO_ROOT / 'astra_chess.py'),
            'query', '--request', str(req_path), '--output', str(out_path), cwd=REPO_ROOT,
            env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=request['seconds'] + 3)
            if proc.returncode:
                raise ValueError('Engine query failed: ' + err.decode('utf-8', 'replace')[-500:])
            if out_path.stat().st_size > 2_000_000:
                raise ValueError('Engine result exceeds size limit')
            result = json.loads(out_path.read_text(encoding='utf-8'))
            if result['engine']['source_sha256'] != state['engine_fingerprint']:
                raise ValueError('Engine source fingerprint mismatch')
            return result, str(out_path.relative_to(self.config.data_dir))
        except BaseException as exc:
            self.store.audit(game_id, 'query_failed', {'request': str(req_path.relative_to(self.config.data_dir)), 'error': type(exc).__name__})
            raise
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
