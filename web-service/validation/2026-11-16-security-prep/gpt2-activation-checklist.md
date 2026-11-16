# GPT-2 post-OS activation checklist

Prepared November 16, 2026. **Future steps only:** stop at Mike's requested
drain/backup/snapshot checkpoint before installing OS updates or following this
activation checklist. Nothing here was executed while writing the checklist.
Keep public and private admission gated until all agreed regression checks pass.

## 1. Confirm the post-reboot baseline

- Both `gpt2-public.service` and `gpt2-codex.service` must remain stopped and
  disabled with valid stopped checkpoints and a verified backup/snapshot.
- Expected pinned OS release: AL2023 `2023.12.20261112`; system Python RPM
  `python3.12-3.12.16-2.amzn2023.0.1`; OpenSSL/OpenSSL-libs
  `3.5.8-1.amzn2023.0.4`. These are the GPT-2 base runtime targets, distinct from
  the chess private builds' OpenSSL 3.5.9. Resolve discrepancies before startup.
- Review failed units and Docker/network state. Verify the lab's internal
  `gpt2-codex-isolated` bridge and `GPT2-CODEX-INPUT` rules before starting it.

Read-only host checks:

```sh
rpm -q system-release python3.12 python3.12-libs openssl openssl-libs
systemctl --failed --no-pager
systemctl show gpt2-public.service gpt2-codex.service -p Id -p ActiveState -p MainPID -p UnitFileState
sudo iptables -S GPT2-CODEX-INPUT
sudo iptables -C INPUT -s 172.30.97.0/24 -j GPT2-CODEX-INPUT
sudo docker network inspect --format '{{.Internal}} {{.Options}} {{.IPAM.Config}}' gpt2-codex-isolated
```

## 2. Verify and retest the unused candidate before switching

| Path / artifact | Expected |
|---|---|
| Original shared venv | `/home/gpt-2/.venvs/gpt2-public` — ordinary directory until switch |
| Tested candidate | `/home/gpt-2/.venvs/gpt2-public-security-20261116` — remains at this exact path |
| Stage | `/home/gpt-2/.local/share/gpt2-security-stage/20261116/python` |
| Recovery directory proposed below | `/home/gpt-2/.venvs/gpt2-public-pre-security-20261116` — must not exist |
| certifi | 2026.10.23; wheel SHA-256 `e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1` |
| Other package versions | Exactly those in `stage-manifest.json` / [preparation report](gpt2-python-preparation.json) |

Reconcile candidate and live non-bytecode files against `candidate-files.json`
and `live-files.json`, including symlink targets/modes. The OS-owned interpreter
symlink destination changes with the OS transaction; the venv must still point
to `/usr/bin/python3.12`, with `sys.base_prefix == '/usr'`. Do not rebuild,
relocate or overwrite the tested venv. Preserve the editable package reference
to `/home/gpt-2/GPT-2-tools/src` and the units' explicit deployed-source
`PYTHONPATH`; neither selects an unrelated development branch.

Run model-free dependency/runtime checks as the service user:

```sh
sudo -u gpt-2 env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PIP_CONFIG_FILE=/dev/null PIP_DISABLE_PIP_VERSION_CHECK=1 /home/gpt-2/.venvs/gpt2-public-security-20261116/bin/python -I -B -m pip check
sudo -u gpt-2 env -i PATH=/usr/bin:/bin /home/gpt-2/.venvs/gpt2-public-security-20261116/bin/python -I -B -c 'import sys,ssl,certifi; assert sys.version_info[:3]==(3,12,16); assert sys.base_prefix=="/usr"; assert ssl.OPENSSL_VERSION.startswith("OpenSSL 3.5.8 "); assert certifi.__version__=="2026.10.23"; ssl.create_default_context(cafile=certifi.where()); print(sys.version.split()[0],ssl.OPENSSL_VERSION,certifi.__version__)'
```

Then repeat the isolated public/lab application fixture suites using
[`gpt2_python_run_fixtures.py`](../../tools/ops/gpt2_python_run_fixtures.py).
From this Windows worktree (PowerShell):

```powershell
Get-Content -Raw web-service/tools/ops/gpt2_python_run_fixtures.py | ssh lightsail python3 -
```

Preserve the earlier `results/*.json`/logs in a uniquely named directory first;
the runner writes new results at the same names. Expected: public 206 and lab
381 passes, zero errors/failures/skips. Units use private networking/home/tmp,
read-only candidate/source/tokenizer, no production state/model cache, one CPU
and 2 GiB. This exercises compiled Torch operations, tokenization, runtime
semantics, TLS construction and mocked app/bridge/gateway behavior. It does not
load GPT-2 weights or perform paid calls. Legacy operator fixtures remain
excluded for the reasons recorded in [preparation notes](gpt2-python-preparation.md).

## 3. Switch only while both GPT-2 services remain stopped

After successful artifact checks, offline tests and the agreed runtime-stage
authorization, this guarded operation preserves the original directory and
creates the live-path symlink. It refuses collisions and restores the original
name if symlink creation fails. It does not start/re-enable anything:

```sh
sudo /usr/bin/python3 - <<'PY'
from pathlib import Path
import os, subprocess
live = Path('/home/gpt-2/.venvs/gpt2-public')
candidate = Path('/home/gpt-2/.venvs/gpt2-public-security-20261116')
backup = Path('/home/gpt-2/.venvs/gpt2-public-pre-security-20261116')
for unit in ('gpt2-public.service', 'gpt2-codex.service'):
    raw = subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','MainPID','-p','UnitFileState'],text=True)
    state = dict(line.split('=',1) for line in raw.splitlines())
    assert state == {'ActiveState':'inactive','MainPID':'0','UnitFileState':'disabled'}, unit
assert live.is_dir() and not live.is_symlink() and live.resolve() == live
assert candidate.is_dir() and not candidate.is_symlink() and candidate.resolve() == candidate
assert not os.path.lexists(backup)
os.rename(live, backup)
try:
    os.symlink(candidate, live)
except BaseException:
    os.rename(backup, live)
    raise
print('Shared venv switched; both services remain stopped.')
PY
```

Confirm ownership/traversal with `namei -l` and `sudo -u gpt-2 readlink -f` for
the original path and its `bin/python`. Do not rewrite `/usr/bin/python3.12`,
the candidate location, release source, model/decoding settings or unit commands.

## 4. Inspect sandbox access, then validate behind the gates

Read-only policy inspection (does not reveal environment values or private URL):

```sh
systemctl show gpt2-public.service gpt2-codex.service -p Id -p User -p Group -p ProtectHome -p ProtectSystem -p PrivateTmp -p NoNewPrivileges -p ReadOnlyPaths -p ReadWritePaths -p BindPaths -p BindReadOnlyPaths -p InaccessiblePaths -p MemoryMax -p MemorySwapMax -p TasksMax
sudo -u gpt-2 readlink -f /home/gpt-2/.venvs/gpt2-public/bin/python
namei -l /home/gpt-2/.venvs/gpt2-public/bin/python
```

Start public first behind the maintained gate, satisfying its 8-GiB available
memory guard; keep preview inactive. Start the lab only after adequate remaining
headroom and successful Docker/network isolation checks. Starting can execute
normal session recovery, so it belongs to the coordinated activation stage;
never start an extra copy against the live private database as a probe.

After each gated start, read that unit's numeric `MainPID`. A read-only mount-
namespace probe can verify that the original venv symlink and new interpreter
are visible to that process, running the same short runtime/TLS check above via:

```sh
# Replace VERIFIED_PID with that service's freshly read positive numeric MainPID.
sudo nsenter --target VERIFIED_PID --mount -- /usr/sbin/runuser -u gpt-2 -- /usr/bin/env -i PATH=/usr/bin:/bin /home/gpt-2/.venvs/gpt2-public/bin/python -I -B -c 'import sys,ssl,certifi; print(sys.executable,sys.version.split()[0],ssl.OPENSSL_VERSION,certifi.__version__); ssl.create_default_context(cafile=certifi.where())'
```

This checks actual mount visibility and account permissions without changing
the running process. It does **not** reproduce all its cgroup/seccomp policy;
the read-only unit inspection and integrated checks remain necessary. Do not
print `/proc/PID/environ` or source either private environment file.

- Verify direct/HTTPS health, public pinned model revision/limits/streaming,
  aliases, clocks/state, memory/OOM logs and absence of unexpected restarts.
- Run one short controlled public GPT-2 generation, streaming and final-result
  retrieval; confirm browser archive continuity. Health alone is insufficient.
- Run no-key lab sandbox/network checks before an approved short end-to-end
  test in a designated disposable session. Preserve real session/thread IDs,
  pending inputs, workspaces and the daily budget; exclude development test
  spend rather than resetting the user's allowance.
- Reopen and restore prior enablement only through the reviewed maintenance
  restoration procedure after the agreed checkpoint. Preserve Astra's separate
  new-game pause and every other shared proxy route.

## 5. Rollback safeguards

Both GPT-2 services must again be stopped before changing the shared path.
Verify `gpt2-public` is the symlink to the exact candidate above and the recorded
rollback path is an ordinary directory. Remove **only that verified symlink**,
then rename the rollback directory to `gpt2-public`; never recursively remove a
venv and never overwrite a colliding path. Restore that original path before
using its console scripts, whose shebangs refer to it.

Retest behind the gate. A venv rollback restores package state only: it does
not undo the upgraded OS Python/OpenSSL. Use the retained host snapshot for
an OS rollback, coordinating IP/host ownership and preventing duplicate active
services. Preserve any newer chats, game data, pending inputs and budget state.
