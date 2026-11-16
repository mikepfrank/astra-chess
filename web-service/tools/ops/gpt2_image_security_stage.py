"""Build an inactive GPT-2 Docker candidate; never retag the production image.

Run on Lightsail as ec2-user. Only scratch containers/builds are created. No
production credentials, data mounts, launcher, service or network are changed.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/home/ec2-user/chess-security-stage-20261116/gpt2-image')
LIVE = 'gpt2-codex-runtime:0.154.0'
LIVE_ID = 'sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb'
BASE = 'node@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee'
CANDIDATE = 'gpt2-codex-security:20261116-node22.23.5'


def run(args, timeout=60):
    p = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'Command failed ({p.returncode}): {args[:4]}\n{p.stderr[-1500:]}')
    return p.stdout.strip()


def image_id(name):
    return run(['sudo', 'docker', 'image', 'inspect', '--format', '{{.Id}}', name])


INVENTORY = r'''
import subprocess,json,pathlib,hashlib,ssl,sys
def run(a):
 p=subprocess.run(a,text=True,capture_output=True,check=True)
 return p.stdout.strip()
root=pathlib.Path('/usr/local/lib/node_modules/@openai')
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
rows=run(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n'])
print(json.dumps({'node':run(['node','--version']),'npm':run(['npm','--version']),'codex':run(['codex','--version']),'python':sys.version,'openssl':ssl.OPENSSL_VERSION,'packages':[dict(zip(('package','version','source','source_version'),r.split('\t'))) for r in rows.splitlines()],'codex_files':files,'codex_symlink':str(pathlib.Path('/usr/local/bin/codex').readlink())},sort_keys=True))
'''


def inventory(name):
    return json.loads(run([
        'sudo', 'docker', 'run', '--rm', '--network', 'none', '--read-only',
        '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
        '--memory', '512m', '--memory-swap', '512m', '--cpus', '0.5',
        '--pids-limit', '64', '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m',
        '--entrypoint', 'python3', name, '-c', INVENTORY,
    ]))


def main():
    os.umask(0o077)
    ROOT.mkdir(parents=True, exist_ok=True)
    if (ROOT / 'manifest.json').exists():
        raise SystemExit('Sealed manifest exists; use a new directory/tag for a new build.')
    assert image_id(LIVE) == LIVE_ID, 'Production image differs from reviewed baseline'
    baseline = inventory(LIVE)
    (ROOT / 'baseline-inventory.json').write_text(json.dumps(baseline, indent=2)+'\n')
    dockerfile = f'''FROM {LIVE} AS preserved
FROM {BASE}
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends python3 git ca-certificates curl bubblewrap && rm -rf /var/lib/apt/lists/*
COPY --from=preserved /usr/local/lib/node_modules/@openai /usr/local/lib/node_modules/@openai
RUN ln -s ../lib/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
ENTRYPOINT ["codex"]
'''
    (ROOT / 'Dockerfile').write_text(dockerfile)
    # Legacy builder honors these per-build resource limits and avoids exposing
    # a Docker socket or host directory to package installation steps.
    env = dict(os.environ, DOCKER_BUILDKIT='0')
    with (ROOT / 'build.log').open('w') as log:
        p = subprocess.run(['sudo', 'env', 'DOCKER_BUILDKIT=0', 'docker', 'build',
                            '--memory', '1g', '--memory-swap', '1g',
                            '--cpu-period', '100000', '--cpu-quota', '50000',
                            '--tag', CANDIDATE, str(ROOT)], env=env,
                           stdout=log, stderr=subprocess.STDOUT, timeout=900)
    if p.returncode:
        raise RuntimeError('Candidate build failed; inspect staging build.log')
    candidate = inventory(CANDIDATE)
    (ROOT / 'candidate-inventory.json').write_text(json.dumps(candidate, indent=2)+'\n')
    assert candidate['codex_files'] == baseline['codex_files'], 'Codex package bytes changed'
    assert candidate['codex_symlink'] == baseline['codex_symlink'], 'Codex entrypoint changed'
    assert candidate['codex'] == 'codex-cli 0.154.0'
    assert candidate['node'] == 'v22.23.5'
    assert image_id(LIVE) == LIVE_ID, 'Production image tag changed during staging'
    old = {p['package']:p for p in baseline['packages']}
    new = {p['package']:p for p in candidate['packages']}
    changes = [{'package':k, 'before':old.get(k,{}).get('version'), 'after':new.get(k,{}).get('version')}
               for k in sorted(set(old)|set(new)) if old.get(k,{}).get('version') != new.get(k,{}).get('version')]
    manifest = {'staged_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'production_tag':LIVE, 'production_image_id':LIVE_ID,
                'base_digest':BASE, 'candidate_tag':CANDIDATE,
                'candidate_image_id':image_id(CANDIDATE),
                'codex_unchanged':True,'live_configuration_changed':False,
                'real_credentials_mounted':False,'model_calls':0,
                'package_changes':changes,
                'artifacts':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(ROOT.iterdir()) if p.is_file()}}
    (ROOT / 'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'candidate':manifest['candidate_image_id'], 'package_changes':len(changes),
                      'codex_unchanged':True,'production_tag_unchanged':True}))


if __name__ == '__main__':
    main()
