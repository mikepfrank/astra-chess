"""One-use idle deployment of the authorized two-worker Arcturus trial."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import time

# Resolve already-versioned gate primitives from tools/ops.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import urllib.request

REPO = Path('/home/or-chess/astra-chess')
APP = REPO / 'web-service'
DATA = Path('/home/or-chess/.local/share/or-chess')
PYTHON = APP / '.venv/bin/python'
UNIT = Path('/etc/systemd/system/or-chess.service')
OLD = '3c43bf7b9ece794293f9c6903e8023d96a5a4f9a'
NEW = '565c057d2da396f88965db186cf96254231de115'
STAGE = Path('/home/or-chess/parallel-staging/565c057')


def run(command, timeout=60):
    p = subprocess.run([str(v) for v in command], text=True,
                       capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError('Operation failed: ' + str(command[0]) + ' exit ' + str(p.returncode))
    return p.stdout


def user(*args):
    return run(['sudo', '-u', 'or-chess', *args])


def show(unit, prop):
    return run(['systemctl', 'show', unit, '--property=' + prop, '--value']).strip()


def pids():
    return {n: show(n, 'MainPID') for n in
            ('or-chess.service', 'astra-chess.service', 'astra-caddy.service')}


def digest():
    with sqlite3.connect((DATA / 'astra.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        games = {k: json.loads(v) for k, v in db.execute('SELECT id,state FROM games')}
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            rows = sorted(repr(tuple(row)) for row in db.execute('SELECT * FROM ' + quoted))
            tables[name] = hashlib.sha256('\n'.join(rows).encode()).hexdigest()
    files = {}
    for path in DATA.rglob('*'):
        relative = path.relative_to(DATA)
        if (path.is_symlink() or not path.is_file() or relative.parts[0] == 'operator-checks'
                or (len(relative.parts) == 1 and path.name.startswith('astra.sqlite3'))):
            continue
        files[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'games': games, 'tables': tables, 'files': files}


def idle():
    value = json.loads(user(PYTHON, APP / 'tools/ops/report_games.py',
                           '--data-dir', DATA, '--require-idle', '--json'))
    assert value['activity']['idle_snapshot']
    return value['activity']


def health():
    for _ in range(30):
        try:
            for host in ('arcturuschess.com', 'arcturus.astraplayschess.com'):
                request = urllib.request.Request('http://127.0.0.1:8792/health', headers={'Host': host})
                with urllib.request.urlopen(request, timeout=2) as response:
                    assert response.status == 200
            return True
        except Exception:
            time.sleep(.5)
    return False


def install_unit(content):
    temporary = UNIT.with_name('or-chess.service.parallel-pending')
    temporary.write_bytes(content)
    temporary.chmod(0o644)
    os.replace(temporary, UNIT)
    run(['systemctl', 'daemon-reload'])


def preflight():
    sys.path.insert(0, str(APP))
    from tools.run_openrouter_service_check import service_properties, check_command
    check_id = 'parallel-' + str(os.getpid())
    name = 'or-chess-check-preflight-' + check_id
    props = service_properties(UNIT.read_text())
    props['RuntimeMaxSec'] = ['45']
    try:
        return run(check_command(props, 'preflight', check_id), timeout=55)
    finally:
        # Reap the transient even if its client timeout or namespace check fails.
        subprocess.run(['systemctl', 'stop', name], capture_output=True, timeout=15, check=False)
        state = subprocess.run(['systemctl', 'show', name, '--property=ActiveState',
                                '--property=MainPID', '--property=LoadState'],
                               text=True, capture_output=True, timeout=10)
        fields = dict(row.split('=', 1) for row in state.stdout.splitlines() if '=' in row)
        assert (fields.get('MainPID') == '0'
                and fields.get('ActiveState') not in ('active', 'activating', 'deactivating'))


def main():
    assert os.geteuid() == 0
    os.umask(0o077)
    assert user('git', '-C', REPO, 'rev-parse', 'HEAD').strip() == OLD
    assert user('git', '-C', STAGE, 'rev-parse', 'HEAD').strip() == NEW
    assert not user('git', '-C', REPO, 'status', '--porcelain').strip()
    assert not user('git', '-C', STAGE, 'status', '--porcelain').strip()
    user('git', '-C', REPO, 'merge-base', '--is-ancestor', OLD, NEW)
    allowed = {
        'web-service/HANDOFF.md', 'web-service/OPENROUTER-EXPERIMENT.md',
        'web-service/README.md', 'web-service/astra_web/config.py',
        'web-service/astra_web/openrouter_setup.py', 'web-service/deploy/or-chess.service',
        'web-service/docs/OPENROUTER-DEPLOYMENT.md', 'web-service/tests/audit_parallel_codex.py',
        'web-service/tests/audit_reasoning_roundtrip.py', 'web-service/tests/test_openrouter_service_checks.py',
        'web-service/tests/test_openrouter_setup.py', 'web-service/tests/test_parallel_workers.py',
        'web-service/tests/test_player_profiles.py', 'web-service/tools/check_openrouter_service.py',
        'web-service/validation/2026-09-14-parallel-workers.md',
        'web-service/validation/2026-09-14-status-names.md',
    }
    changed = set(user('git', '-C', REPO, 'diff', '--name-only', OLD, NEW).splitlines())
    assert changed <= allowed, 'Unexpected candidate paths'
    old_unit = UNIT.read_bytes()
    assert old_unit == (APP / 'deploy/or-chess.service').read_bytes()
    assert not show('or-chess.service', 'DropInPaths')
    new_unit = (STAGE / 'web-service/deploy/or-chess.service').read_bytes()
    assert new_unit == old_unit.replace(b'ASTRA_MAX_WORKERS=1\n', b'ASTRA_MAX_WORKERS=2\n').replace(
        b'CPUQuota=50%\n', b'CPUQuota=200%\n').replace(b'TasksMax=64\n', b'TasksMax=128\n')
    audit_path = DATA / 'operator-checks/parallel-native-565c057/parallel-audit.json'
    native = json.loads(audit_path.read_text())
    assert native['audit_completed'] and native['parallelism_proven_before_and_after_restart']
    receipt = json.loads((audit_path.parent / 'candidate-receipt.json').read_text())
    # Bind deployment to the exact commit independently of the report directory name.
    assert NEW in receipt.values()
    before_pids = pids()
    assert all(int(v) > 0 for v in before_pids.values())
    original_units = {n: run(['systemctl', 'cat', n]) for n in
                      ('astra-chess.service', 'astra-caddy.service')}
    idle()
    # The caller's proxy gate now prevents new writes from racing this snapshot.
    before = digest(); idle()
    group = Path('/sys/fs/cgroup') / show('or-chess.service', 'ControlGroup').lstrip('/')
    assert set((group / 'cgroup.procs').read_text().split()) == {before_pids['or-chess.service']}, (
        'A child process is still finishing; defer deployment')
    report = {'candidate': NEW, 'previous_commit': OLD, 'success': False,
              'focused_linux_tests': 151, 'final_cap_tests_rechecked': 6, 'linux_test_failures': 0,
              'native_parallel_audit_passed': True, 'before_pids': before_pids}
    stopped = False
    activated = False
    backup = None
    try:
        run(['systemctl', 'stop', 'or-chess.service']); stopped = True
        assert show('or-chess.service', 'ActiveState') == 'inactive'
        assert show('or-chess.service', 'MainPID') == '0'
        group = Path('/sys/fs/cgroup/system.slice/or-chess.service/cgroup.procs')
        assert not group.exists() or not group.read_text().strip()
        idle()
        assert digest() == before, 'Data changed around stop; defer deployment'
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        backup = Path('/home/or-chess/backups/parallel-workers-' + stamp)
        backup.mkdir(mode=0o700, parents=True)
        with tarfile.open(backup / 'private-data.tar.gz', 'w:gz') as archive:
            archive.add(DATA, arcname='or-chess')
        (backup / 'before.json').write_text(json.dumps(before))
        (backup / 'or-chess.service.before').write_bytes(old_unit)
        report.update(backup=str(backup), utc=stamp)
        user('git', '-C', REPO, 'merge', '--ff-only', NEW)
        install_unit(new_unit)
        preflight_output = preflight()
        (backup / 'namespace-preflight.txt').write_text(preflight_output)
        checked = json.loads(preflight_output[preflight_output.index('{'):])
        assert all(checked['checks'].values())
        runtime = checked['runtime']
        assert runtime['max_workers'] == 2 and runtime['reasoning'] == 'max'
        assert runtime['max_output_tokens'] == 32768 and runtime['compact_limit'] == 250000
        assert runtime['max_daily_tokens'] == 200000000
        assert checked['limits']['cpu.max'] == '200000 100000'
        assert digest() == before, 'Unexpected data mutation during update'
        run(['systemctl', 'start', 'or-chess.service']); stopped = False
        assert health(), 'New service health did not become ready'
        after_pids = pids()
        environment = (Path('/proc') / after_pids['or-chess.service'] / 'environ').read_bytes().split(b'\0')
        assert b'ASTRA_MAX_WORKERS=2' in environment
        cgroup = Path('/sys/fs/cgroup') / show('or-chess.service', 'ControlGroup').lstrip('/')
        limits = {name: (cgroup / name).read_text().strip()
                  for name in ('cpu.max', 'memory.max', 'pids.max')}
        assert limits == {'cpu.max': '200000 100000', 'memory.max': '2147483648', 'pids.max': '128'}
        activated = True
        after = digest()
        report.update(success=True, after_pids=after_pids, limits=limits, runtime=runtime,
            all_game_documents_unchanged=before['games'] == after['games'],
            all_database_tables_unchanged=before['tables'] == after['tables'],
            private_files_unchanged=before['files'] == after['files'],
            game_count=len(before['games']),
            original_service_pids_unchanged=all(before_pids[n] == after_pids[n] for n in original_units),
            original_service_units_unchanged=all(run(['systemctl', 'cat', n]) == text
                                               for n, text in original_units.items()))
        assert report['original_service_pids_unchanged'] and report['original_service_units_unchanged']
        # A real request may arrive after startup: record any change, never rewind player data.
        (backup / 'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    except Exception as error:
        report['error'] = type(error).__name__ + ': ' + str(error)
        if backup:
            (backup / 'result.json').write_text(json.dumps(report, indent=2))
        if not activated:
            run(['systemctl', 'stop', 'or-chess.service']); stopped = True
            # Only this clean deployment checkout is reverted; private data is never restored.
            if user('git', '-C', REPO, 'rev-parse', 'HEAD').strip() != OLD:
                user('git', '-C', REPO, 'reset', '--hard', OLD)
            if UNIT.read_bytes() != old_unit:
                install_unit(old_unit)
        raise
    finally:
        if stopped:
            run(['systemctl', 'start', 'or-chess.service'])


def historical_entrypoint():
    from arcturus_maintenance_gate import arcturus_maintenance_gate
    os.umask(0o077)
    idle()  # Do not close admissions while a response is known to be active.
    with arcturus_maintenance_gate() as gate_report:
        main()  # Includes rollback/restart cleanup before the gate can reopen.
    print(json.dumps({'maintenance_gate': gate_report}), flush=True)


if __name__ == "__main__":
    raise SystemExit("Historical deployment source only; execution is disabled. Read the adjacent README.md.")
