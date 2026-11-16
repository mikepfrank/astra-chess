"""Launch staged GPT-2 app fixtures with no production home/data/network access.

Run as ec2-user on the reviewed host, after staging and installing the runner.
Only the unused stage results directory is writable outside private /tmp.
"""
from pathlib import Path
import json
import subprocess

STAGE = Path('/home/gpt-2/.local/share/gpt2-security-stage/20261116/python')
CANDIDATE = '/home/gpt-2/.venvs/gpt2-public-security-20261116'


def main():
    for suite in ('public', 'lab'):
        command = ['sudo', 'systemd-run', '--quiet', '--wait', '--pipe',
                   '--unit=gpt2-security-app-fixtures-' + suite + '-20261116']
        properties = [
            'User=gpt-2', 'Group=gpt-2', 'PrivateNetwork=yes', 'PrivateTmp=yes',
            'NoNewPrivileges=yes', 'ProtectSystem=strict', 'ProtectHome=tmpfs',
            'CPUQuota=100%', 'MemoryMax=2G', 'TasksMax=128', 'Nice=10',
            'RuntimeMaxSec=600', 'BindReadOnlyPaths=' + CANDIDATE,
            f'BindReadOnlyPaths={STAGE}/source-{suite}',
            f'BindReadOnlyPaths={STAGE}/fixture_runner.py',
            f'BindReadOnlyPaths={STAGE}/tokenizer-cache',
            f'BindPaths={STAGE}/results', f'ReadWritePaths={STAGE}/results',
            f'WorkingDirectory={STAGE}/source-{suite}',
        ]
        for value in properties:
            command.extend(['-p', value])
        command.extend([
            '/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'LANG=C.UTF-8',
            'PYTHONDONTWRITEBYTECODE=1', 'HF_HUB_OFFLINE=1',
            'TRANSFORMERS_OFFLINE=1', 'TOKENIZERS_PARALLELISM=false',
            'OMP_NUM_THREADS=1', 'MKL_NUM_THREADS=1',
            f'HF_HUB_CACHE={STAGE}/tokenizer-cache',
            f'PYTHONPATH={STAGE}/source-{suite}/src',
            CANDIDATE + '/bin/python', str(STAGE / 'fixture_runner.py'), suite,
        ])
        result = subprocess.run(command, text=True, capture_output=True)
        # Test fixture output has no access to production secrets or data.
        log = result.stdout + '\n' + result.stderr
        write = subprocess.run(['sudo', '-u', 'gpt-2', 'tee',
                                str(STAGE / 'results' / (suite + '-fixtures.log'))],
                               input=log, text=True, capture_output=True)
        if write.returncode:
            raise RuntimeError('Could not save fixture log')
        print(json.dumps({'suite': suite, 'returncode': result.returncode,
                          'output_tail': log[-4500:]}), flush=True)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
