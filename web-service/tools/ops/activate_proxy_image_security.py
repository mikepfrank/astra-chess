#!/usr/bin/env python3
"""Guarded Caddy binary or GPT-2 image selection; does not reopen applications.

Default is a read-only check (apart from operation lock files). --apply preserves
the original file, replaces it atomically, and restarts Caddy only for its binary
swap. Run with the reviewed guard helpers beside this file. Candidate image
selection changes one exact launcher token, never a mutable Docker tag.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import types

CADDY = Path('/home/astra/.local/bin/caddy')
CANDIDATE = Path('/home/ec2-user/chess-security-stage-20261115/caddy/bin/caddy')
CONFIG = Path('/home/astra/.config/astra-chess/Caddyfile')
LAUNCHER = Path('/usr/local/libexec/gpt2-codex-sandbox')
OLD_CADDY = 'b7105518e3ed1c0761f232e44fc09345535533c9cb0abf0e12809416c7ac64d9'
NEW_CADDY = 'e8903acf0e525a53d9ad7c8d72b10bc63b71392ff39f9b7786c15d51a0639d01'
OLD_LAUNCHER = '4aca8f953ec609268110b46374bab6c30f256143f18d56ca073068a0dafc2cbd'
NEW_LAUNCHER = '27bb9bcc0039037669acb41e5b129d682ebbd4c7376e8039fc5c011890de8f6e'
OLD_TAG = 'gpt2-codex-runtime:0.154.0'
OLD_IMAGE = 'sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb'
NEW_TAG = 'gpt2-codex-security:20261116-node22.23.5'
NEW_IMAGE = 'sha256:cd4677302c525c03f02fefe65da2944ec07c6d4bb52aa0bf611a54dc504e71d1'
HELPERS = {
    'backup_host_security.py': 'dba364ed5ab800ab3843d45710a9b9ae36237b82d848609d253027fe8b36f5e7',
    'gpt2_maintenance-v2.py': '80018c27bb074cd66782b9313346b5033bce808cc0a1058c543b92585b1f7912',
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(args, *, input=None, **kwargs):
    p = subprocess.run([str(x) for x in args], input=input, text=True,
                       capture_output=True, timeout=75, **kwargs)
    require(p.returncode == 0, 'Operator subprocess failed; private output suppressed')
    return p.stdout


def regular(path, owner=None, mode=None):
    s = path.lstat()
    require(stat.S_ISREG(s.st_mode) and path.resolve() == path, 'Expected a resolved regular file')
    if owner is not None:
        require((s.st_uid, s.st_gid) == owner, 'File ownership changed')
    if mode is not None:
        require(stat.S_IMODE(s.st_mode) == mode, 'File permissions changed')
    return path.read_bytes(), s


def load_helper(name):
    path = Path(__file__).resolve().with_name(name)
    raw, _ = regular(path)
    require(digest(raw) == HELPERS[name], 'Guard helper checksum changed')
    module = types.ModuleType('guard_' + name.replace('.', '_'))
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


def launcher_bytes(original):
    require(digest(original) == OLD_LAUNCHER, 'Launcher differs from reviewed original')
    require(original.count(OLD_TAG.encode()) == 1, 'Expected exactly one image token')
    updated = original.replace(OLD_TAG.encode(), NEW_IMAGE.encode())
    require(digest(updated) == NEW_LAUNCHER, 'Proposed launcher differs from reviewed change')
    return updated


def placement(path, old_hash, new_hash, owner, mode):
    raw, info = regular(path, owner, mode)
    rollback = path.with_name(path.name + '.pre-security-20261117')
    if digest(raw) == old_hash:
        require(not os.path.lexists(rollback), 'Rollback path already exists; inspect before retrying')
        state = 'original'
    else:
        require(digest(raw) == new_hash, 'Unrecognized active file checksum')
        previous, _ = regular(rollback, owner, mode)
        require(digest(previous) == old_hash, 'Rollback file checksum changed')
        state = 'activated'
    return {'live': path, 'rollback': rollback, 'old_hash': old_hash, 'new_hash': new_hash,
            'owner': owner, 'mode': mode, 'state': state, 'identity': (info.st_dev, info.st_ino)}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def metadata(fd, owner, mode):
    os.fchown(fd, *owner)
    os.fchmod(fd, mode)


def replace_bytes(path, data, owner, mode):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.security-', dir=path.parent)
    try:
        metadata(fd, owner, mode)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def preserve_and_replace(plan, data):
    require(plan['state'] == 'original', 'Already activated; use check')
    current, info = regular(plan['live'], plan['owner'], plan['mode'])
    require((info.st_dev, info.st_ino) == plan['identity'] and digest(current) == plan['old_hash'],
            'Original file identity changed')
    require(digest(data) == plan['new_hash'], 'Candidate bytes changed')
    # O_EXCL prevents replacing any existing rollback file or symlink.
    fd = os.open(plan['rollback'], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, plan['mode'])
    with os.fdopen(fd, 'wb') as stream:
        metadata(stream.fileno(), plan['owner'], plan['mode'])
        stream.write(current); stream.flush(); os.fsync(stream.fileno())
    sync_directory(plan['live'].parent)
    replace_bytes(plan['live'], data, plan['owner'], plan['mode'])


def restore(plan, guard):
    guard()
    current, _ = regular(plan['live'], plan['owner'], plan['mode'])
    previous, _ = regular(plan['rollback'], plan['owner'], plan['mode'])
    require(digest(current) == plan['new_hash'] and digest(previous) == plan['old_hash'],
            'Rollback refused: current or original file changed')
    replace_bytes(plan['live'], previous, plan['owner'], plan['mode'])


def caddy_as_astra(binary, action):
    import pwd
    account = pwd.getpwnam('astra')
    fd = os.open(binary, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return run(['/proc/self/fd/' + str(fd), action, '--config', CONFIG, '--adapter', 'caddyfile'],
            pass_fds=(fd,), user=account.pw_uid, group=account.pw_gid, extra_groups=[],
            cwd='/home/astra/.local/share/astra-caddy',
            env={'PATH': '/usr/bin:/bin', 'HOME': '/home/astra/.local/share/astra-caddy',
                 'XDG_DATA_HOME': '/home/astra/.local/share/astra-caddy',
                 'XDG_CONFIG_HOME': '/home/astra/.local/share/astra-caddy/config'})
    finally:
        os.close(fd)


def gates(maintenance):
    state = maintenance.load()
    for name in (maintenance.PUBLIC, maintenance.LAB):
        maintenance.verify_gate(state, name)
    for host, namespace in [('astraplayschess.com', 'astra-chess-ops'),
                            ('arcturuschess.com', 'arcturus-chess-ops'),
                            ('arcturus.astraplayschess.com', 'arcturus-chess-ops')]:
        state = json.loads(Path('/var/lib', namespace, 'maintenance.json').read_text())
        value = run(['curl', '--silent', '--show-error', '--noproxy', '*', '--max-time', '8',
            '--resolve', host + ':443:127.0.0.1', '--dump-header', '-', '--write-out', '\n%{http_code}',
            'https://' + host + '/'])
        require(value.rstrip().endswith('503') and state['marker'] in value,
                'Chess maintenance response not confirmed')


def proxy_identity(expected):
    data = dict(line.split('=', 1) for line in run(['systemctl', 'show', 'astra-caddy.service',
        '-p', 'ActiveState', '-p', 'MainPID']).splitlines())
    pid = int(data['MainPID'])
    require(data['ActiveState'] == 'active' and pid > 1, 'Proxy is not running')
    require(os.path.samefile('/proc/%d/exe' % pid, CADDY), 'Proxy is not running the selected executable')
    for path in (CADDY, CONFIG):
        require(os.path.samefile(Path('/proc/%d/root' % pid) / path.relative_to('/'), path),
                'Proxy file bind points at a stale inode')
    require(digest(Path('/proc/%d/exe' % pid).read_bytes()) == expected, 'Running proxy binary checksum differs')
    return pid


def restart_and_verify(maintenance, expected):
    run(['systemctl', 'restart', 'astra-caddy.service'])
    end = time.monotonic() + 45
    while True:
        try:
            pid = proxy_identity(expected)
            gates(maintenance)
            return pid
        except (RuntimeError, OSError, ValueError):
            if time.monotonic() >= end:
                raise RuntimeError('Restarted proxy did not pass file-bind and maintenance checks') from None
            time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', choices=('caddy', 'image'), required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(os.name == 'posix' and os.geteuid() == 0, 'Run as root on the reviewed host')
    backup = load_helper('backup_host_security.py')
    maintenance = load_helper('gpt2_maintenance-v2.py')
    with ExitStack() as stack:
        for name in ('astra-chess-ops', 'arcturus-chess-ops', 'gpt2-maintenance-ops'):
            stack.enter_context(maintenance.lock(Path('/var/lib', name, 'operation.lock')))
        stack.enter_context(maintenance.lock(Path('/run/lock/astra-caddy-config.lock')))
        backup.preflight()
        gates(maintenance)
        unchanged_paths = [CONFIG, CONFIG.with_name('new-games.caddy'),
            Path('/home/astra/.local/share/astra-chess/new-games-paused'),
            Path('/usr/local/libexec/gpt2-codex-seccomp.json')]
        unchanged = {p: digest(regular(p)[0]) for p in unchanged_paths}
        if args.component == 'caddy':
            import pwd
            account = pwd.getpwnam('astra')
            plan = placement(CADDY, OLD_CADDY, NEW_CADDY, (account.pw_uid, account.pw_gid), 0o755)
            data, _ = regular(CANDIDATE)
            require(digest(data) == NEW_CADDY, 'Caddy candidate checksum changed')
            require(json.loads(caddy_as_astra(CADDY, 'adapt')) == json.loads(caddy_as_astra(CANDIDATE, 'adapt')),
                    'Caddy configuration adaptation differs')
            if args.apply:
                require(plan['state'] == 'original', 'Already activated; use check')
                # During authorized activation only: provisions validation using
                # the actual astra identity/config/TLS storage, without listeners.
                caddy_as_astra(CANDIDATE, 'validate')
            proxy_identity(OLD_CADDY if plan['state'] == 'original' else NEW_CADDY)
        else:
            plan = placement(LAUNCHER, OLD_LAUNCHER, NEW_LAUNCHER, (0, 0), 0o755)
            original = regular(LAUNCHER if plan['state'] == 'original' else plan['rollback'])[0]
            data = launcher_bytes(original)
            run(['bash', '-n'], input=data.decode())
            require(run(['docker', 'image', 'inspect', '--format', '{{.Id}}', NEW_TAG]).strip() == NEW_IMAGE,
                    'Candidate image tag changed')
            require(run(['docker', 'image', 'inspect', '--format', '{{.Id}}', OLD_TAG]).strip() == OLD_IMAGE,
                    'Original image tag changed')
        if args.apply:
            backup.preflight()
            preserve_and_replace(plan, data)
            try:
                if args.component == 'caddy':
                    restart_and_verify(maintenance, NEW_CADDY)
                else:
                    require(digest(regular(LAUNCHER, (0, 0), 0o755)[0]) == NEW_LAUNCHER, 'Launcher postcheck failed')
                    run(['bash', '-n', LAUNCHER])
                backup.preflight()
                require(all(digest(regular(p)[0]) == value for p, value in unchanged.items()),
                        'A preserved configuration or policy changed')
                gates(maintenance)
            except BaseException as failure:
                try:
                    restore(plan, backup.preflight)
                    if args.component == 'caddy':
                        restart_and_verify(maintenance, OLD_CADDY)
                except BaseException:
                    raise RuntimeError('Activation failed and rollback failed/refused; inspect retained original file and service state') from failure
                raise RuntimeError('Activation checks failed; original file restored with applications still stopped') from failure
        print(json.dumps({'component': args.component, 'applied': args.apply,
            'placement': 'activated' if args.apply else plan['state'], 'live_path': str(plan['live']),
            'rollback_path': str(plan['rollback']), 'active_sha256': digest(regular(plan['live'])[0]),
            'apps_started': False, 'maintenance_gates_verified': True,
            'preserved_configuration': all(digest(regular(p)[0]) == value for p, value in unchanged.items())}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'passed': False, 'error': str(error) if type(error) is RuntimeError
                          else 'Activation/check failed: ' + type(error).__name__}))
        raise SystemExit(1)
