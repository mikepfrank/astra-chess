"""Deploy the reviewed UI controls, tool-output repair, records and chat export.

Run from the exact clean staged commit on the reviewed Lightsail host, as root.
Requires exact-revision offline and native mocked-provider receipts. Only the
Arcturus app is stopped/restarted; environment, units, timers and player records
are not edited. Rollback restores code only, never a database or private file.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tarfile
import time


REPO = Path('/home/or-chess/astra-chess')
STAGE_ROOT = Path('/home/or-chess/ui-staging')
CONFIG = Path('/home/or-chess/.config/or-chess')
BRANCH = 'codex/openrouter-chess'
UNITS = (
    'or-chess.service', 'astra-chess.service', 'astra-caddy.service',
    'or-chess-game-notify.service', 'or-chess-game-notify.timer',
    'astra-game-notify.service', 'astra-game-notify.timer',
)
LIMITS = {'cpu.max': '200000 100000', 'memory.max': '2147483648', 'pids.max': '128'}

# Exact reviewed scope, including the September 14 preservation-only commits
# between the installed ce66868 revision and the new UI release. Adding a path
# requires another source review; no directory-prefix or glob exemptions.
ALLOWED_PATHS = frozenset({
    'HANDOFF.md',
    'web-service/HANDOFF.md',
    'web-service/OPENROUTER-EXPERIMENT.md',
    'web-service/astra_web/app.py',
    'web-service/astra_web/chess_game.py',
    'web-service/astra_web/chat_export.py',
    'web-service/astra_web/codex_bridge.py',
    'web-service/astra_web/openrouter_gateway.py',
    'web-service/astra_web/player_profiles.py',
    'web-service/astra_web/replay_archive.py',
    'web-service/astra_web/supervisor.py',
    'web-service/astra_web/store.py',
    'web-service/prompts/public-comment-policy.md',
    'web-service/prompts/move-deliberation-policy.md',
    'web-service/prompts/README.md',
    'web-service/deploy/dns/README.md',
    'web-service/deploy/dns/arcturuschess.com.changes.txt',
    'web-service/docs/FUTURE-FEATURES.md',
    'web-service/docs/OPENROUTER-DEPLOYMENT.md',
    'web-service/docs/OPERATOR-MONITOR.md',
    'web-service/static/app.js',
    'web-service/static/index.html',
    'web-service/static/monitor.css',
    'web-service/static/monitor.html',
    'web-service/static/monitor.js',
    'web-service/static/style.css',
    'web-service/tests/audit_arcturus_public.py',
    'web-service/tests/audit_chat_reasoning.py',
    'web-service/tests/audit_private_notes.py',
    'web-service/tests/audit_tool_visibility.py',
    'web-service/tests/audit_or_chess_notifier_namespace.py',
    'web-service/tests/browser/monitor.cjs',
    'web-service/tests/browser/move_reasoning.cjs',
    'web-service/tests/browser/matchup_record.cjs',
    'web-service/tests/browser/chat_export.cjs',
    'web-service/tests/browser/README.md',
    'web-service/tests/check_chat_policy.py',
    'web-service/tests/check_ui_controls.py',
    'web-service/tests/test_chat_reasoning_policy.py',
    'web-service/tests/test_chat_time_policy.py',
    'web-service/tests/test_codex_bridge.py',
    'web-service/tests/test_move_reasoning.py',
    'web-service/tests/test_matchup_record.py',
    'web-service/tests/test_chat_export.py',
    'web-service/tests/test_player_profiles.py',
    'web-service/tests/test_openrouter_gateway.py',
    'web-service/tests/test_replay_archive.py',
    'web-service/tests/test_replay_reasoning.py',
    'web-service/tools/ops/README.md',
    'web-service/tools/ops/check_arcturus_mail.py',
    'web-service/tools/ops/deploy_arcturus_ui.py',
    'web-service/tools/ops/history/2026-09-14/README.md',
    'web-service/tools/ops/history/2026-09-14/deploy_chat_allowance.py',
    'web-service/tools/ops/history/2026-09-14/deploy_parallel_workers.py',
    'web-service/validation/2026-09-14-chat-deadline.md',
    'web-service/validation/2026-09-14-housekeeping.md',
    'web-service/validation/2026-09-15-ui-controls.md',
    'web-service/validation/2026-09-15-chat-context-truncation.md',
    'web-service/validation/2026-09-15-matchup-record.md',
    'web-service/validation/2026-09-15-chat-export.md',
    'web-service/validation/2026-09-17-private-notes.md',
    'web-service/validation/2026-09-18-comment-reminder.md',
    'web-service/validation/2026-09-20-output-limit-incident.md',
    'web-service/validation/2026-09-20-deliberation-guidance.md',
    'web-service/validation/2026-09-20-request-metadata.md',
})


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load_base():
    """Import preserved primitives without invoking historical entrypoints."""
    root = Path(__file__).resolve().parent
    source = root / 'history/2026-09-14/deploy_parallel_workers.py'
    spec = importlib.util.spec_from_file_location('preserved_arcturus_deployment', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.path.insert(0, str(root))
    return module


def receipt(path, commit):
    require(path.is_file() and not path.is_symlink(), 'Required receipt is missing or symlinked.')
    require(path.stat().st_size <= 1024 * 1024, 'Receipt is unexpectedly large.')
    value = json.loads(path.read_text())
    require(value.get('commit') == commit and value.get('success') is True,
            'Receipt does not establish success at the exact candidate commit.')
    return value


def validate_receipts(stage, commit):
    tests = receipt(stage / 'web-service/var/ui-tests.json', commit)
    require(type(tests.get('tests')) is int and tests['tests'] >= 151,
            'The focused Linux regression receipt is incomplete.')
    require(tests.get('failures') == 0 and tests.get('errors') == 0,
            'The focused Linux regression receipt has failures or errors.')
    native = receipt(stage / 'web-service/var/native-ui-reasoning-receipt.json', commit)
    require(native.get('completed_actions') == 4
            and native.get('external_provider_contacted') is False
            and native.get('real_credentials_used') is False
            and native.get('immutable_binding_preserved') is True
            and native.get('move_deliberation_policy_verified') is True
            and native.get('cli_version') == '0.154.0',
            'The native mocked-provider reasoning receipt is incomplete.')
    expected = [('move', 'max'), ('move', 'high'), ('chat', 'high'), ('move', 'max')]
    actions = native.get('actions', [])
    require([(a.get('kind'), a.get('effort')) for a in actions] == expected
            and all(a.get('same_thread') is True and a.get('process_reaped') is True
                    and a.get('original_identity_preserved') is True for a in actions),
            'The native receipt must verify four actions on one saved thread.')
    requests = native.get('requests', [])
    require([(r.get('kind'), r.get('effort')) for r in requests]
            == [value for value in expected for _ in range(2)]
            and all(r.get('max_output_tokens') == 32768
                    and r.get('move_deliberation_policy_on_wire') is True for r in requests),
            'The native receipt must verify eight transmitted provider requests.')
    visibility = receipt(stage / 'web-service/var/native-tool-visibility.json', commit)
    expected_visibility = {
        'checkout_clean': True, 'exact_commit': True, 'cli_version': '0.154.0',
        'tool_output_token_limit': 65536, 'external_provider_contacted': False,
        'real_credentials_inherited': False, 'case_count': 3, 'request_count': 12,
        'wire_check_count': 9, 'all_status_snapshots_preserved': True,
        'all_user_messages_preserved': True, 'all_threads_resumed': True,
    }
    require(all(type(visibility.get(key)) is type(value) and visibility[key] == value
                for key, value in expected_visibility.items()),
            'Native tool visibility must preserve long messages before and after resume.')
    notes = receipt(stage / 'web-service/var/native-private-notes.json', commit)
    expected_notes = {
        'checkout_clean': True, 'exact_commit': True, 'cli_version': '0.154.0',
        'external_provider_contacted': False, 'real_credentials_used': False,
        'completed_actions': 3, 'request_count': 8, 'public_comment_count': 2,
        'private_note_count': 6, 'private_history_survived_restart': True,
        'conditional_comment_reminder_verified': True,
        'move_deliberation_policy_verified': True,
        'request_metadata_verified': True,
        'request_metadata_check_count': 8,
        'old_saved_prompt_preserved': True, 'dynamic_tool_schema_unchanged': True,
        'reasoning_never_published_or_persisted_as_note': True,
        'long_private_note_exceeds_public_limit': True,
    }
    require(all(type(notes.get(key)) is type(value) and notes[key] == value
                for key, value in expected_notes.items()),
            'Native notes audit must verify private history and explicit public comments across resume.')
    require(len(notes.get('requests', [])) == 8
            and all(row.get('developer_policy_on_wire') is True
                    and row.get('move_deliberation_policy_on_wire') is True
                    and row.get('conditional_reminder_verified') is True for row in notes['requests']),
            'The publication policy must reach every native provider request.')
    return tests, native


def clean_revision(base, checkout, revision):
    require(base.user('git', '-C', checkout, 'rev-parse', 'HEAD').strip() == revision,
            'Checkout revision changed; refuse deployment.')
    require(not base.user('git', '-C', checkout, 'status', '--porcelain').strip(),
            'Checkout has changes or untracked files; refuse deployment.')


def config_digest():
    result = {}
    require(CONFIG.is_dir() and not CONFIG.is_symlink(), 'Private configuration directory is unexpected.')
    for path in CONFIG.rglob('*'):
        require(not path.is_symlink(), 'Symlink in private configuration requires review.')
        if path.is_file():
            result[str(path.relative_to(CONFIG))] = hashlib.sha256(path.read_bytes()).hexdigest()
    require('service.env' in result, 'The installed service environment is missing.')
    return result


def unit_snapshot(base):
    return {unit: base.run(['systemctl', 'cat', unit]) for unit in UNITS}


def timer_snapshot(base):
    return {unit: {prop: base.show(unit, prop) for prop in ('ActiveState', 'UnitFileState')}
            for unit in UNITS if unit.endswith('.timer')}


def group_path(base):
    relative = base.show('or-chess.service', 'ControlGroup')
    require(relative == '/system.slice/or-chess.service', 'Unexpected Arcturus control group.')
    return Path('/sys/fs/cgroup') / relative.lstrip('/')


def require_no_children(base, expected_pid):
    group = group_path(base)
    require(set((group / 'cgroup.procs').read_text().split()) == {expected_pid},
            'An Arcturus child is still finishing; defer deployment.')
    require({name: (group / name).read_text().strip() for name in LIMITS} == LIMITS,
            'The installed aggregate resource limits differ from the reviewed values.')
    return group


def stop_app(base, group):
    base.run(['systemctl', 'stop', 'or-chess.service'])
    require(base.show('or-chess.service', 'MainPID') == '0', 'Arcturus did not stop.')
    require(not group.exists() or not (group / 'cgroup.procs').read_text().strip(),
            'Arcturus descendants have not been reaped.')


def validate_runtime(checked):
    require(checked.get('checks') and all(checked['checks'].values()),
            'Installed namespace preflight failed.')
    runtime = checked.get('runtime', {})
    expected = {'max_workers': 2, 'reasoning': 'max', 'max_output_tokens': 32768,
                'compact_limit': 250000, 'max_daily_tokens': 200000000}
    require(all(runtime.get(key) == value for key, value in expected.items()),
            'Deployment changed a runtime setting outside the reviewed scope.')
    require(checked.get('limits') == LIMITS, 'Installed namespace resource ceilings changed.')
    return runtime


def deploy(args):
    require(sys.platform == 'linux' and hasattr(os, 'geteuid') and os.geteuid() == 0,
            'This deployment requires root on the reviewed Linux host.')
    require(not sys.flags.optimize, 'Run without Python optimization; preserved checks use assertions.')
    os.umask(0o077)
    require(REPO.resolve() == REPO, 'The installed checkout path must not traverse symlinks.')
    require(args.from_commit != args.to_commit, 'The deployment revisions must differ.')
    expected_stage = STAGE_ROOT / args.to_commit[:7]
    require(args.stage == expected_stage and args.stage.resolve() == expected_stage,
            'Stage must be the real absolute ui-staging directory for this commit prefix.')
    require(Path(__file__).resolve() == args.stage / 'web-service/tools/ops/deploy_arcturus_ui.py',
            'Run this helper from the exact staged candidate checkout.')
    base = load_base()
    from arcturus_maintenance_gate import arcturus_maintenance_gate
    clean_revision(base, REPO, args.from_commit)
    clean_revision(base, args.stage, args.to_commit)
    require(base.user('git', '-C', REPO, 'branch', '--show-current').strip() == BRANCH,
            'Installed checkout is not the experimental branch.')
    base.user('git', '-C', REPO, 'merge-base', '--is-ancestor', args.from_commit, args.to_commit)
    changed = set(base.user('git', '-C', REPO, 'diff', '--name-only',
                            args.from_commit, args.to_commit).splitlines())
    require(changed and changed <= ALLOWED_PATHS, 'Candidate contains an unreviewed path.')
    tests, _ = validate_receipts(args.stage, args.to_commit)
    require(not base.show('or-chess.service', 'DropInPaths'), 'Unit drop-ins require separate review.')
    require(base.UNIT.read_bytes() == (args.stage / 'web-service/deploy/or-chess.service').read_bytes(),
            'Candidate unit differs from the installed unit.')
    original_config = config_digest()
    original_units = unit_snapshot(base)
    original_timers = timer_snapshot(base)
    base.idle()  # Do not close admissions while a response is known to be active.
    before_pids = base.pids()
    require(all(int(pid) > 0 for pid in before_pids.values()), 'A required service is not running.')
    report = {'from_commit': args.from_commit, 'commit': args.to_commit, 'success': False,
              'linux_tests': tests['tests'], 'native_reasoning_actions': 4,
              'tool_output_token_limit': 65536, 'native_tool_visibility_checks': 9,
              'changed_paths': sorted(changed), 'before_pids': before_pids}
    backup = None
    with arcturus_maintenance_gate() as gate:
        base.idle()
        before = base.digest()
        base.idle()
        require(base.pids() == before_pids, 'A service process changed before the final idle check.')
        group = require_no_children(base, before_pids['or-chess.service'])
        clean_revision(base, REPO, args.from_commit)
        clean_revision(base, args.stage, args.to_commit)
        validate_receipts(args.stage, args.to_commit)
        try:
            stop_app(base, group)
            require(base.digest() == before, 'Private data changed around stop; defer deployment.')
            stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
            backup = Path('/home/or-chess/backups') / ('ui-reasoning-' + stamp)
            backup.mkdir(mode=0o700, parents=True)
            with tarfile.open(backup / 'private-data.tar.gz', 'w:gz') as archive:
                archive.add(base.DATA, arcname='or-chess')
                archive.add(CONFIG, arcname='or-chess-config')
            (backup / 'before.json').write_text(json.dumps(before))
            (backup / 'units.json').write_text(json.dumps(original_units))
            (backup / 'configuration-digests.json').write_text(json.dumps(original_config))
            report.update(utc=stamp, backup=str(backup))
            base.user('git', '-C', REPO, 'merge', '--ff-only', args.to_commit)
            clean_revision(base, REPO, args.to_commit)
            checked = json.loads(base.preflight())
            runtime = validate_runtime(checked)
            (backup / 'namespace-preflight.json').write_text(json.dumps(checked, indent=2))
            require(base.digest() == before and config_digest() == original_config,
                    'Data or private configuration changed during namespace preflight.')
            base.run(['systemctl', 'start', 'or-chess.service'])
            require(base.health(), 'Arcturus health did not become ready.')
            after_pids = base.pids()
            after = base.digest()
            report.update(game_count=len(before['games']), after_pids=after_pids, runtime=runtime,
                all_game_documents_unchanged=before['games'] == after['games'],
                all_database_tables_unchanged=before['tables'] == after['tables'],
                private_files_unchanged=before['files'] == after['files'],
                configuration_unchanged=config_digest() == original_config,
                original_service_pids_unchanged=all(before_pids[name] == after_pids[name]
                    for name in ('astra-chess.service', 'astra-caddy.service')),
                all_service_units_unchanged=unit_snapshot(base) == original_units,
                notification_timers_unchanged=timer_snapshot(base) == original_timers)
            require(all(report[name] for name in (
                'all_game_documents_unchanged', 'all_database_tables_unchanged', 'private_files_unchanged',
                'configuration_unchanged', 'original_service_pids_unchanged',
                'all_service_units_unchanged', 'notification_timers_unchanged')),
                'A preservation check failed; private data must never be restored automatically.')
            require_no_children(base, after_pids['or-chess.service'])
            base.idle()
            report['activation_verified'] = True
            (backup / 'result.json').write_text(json.dumps(report, indent=2))
        except BaseException as error:
            report['error_type'] = type(error).__name__
            # Gate stays closed through rollback/restart. Only the exact clean
            # candidate checkout is eligible for code rollback; no DB restore.
            try:
                stop_app(base, group)
                current = base.user('git', '-C', REPO, 'rev-parse', 'HEAD').strip()
                require(current in (args.from_commit, args.to_commit),
                        'Unexpected checkout revision; automatic rollback is unsafe.')
                clean_revision(base, REPO, current)
                if current == args.to_commit:
                    base.user('git', '-C', REPO, 'reset', '--keep', args.from_commit)
                clean_revision(base, REPO, args.from_commit)
                report['code_rollback_verified'] = True
            finally:
                base.run(['systemctl', 'start', 'or-chess.service'])
                report['recovery_health'] = base.health()
                if backup is not None:
                    (backup / 'result.json').write_text(json.dumps(report, indent=2))
            raise
    report['gate_restored'] = gate['restored']
    require(report['gate_restored'], 'Maintenance gate restoration was not verified.')
    report['success'] = True
    (backup / 'result.json').write_text(json.dumps(report, indent=2))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-commit', required=True, help='Exact installed 40-character commit SHA')
    parser.add_argument('--to-commit', required=True, help='Exact staged 40-character candidate SHA')
    parser.add_argument('--stage', type=Path, required=True,
                        help='Absolute /home/or-chess/ui-staging/<first-seven-candidate-characters>')
    args = parser.parse_args(argv)
    if not all(re.fullmatch(r'[0-9a-f]{40}', value) for value in (args.from_commit, args.to_commit)):
        parser.error('Both commits must be full lowercase 40-character Git SHAs.')
    try:
        report = deploy(args)
    except BaseException as error:
        # Arbitrary exception messages and command output can contain private
        # information. Detailed state remains in the root-only backup receipt.
        print(json.dumps({'success': False, 'error_type': type(error).__name__}), flush=True)
        return 1
    print(json.dumps(report), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
