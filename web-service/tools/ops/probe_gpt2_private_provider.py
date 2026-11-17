#!/usr/bin/env python3
"""One isolated, bounded provider action; default is read-only preparation.

Run as gpt-2 through the production-style /bin/bash -lc login shell, with the
reviewed EnvironmentFile supplied by a transient systemd unit. The environment
file supplies app settings; the login profile supplies OPENAI_API_KEY. Copying
only EnvironmentFile and executing Python directly omits that credential.
Keep the real private service STOPPED. The test owns bridge port 8902
temporarily, uses a separate $1 development ledger, and creates one fresh
synthetic agent directory. It never opens the live chat/budget databases with
SQLite or changes real sessions. Private artifacts remain on-host for audit.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid

SOURCE = Path('/home/gpt-2/GPT-2-codex/src')
DATA = Path('/home/gpt-2/.local/share/gpt2-codex')
EVIDENCE = Path('/home/gpt-2/.local/share/gpt2-security-stage')
CODE_HASHES = {
    'codex_chat_bridge.py': '9b30c6ad8eba308b0595e73ad2c589ae80ddc6576423194e22177685a121e55f',
    'codex_chat_gateway.py': 'bee68d162464133afca1becc39420567ca08e33d47f32692bdc1cfbb56d8d8d5',
    'codex_chat_budget.py': '0991eed1c06f006b9c676649be945f506d45b21a26f7240d436c5e98b2a97db4',
}
LAUNCHER = '/usr/local/libexec/gpt2-codex-sandbox'
PROOF = b'42\n'
MAX_PROVIDER_REQUESTS = 6


def require(value, message):
    if not value:
        raise RuntimeError(message)


def file_hash(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def require_lab_stopped():
    raw = subprocess.check_output(['systemctl', 'show', 'gpt2-codex.service', '-p',
                                   'ActiveState', '-p', 'MainPID', '-p', 'UnitFileState'], text=True)
    state = dict(line.split('=', 1) for line in raw.splitlines())
    require(state == {'ActiveState': 'inactive', 'MainPID': '0', 'UnitFileState': 'disabled'},
            'The real private lab must remain stopped and disabled')


def database_hashes():
    result = {}
    for name in ('chats.sqlite3', 'budget.sqlite3'):
        require((DATA / name).is_file() and not (DATA / name).is_symlink(), 'Missing ordinary production database')
        for suffix in ('', '-wal', '-shm', '-journal'):
            path = DATA / (name + suffix)
            if path.exists():
                require(not path.is_symlink(), 'Unexpected database companion symlink')
                result[name + suffix] = file_hash(path)
    return result


def bounded_ledger_type(base, exceeded):
    class BoundedLedger(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.test_admissions = 0
            self.test_lock = threading.Lock()

        def reserve(self, *args, **kwargs):
            with self.test_lock:
                if self.test_admissions >= MAX_PROVIDER_REQUESTS:
                    raise exceeded('Maintenance test request-count limit reached')
                result = super().reserve(*args, **kwargs)
                self.test_admissions += 1
                return result
    return BoundedLedger


def proof_callback(workspace, recorded, thread_record=None):
    thread_record = {} if thread_record is None else thread_record
    def callback(name, arguments):
        if name == '_thread':
            require(isinstance(arguments, dict) and set(arguments) == {'thread_id'}
                    and isinstance(arguments['thread_id'], str)
                    and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', arguments['thread_id']),
                    'Invalid internal thread callback')
            require(not thread_record or thread_record == arguments,
                    'Internal thread identifier changed')
            # Acknowledge bridge persistence only. Never attach this synthetic
            # thread to the production chat store or write its databases.
            thread_record.update(arguments)
            return {'ok': True}
        require(name == 'emit_message', 'Unexpected application tool in maintenance action')
        require(bool(thread_record), 'Thread initialization callback is missing')
        require(len(recorded) < 2, 'Maintenance action emitted more than two messages')
        if not recorded:
            require(arguments == {'text': 'Maintenance check started.'},
                    'Expected initial maintenance comment before native work')
            recorded.append('started')
            return {'ok': True, 'instruction': 'Now perform the native Python proof, then emit the requested final comment.'}
        require(arguments == {'text': 'Maintenance check: 42.'}, 'Unexpected maintenance reply')
        path = workspace / 'maintenance-proof.txt'
        require(path.is_file() and not path.is_symlink() and path.read_bytes() == PROOF,
                'Native workspace arithmetic proof is missing or incorrect')
        recorded.append('completed')
        return {'ok': True, 'maintenance_test': 'passed', 'instruction': 'Finish this action now.'}
    return callback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-authorized', action='store_true')
    args = parser.parse_args()
    require(sys.platform == 'linux', 'Run on the reviewed Linux host')
    import pwd
    require(os.geteuid() == pwd.getpwnam('gpt-2').pw_uid, 'Run as gpt-2, never as root')
    require_lab_stopped()
    for name, expected in CODE_HASHES.items():
        require(file_hash(SOURCE / 'gpt2_local' / name) == expected, 'Deployed source changed; re-review probe')
    require(file_hash(Path(LAUNCHER)) == '27bb9bcc0039037669acb41e5b129d682ebbd4c7376e8039fc5c011890de8f6e',
            'Installed launcher changed; re-review confinement')
    require(bool(os.environ.get('OPENAI_API_KEY')), 'Operator key unavailable; use the production login shell and EnvironmentFile')
    before = database_hashes()
    if not args.run_authorized:
        print(json.dumps({'ready': True, 'calls': 0, 'writes': False, 'max_action_seconds': 180,
                          'development_ledger_limit_usd': 1, 'max_provider_requests': MAX_PROVIDER_REQUESTS}))
        return
    os.umask(0o077)
    session = uuid.uuid4().hex
    player = DATA / 'agents' / 'players' / session
    require(not os.path.lexists(player), 'Synthetic player collision')
    destination = EVIDENCE / ('provider-regression-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    require(destination.parent.resolve() == EVIDENCE, 'Unexpected evidence directory')
    destination.mkdir(mode=0o700)
    # Claim this unique identifier before bridge creation; no chat row is made.
    player.mkdir(mode=0o700)
    (destination / 'intent.json').write_text(json.dumps({'synthetic_player': session,
        'max_seconds': 180, 'max_requests': MAX_PROVIDER_REQUESTS, 'ledger_limit_usd': 1, 'production_db_hashes_before': before}))
    sys.path.insert(0, str(SOURCE))
    from gpt2_local.codex_chat_budget import DailyBudgetLedger, DailyBudgetExceeded
    from gpt2_local.codex_chat_gateway import CodexAPIGateway
    from gpt2_local.codex_chat_bridge import CodexChatBridge
    ledger = bounded_ledger_type(DailyBudgetLedger, DailyBudgetExceeded)(destination / 'development-budget.sqlite3', daily_limit_usd=1)
    gateway = CodexAPIGateway(os.environ['OPENAI_API_KEY'], ledger, host='172.30.97.1', port=8902)
    bridge = CodexChatBridge(DATA / 'agents', ['/usr/bin/sudo', '-n',
        LAUNCHER, '{session_id}', '{codex_home}', '{workspace}', '{base_url}'], gateway,
        reasoning='medium', timeout_seconds=180, gateway_base_url='http://172.30.97.1:8902/v1')
    emitted = []
    thread_record = {}
    started = time.monotonic()
    succeeded = False
    summary = {}
    try:
        gateway.start()
        result = bridge.run(session,
            'Human addresses Codex. This is one isolated maintenance test, not a conversation. '
            'FIRST call emit_message with exactly "Maintenance check started." to acknowledge the Human. '
            'NEXT use your native shell/code tool to run Python that computes 6*7 and writes its decimal result '
            'followed by one LF newline into maintenance-proof.txt in your workspace. '
            'THEN call emit_message with exactly "Maintenance check: 42." and finish your turn. '
            'Send only these two brief comments in that order. '
            'Do not query GPT-2, wait, browse, spawn subagents, or do any other work.',
            proof_callback(player / 'workspace', emitted, thread_record))
        require(emitted == ['started', 'completed'] and result.get('thread_id') == thread_record.get('thread_id')
                and bool(thread_record), 'Expected completed native/tool action and acknowledged thread')
        # Bridge revocation can race the gateway worker's final ledger commit.
        until = time.monotonic() + 10
        while ledger.snapshot()['unknown_usage_requests'] and time.monotonic() < until:
            time.sleep(.2)
        budget = ledger.snapshot()
        require(1 <= budget['requests'] <= MAX_PROVIDER_REQUESTS and budget['unknown_usage_requests'] == 0,
                'Development usage did not settle completely')
        require(budget['charged_usd'] <= 1, 'Development allowance exceeded')
        summary.update(native_workspace_proof=True, explicit_comment_tool=True, explicit_comments=2,
                       internal_thread_callback_acknowledged=True,
                       development_budget=budget, production_ledger_written=False)
        succeeded = True
    finally:
        gateway.close()
        require_lab_stopped()
        unchanged = database_hashes() == before
        summary.update(passed=succeeded and unchanged, production_database_bytes_unchanged=unchanged,
                       elapsed_seconds=round(time.monotonic() - started, 3))
        (destination / 'result.json').write_text(json.dumps(summary, indent=2) + '\n')
        require(unchanged, 'Production database bytes changed during isolated probe')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # No raw exception, provider payload, key, transcript, private URL or ID.
        print(json.dumps({'passed': False, 'error_type': type(error).__name__,
                          'detail': str(error) if type(error) is RuntimeError else 'Inspect private on-host test evidence'}))
        raise SystemExit(1)
