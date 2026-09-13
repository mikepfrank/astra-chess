"""Provision the experimental Linux account from its existing login credential.

Run as or-chess, supplying the existing private experiment budget JSON on stdin.
This makes no provider requests, prints no credential/hash, and refuses a new
baseline or replacement of an existing configuration with different contents.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import sys


def main():
    if os.name != 'posix' or pwd.getpwuid(os.getuid()).pw_name != 'or-chess':
        raise SystemExit('Run as the dedicated or-chess account.')
    root = Path('/home/or-chess')
    if Path.home() != root:
        raise SystemExit('The experimental login home is inconsistent.')
    key = os.environ.get('OPENROUTER_API_KEY', '')
    if not key or any(char in key for char in '\r\n\x00'):
        raise SystemExit('The login environment needs a valid OpenRouter credential.')
    raw = sys.stdin.buffer.read(16385)
    if len(raw) > 16384:
        raise SystemExit('Budget record is too large.')
    ledger = json.loads(raw)
    if ledger.get('version') != 2 or ledger.get('budget_usd') != '50':
        raise SystemExit('An existing version 2 experiment budget is required.')
    if ledger.get('key_sha256') != hashlib.sha256(key.encode()).hexdigest():
        raise SystemExit('The server credential differs from the recorded experiment.')
    os.umask(0o077)
    data = root / '.local/share/or-chess'
    config = root / '.config/or-chess'
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.mkdir(parents=True, exist_ok=True, mode=0o700)
    budget_path = data / 'openrouter-budget.json'
    # Full validation is performed by the normal spending guard and preflight.
    values = ((budget_path, json.dumps(ledger, indent=2) + '\n'),
              (config / 'service.env', 'OPENROUTER_API_KEY=' + json.dumps(key) + '\n'))
    for path, content in values:
        if path.is_symlink():
            raise SystemExit('Refusing a symlink configuration target.')
        if path.exists():
            if path.read_text() != content:
                raise SystemExit('Existing experimental configuration differs; reconcile it before replacing.')
        else:
            with path.open('x', encoding='utf-8') as output:
                output.write(content)
        path.chmod(0o600)
    print('Experimental credential provisioned; original budget baseline retained.')


if __name__ == '__main__':
    main()
