"""One-use gated deployment of the reviewed Arcturus chat deadline fix."""
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import time

# Resolve already-versioned gate primitives from tools/ops.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import deploy_parallel_workers as base
from arcturus_maintenance_gate import arcturus_maintenance_gate

OLD = '16e2bd8c4adef494c6ab10555849459902ba884e'
ENV = Path('/home/or-chess/.config/or-chess/service.env')


def main():
    os.umask(0o077)
    new = sys.argv[1]
    assert re.fullmatch(r'[0-9a-f]{40}', new)
    stage = Path('/home/or-chess/chat-staging') / new[:7]
    checks = json.loads((stage / 'web-service/var/chat-tests.json').read_text())
    assert checks['commit'] == new and checks['success'] and checks['tests'] >= 40
    native = json.loads((stage / 'web-service/var/native-chat-receipt.json').read_text())
    assert native['commit'] == new and native['success'] and native['completed_actions'] == 3
    assert base.user('git', '-C', base.REPO, 'rev-parse', 'HEAD').strip() == OLD
    assert base.user('git', '-C', stage, 'rev-parse', 'HEAD').strip() == new
    assert not base.user('git', '-C', base.REPO, 'status', '--porcelain').strip()
    assert not base.user('git', '-C', stage, 'status', '--porcelain').strip()
    base.user('git', '-C', base.REPO, 'merge-base', '--is-ancestor', OLD, new)
    allowed = {
        'web-service/HANDOFF.md', 'web-service/OPENROUTER-EXPERIMENT.md',
        'web-service/docs/GAME-NOTIFICATIONS.md', 'web-service/docs/OPERATOR-MONITOR.md',
        'web-service/validation/2026-09-14-monitor-notifications.md',
        'web-service/astra_web/supervisor.py', 'web-service/astra_web/codex_bridge.py',
        'web-service/astra_web/player_profiles.py',
        'web-service/tests/test_bridge_time_policy.py',
        'web-service/tests/test_chat_time_policy.py',
        'web-service/tests/test_chat_reasoning_policy.py',
        'web-service/tests/test_player_profiles.py',
        'web-service/tests/test_openrouter_gateway.py',
        'web-service/tests/audit_chat_reasoning.py',
        'web-service/validation/2026-09-14-chat-deadline.md',
    }
    assert set(base.user('git', '-C', base.REPO, 'diff', '--name-only', OLD, new).splitlines()) <= allowed
    original_env = ENV.read_bytes()
    original_units = {name: base.run(['systemctl', 'cat', name]) for name in (
        'or-chess.service', 'astra-chess.service', 'astra-caddy.service',
        'or-chess-game-notify.service', 'or-chess-game-notify.timer',
        'astra-game-notify.service', 'astra-game-notify.timer')}
    assert base.UNIT.read_bytes() == (stage / 'web-service/deploy/or-chess.service').read_bytes()
    assert not base.show('or-chess.service', 'DropInPaths')
    base.idle()
    before_pids = base.pids()
    with arcturus_maintenance_gate() as gate:
        base.idle()
        before = base.digest()
        base.idle()
        group = Path('/sys/fs/cgroup') / base.show('or-chess.service', 'ControlGroup').lstrip('/')
        assert set((group / 'cgroup.procs').read_text().split()) == {before_pids['or-chess.service']}
        stopped = False
        activated = False
        backup = None
        report = {'commit': new, 'success': False, 'linux_tests': checks['tests'],
                  'native_reasoning_transition_verified': True}
        try:
            base.run(['systemctl', 'stop', 'or-chess.service'])
            stopped = True
            assert base.show('or-chess.service', 'MainPID') == '0'
            assert not group.exists() or not (group / 'cgroup.procs').read_text().strip()
            assert base.digest() == before
            stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
            backup = Path('/home/or-chess/backups/chat-deadline-' + stamp)
            backup.mkdir(mode=0o700, parents=True)
            with tarfile.open(backup / 'private-data.tar.gz', 'w:gz') as archive:
                archive.add(base.DATA, arcname='or-chess')
            (backup / 'before.json').write_text(json.dumps(before))
            report.update(utc=stamp, backup=str(backup))
            base.user('git', '-C', base.REPO, 'merge', '--ff-only', new)
            checked = json.loads(base.preflight())
            assert all(checked['checks'].values())
            runtime = checked['runtime']
            assert runtime['max_workers'] == 2 and runtime['reasoning'] == 'max'
            assert runtime['max_output_tokens'] == 32768 and runtime['compact_limit'] == 250000
            assert runtime['max_daily_tokens'] == 200000000
            assert before == base.digest() and ENV.read_bytes() == original_env
            base.run(['systemctl', 'start', 'or-chess.service'])
            stopped = False
            assert base.health()
            after_pids = base.pids()
            after = base.digest()
            report.update(game_count=len(before['games']), before_pids=before_pids, after_pids=after_pids,
                all_game_documents_unchanged=before['games'] == after['games'],
                all_database_tables_unchanged=before['tables'] == after['tables'],
                private_files_unchanged=before['files'] == after['files'],
                configuration_unchanged=ENV.read_bytes() == original_env,
                original_service_pids_unchanged=all(before_pids[n] == after_pids[n]
                    for n in ('astra-chess.service', 'astra-caddy.service')),
                all_service_units_unchanged=all(base.run(['systemctl', 'cat', n]) == content
                    for n, content in original_units.items()), runtime=runtime)
            assert all(report[k] for k in ('all_game_documents_unchanged','all_database_tables_unchanged',
                'private_files_unchanged','configuration_unchanged','original_service_pids_unchanged',
                'all_service_units_unchanged'))
            activated = True
            report['success'] = True
            (backup / 'result.json').write_text(json.dumps(report, indent=2))
        except Exception as error:
            report['error_type'] = type(error).__name__
            if backup:
                (backup / 'result.json').write_text(json.dumps(report, indent=2))
            if not activated:
                base.run(['systemctl', 'stop', 'or-chess.service'])
                stopped = True
                assert not base.user('git', '-C', base.REPO, 'status', '--porcelain').strip()
                if base.user('git', '-C', base.REPO, 'rev-parse', 'HEAD').strip() != OLD:
                    base.user('git', '-C', base.REPO, 'reset', '--hard', OLD)
            raise
        finally:
            if stopped:
                base.run(['systemctl', 'start', 'or-chess.service'])
    report['gate_restored'] = gate['restored']
    (backup / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


def historical_entrypoint():
    main()


if __name__ == "__main__":
    raise SystemExit("Historical deployment source only; execution is disabled. Read the adjacent README.md.")
