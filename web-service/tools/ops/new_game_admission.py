#!/usr/bin/env python3
"""Pause/reopen only new Astra games on the existing Lightsail host.

Run as ec2-user with sudo python3 -I -B. Does not restart either chess app.
The shared Caddy proxy requires a brief restart because its admin API is off.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time

OPS = Path('/home/astra/astra-chess/web-service/tools/ops/astra_service.py')
FRAGMENT = Path('/home/astra/.config/astra-chess/new-games.caddy')
IMPORT = '    import ' + FRAGMENT.as_posix() + '\n'
DROPIN = Path('/etc/systemd/system/astra-caddy.service.d/30-new-game-admission.conf')
DROPIN_CONTENT = ('[Service]\nBindReadOnlyPaths=-' + FRAGMENT.as_posix() + '\n').encode()
URL = 'https://github.com/mikepfrank/astra-chess/blob/codex/hosted-chess/web-service/DEPLOYMENT.md'
MESSAGE = ('New games cannot be started for the time being because of OpenAI API costs. '
           'You can continue or resume games that have already been started. '
           'If you have your own OpenAI API key and web hosting, you can deploy your own '
           'instance by asking Codex, Astra, or a similar coding agent to follow the deployment guide: ' + URL)


def policy():
    return dict(new_games_available=False, new_games_message=MESSAGE, deployment_url=URL)


def fragment():
    denial = dict(detail=MESSAGE, code='new_games_paused', deployment_url=URL)
    chunks = ['# Managed by tools/ops/new_game_admission.py. Only new-game admission is paused.\n']
    for name, method, path, payload, status in (
            ('astra_new_games_paused', 'POST', '/api/games /api/games/', denial, 503),
            ('astra_new_game_policy', 'GET', '/api/new-game-policy', policy(), 200)):
        chunks.append('@' + name + ' {\n    method ' + method + '\n    path ' + path + '\n}\n')
        chunks.append('header @' + name + ' Content-Type application/json\n')
        chunks.append('header @' + name + ' Cache-Control no-store\n')
        chunks.append('respond @' + name + ' ' + json.dumps(json.dumps(payload)) + ' ' + str(status) + '\n')
    return ''.join(chunks).encode()


def desired_block(block, paused):
    if block.count(IMPORT) > 1:
        raise ValueError('Duplicate admission import; inspect the configuration.')
    clean = block.replace(IMPORT, '')
    if not clean.endswith('}\n'):
        raise ValueError('Unexpected Astra block ending.')
    return clean[:-2] + IMPORT + '}\n' if paused else clean


def load_ops():
    spec = importlib.util.spec_from_file_location('astra_service_ops', OPS)
    ops = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ops)
    return ops


def verify(ops, paused):
    deadline = time.monotonic() + 30
    while True:
        try:
            ops.health(proxy=True, deadline=deadline)
            status, _, body = ops.curl('/api/new-game-policy', timeout=ops.probe_timeout(deadline))
            if paused:
                if status != 200 or json.loads(body) != policy():
                    raise RuntimeError('Admission policy is not confirmed.')
                # No credentials/body: even a broken gate cannot create a game.
                output = ops.command([ops.CURL, '--silent', '--show-error', '--noproxy', '*',
                    '--max-time', '5', '--resolve', ops.DOMAIN + ':443:127.0.0.1',
                    '--request', 'POST', 'https://' + ops.DOMAIN + '/api/games',
                    '--write-out', '\n%{http_code}'])
                payload, code = output.rsplit('\n', 1)
                if code != '503' or json.loads(payload).get('code') != 'new_games_paused':
                    raise RuntimeError('New-game denial is not confirmed.')
            elif status != 404 and (status != 200 or json.loads(body).get('new_games_available') is not True):
                raise RuntimeError('Reopened admission policy is not confirmed.')
            return
        except (ops.SafetyError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('pause', 'open'))
    args = parser.parse_args()
    ops = load_ops()
    paused = args.action == 'pause'
    flag = ops.DATA / 'new-games-paused'
    with ops.lock(ops.CONFIG_LOCK):
        if ops.STATE_FILE.exists():
            raise RuntimeError('Astra maintenance checkpoint exists; finish that operation first.')
        before = ops.CADDYFILE.read_bytes()
        original = ops.site_block(before.decode())
        ops.normal_block(original.replace(IMPORT, ''))
        desired = desired_block(original, paused)
        candidate = ops.replace_site(before.decode(), original, desired).encode()
        info = ops.CADDYFILE.stat()
        prior_fragment = FRAGMENT.read_bytes() if FRAGMENT.exists() else None
        if prior_fragment is not None and prior_fragment != fragment():
            raise RuntimeError('Admission fragment was changed independently; inspect it first.')
        prior_flag = flag.exists()
        if DROPIN.exists() and DROPIN.read_bytes() != DROPIN_CONTENT:
            raise RuntimeError('Admission sandbox drop-in differs; inspect it first.')
        # Keep a private full-config backup, but rollback edits ONLY our Astra block.
        ops.STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        ops.atomic_write(ops.STATE_DIR / ('admission-' + str(time.time_ns()) + '.backup'), before)
        fd, name = tempfile.mkstemp(prefix='.admission-check-', dir=ops.CADDYFILE.parent)
        import os
        os.close(fd)
        check = Path(name)
        installed = False
        try:
            ops.atomic_write(FRAGMENT, fragment(), owner=(info.st_uid, info.st_gid))
            ops.atomic_write(check, candidate, owner=(info.st_uid, info.st_gid))
            ops.validate_config(check, gated=False)
            # The service hides /home except explicit read-only bind mounts.
            # Expose just this fragment; retain the harmless optional mount on reopen.
            DROPIN.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            ops.atomic_write(DROPIN, DROPIN_CONTENT, mode=0o644)
            ops.command([ops.SYSTEMCTL, 'daemon-reload'])
            if ops.CADDYFILE.read_bytes() != before:
                raise RuntimeError('Caddyfile changed during validation; refusing to overwrite it.')
            if paused:
                ops.atomic_write(flag, b'New games paused for API costs.\n', owner=(info.st_uid, info.st_gid))
            else:
                flag.unlink(missing_ok=True)
            ops.atomic_write(ops.CADDYFILE, candidate, owner=(info.st_uid, info.st_gid), mode=info.st_mode & 0o777)
            installed = True
            ops.control('restart', ops.PROXY)
            verify(ops, paused)
        except BaseException:
            if installed:
                current = ops.CADDYFILE.read_bytes()
                restored = ops.replace_site(current.decode(), desired, original).encode()
                ops.atomic_write(check, restored, owner=(info.st_uid, info.st_gid))
                ops.validate_config(check, gated=False)
                if ops.CADDYFILE.read_bytes() != current:
                    raise RuntimeError('Proxy changed during rollback; inspect manually.')
                ops.atomic_write(ops.CADDYFILE, restored, owner=(info.st_uid, info.st_gid), mode=info.st_mode & 0o777)
            if prior_flag:
                ops.atomic_write(flag, b'New games paused.\n', owner=(info.st_uid, info.st_gid))
            else:
                flag.unlink(missing_ok=True)
            if installed:
                ops.control('restart', ops.PROXY)
                verify(ops, IMPORT in original)
            if prior_fragment is None:
                FRAGMENT.unlink(missing_ok=True)
            raise
        finally:
            check.unlink(missing_ok=True)
    print('New games are paused; existing games remain playable.' if paused else 'New games are open again.')
    print('Neither chess application was stopped or restarted.')


if __name__ == '__main__':
    main()
