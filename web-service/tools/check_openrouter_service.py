"""Check the experimental Linux service boundary before wire or live testing.

Preflight makes no network requests. Wire testing uses a loopback mock provider.
Only live --live starts paid actions, retaining the service's shared budget file.
"""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile


APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from astra_web.config import Config
from astra_web.openrouter_setup import _ledger, OpenRouterSetupError
from astra_web.player_profiles import new_player_binding, profile_for
from tools.check_linux_service import _codex_version


DATA = Path('/home/or-chess/.local/share/or-chess')
RUNTIME = Path('/home/or-chess/.local/share/or-chess-runtime')
CODEX = RUNTIME / 'codex/bin/codex'
BUDGET = DATA / 'openrouter-budget.json'


def preflight():
    import pwd
    config = Config()
    key = os.environ.get('OPENROUTER_API_KEY', '')
    checks = {
        'service_user': pwd.getpwuid(os.getuid()).pw_name == 'or-chess',
        'openrouter_key_present': bool(key),
        'openai_keys_absent': not any(os.environ.get(name) for name in ('OPENAI_API_KEY', 'CODEX_API_KEY')),
        'application_path': APP_ROOT == Path('/home/or-chess/astra-chess/web-service'),
        'data_path': config.data_dir == DATA,
        'codex_path': config.codex_bin == str(CODEX),
        'shared_budget_path': os.environ.get('ASTRA_OPENROUTER_BUDGET_PATH') == str(BUDGET),
        'fixed_profile': config.model_profile == 'openrouter-glm' and config.persona == 'arcturus',
        'single_codex_worker': config.player_mode == 'codex' and config.max_workers == 1,
        'https_origin': config.origin == 'https://arcturuschess.com' and config.secure_cookies,
        'legacy_origin_alias': config.additional_origins == ('https://arcturus.astraplayschess.com',),
        'python_312': sys.version_info[:2] == (3, 12),
    }
    # Refuse unexpected paths before creating any disposable probes.
    if not all(checks.values()):
        return {'checks': checks}
    config.validate()
    profile = profile_for(config)
    binding = new_player_binding(config)
    checks['arcturus_prompt'] = (binding['persona']['name'] == 'arcturus'
        and binding['prompt'].startswith('You are Arcturus, an AI chess-playing persona.\n'))
    checks['existing_private_budget'] = False
    try:
        ledger = _ledger(BUDGET)
        info = BUDGET.stat()
        checks['existing_private_budget'] = (ledger is not None
            and ledger['key_sha256'] == hashlib.sha256(key.encode('utf-8')).hexdigest()
            and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
            and not BUDGET.is_symlink())
    except (OSError, OpenRouterSetupError):
        pass
    checks['password_hashing'] = len(hashlib.scrypt(
        b'preflight', salt=b'disposable-test-salt', n=32768, r=8, p=3,
        dklen=64, maxmem=64 * 1024 * 1024)) == 64
    checks['repository_readable'] = (APP_ROOT.parent / 'astra_engine/rules.py').is_file()
    checks['codex_bundle'] = all((RUNTIME / 'codex' / name).is_file()
        for name in ('bin/codex', 'bin/codex-code-mode-host', 'codex-resources/bwrap', 'codex-path/rg'))
    hidden = ('/home/astra/astra-chess', '/home/astra/.local/share/astra-chess',
              '/home/or-chess/.ssh', '/home/or-chess/.codex/auth.json',
              '/home/or-chess/.codex/config.toml', '/home/or-chess/.config/or-chess/service.env',
              '/home/ec2-user/.ssh')
    checks['operator_and_production_files_hidden'] = all(not Path(path).exists() for path in hidden)
    for label, directory in (('source_read_only', APP_ROOT), ('runtime_read_only', RUNTIME)):
        checks[label] = False
        try:
            with tempfile.NamedTemporaryFile(prefix='.or-chess-permission-probe-', dir=directory):
                pass
        except OSError as error:
            checks[label] = error.errno in (errno.EROFS, errno.EACCES)
    with tempfile.TemporaryDirectory(prefix='service-probe-', dir=DATA) as scratch:
        connection = sqlite3.connect(Path(scratch) / 'check.sqlite3')
        try:
            connection.execute('CREATE TABLE probe (value TEXT)')
            connection.execute("INSERT INTO probe VALUES ('ok')")
            connection.commit()
            checks['private_data_writable'] = connection.execute('SELECT value FROM probe').fetchone() == ('ok',)
        finally:
            connection.close()
    relative = next(line.split(':', 2)[2] for line in Path('/proc/self/cgroup').read_text().splitlines()
                    if line.startswith('0::'))
    cgroup = Path('/sys/fs/cgroup') / relative.lstrip('/')
    limits = {name: (cgroup / name).read_text().strip()
              for name in ('memory.max', 'pids.max', 'cpu.max')}
    checks['memory_limit'] = limits['memory.max'] == str(2 * 1024 ** 3)
    checks['process_limit'] = limits['pids.max'] == '64'
    quota, period = limits['cpu.max'].split()
    checks['cpu_limit'] = quota != 'max' and int(quota) * 2 <= int(period)
    checks['nice_priority'] = os.getpriority(os.PRIO_PROCESS, 0) == 10
    version = _codex_version(config)
    checks['reviewed_codex_version'] = version == 'codex-cli 0.154.0'
    return {'checks': checks, 'limits': limits,
            'runtime': {'profile_version': profile.version, 'reasoning': profile.reasoning,
                        'max_output_tokens': profile.max_output_tokens,
                        'context_window': profile.context_window, 'compact_limit': profile.compact_limit,
                        'max_turn_tokens': config.max_turn_tokens, 'max_daily_tokens': config.max_daily_tokens},
            'python': sys.version.split()[0],
            'sqlite': sqlite3.sqlite_version, 'codex': version}


def followup_command(mode, check_id):
    if mode == 'wire':
        return [sys.executable, str(APP_ROOT / 'tests/audit_model_wire.py'),
                '--codex', str(CODEX), '--candidate-version', '0.154.0',
                '--audit-dir', str(DATA / 'operator-checks/wire'), '--through-gateway']
    if mode == 'live':
        return [sys.executable, str(APP_ROOT / 'tests/live_codex_check.py'),
                '--live', '--turns', '2', '--profile', 'openrouter-glm',
                '--codex-bin', str(CODEX), '--data-dir', str(DATA / f'operator-checks/live-{check_id}')]
    raise ValueError('Unknown service check mode')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', choices=('preflight', 'wire', 'live'), default='preflight')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if args.mode == 'live' and not args.live:
        parser.error('The live check requires --live.')
    if sys.platform != 'linux':
        parser.error('This check requires Linux and the installed service namespace.')
    try:
        report = preflight()
    except Exception as error:
        # Never include arbitrary exception text, credential values or ledger data.
        print(json.dumps({'preflight_error_type': type(error).__name__}))
        return 1
    print(json.dumps(report, indent=2), flush=True)
    if not all(report['checks'].values()):
        return 1
    if args.mode == 'preflight':
        return 0
    return subprocess.run(followup_command(args.mode, secrets.token_hex(5)), check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
