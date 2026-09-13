# Arcturus experimental deployment

This deployment serves `arcturus.astraplayschess.com` from the separate
`or-chess` Linux account. It retains the Codex driver, selects the
`openrouter-glm` profile (`z-ai/glm-5.3-flash:nitro`, high reasoning), and binds
new games to the Arcturus persona. The original Astra account, application
unit, repository and game data remain independently operated.

## Files and boundaries

| Path | Purpose and service access |
| --- | --- |
| `/home/or-chess/astra-chess` | Experimental repository and `web-service/.venv`, read-only |
| `/home/or-chess/.local/share/or-chess-runtime` | Private Python 3.12.14 and full Codex 0.154.0 bundle, read-only |
| `/home/or-chess/.local/share/or-chess` | Private application and audit data, read/write |
| `/home/or-chess/.local/share/or-chess/openrouter-budget.json` | Shared lifetime experiment budget ledger |
| `/home/or-chess/.config/or-chess/service.env` | Mode `0600` credential file, read by PID1 and hidden from the service filesystem |
| `/etc/systemd/system/or-chess.service` | Small system unit, executing as `or-chess:or-chess` |

The unit starts the application directly through the virtual environment's
`python -m uvicorn`, bypassing the original launcher's OpenAI credential loader.
It listens only on `127.0.0.1:8792` and trusts forwarded headers only from
`127.0.0.1`. The real OpenRouter key stays in the application environment; the
Codex child receives an ephemeral loopback-gateway token. OpenAI keys are
explicitly removed from the unit environment.

The private filesystem uses `ProtectHome=tmpfs`, selective binds, and a
read-only system. Resource limits cover the application and its descendants
together: 2 GiB memory, 64 tasks, 1,024 file descriptors, half of one logical
CPU (`CPUQuota=50%`), and `Nice=10`. These reduce interference with production;
they are not a reservation of separate physical resources. Keep the complete
Codex bundle, including its helper executables and resources, in the bound
runtime directory.

## Prepare and validate

Use the experimental checkout and its own virtual environment. The pinned
Python executable is
`/home/or-chess/.local/share/or-chess-runtime/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12`;
Codex is
`/home/or-chess/.local/share/or-chess-runtime/codex/bin/codex`.
Installation alone does not establish their compatibility with the unit.

Create the configuration and data directories as `or-chess:or-chess`, mode
`0700`. Supply `OPENROUTER_API_KEY` through the protected environment file,
without printing it or copying the operator's entire login environment. The
unit supplies the fixed profile, persona, origin, runtime and data settings.
Do not override them in the environment file: environment-file values take
precedence over unit defaults, and the preflight rejects mismatches.

Transfer the existing experiment's budget ledger securely into the data
directory, owned by `or-chess` with mode `0600`. Preserve its initial usage
counters and key fingerprint. **Do not create a fresh baseline for deployment
or a disposable test.** Stop local paid experimentation before transferring
authority to the host; independently writable ledger copies cannot provide a
single coherent admission record. The live service and every paid operator
check use the same `ASTRA_OPENROUTER_BUDGET_PATH` supplied by the unit.

The lifetime allowance remains $50, including other use of the same key since
its saved baseline. New requests stop with $5 or less remaining. This is a
local usage guard; delayed provider accounting and work already in flight mean
it is not a provider-enforced hard cap. Missing, invalid or mismatched ledger
data fails the operator preflight without initializing a replacement.

After transferring the reviewed code and installing its pinned requirements:

```sh
sudo install -o root -g root -m 0644 deploy/or-chess.service /etc/systemd/system/or-chess.service
sudo systemd-analyze verify /etc/systemd/system/or-chess.service
sudo systemctl daemon-reload
sudo /home/or-chess/astra-chess/web-service/.venv/bin/python tools/run_openrouter_service_check.py preflight
sudo /home/or-chess/astra-chess/web-service/.venv/bin/python tools/run_openrouter_service_check.py wire
```

Run those commands from the experimental `web-service` directory. The helper
copies the installed unit's namespace, environment and resource properties
into a transient system unit. It refuses unit drop-ins, which need explicit
reconciliation before this simple parser can represent them accurately.

Every mode first runs the no-network preflight: account and paths, hidden
operator/production files, read-only code/runtime, writable SQLite state,
Python and exact Codex version, resource limits, persona, key presence and
existing private ledger binding. Output contains check results rather than
credential or ledger contents. The wire mode then exercises actual Codex
0.154.0 against the loopback gateway and a mocked upstream. It checks the
exact composed persona instructions and the seven canonical chess tools.
Neither mode makes a model request to OpenRouter. Wire reports are private
under `operator-checks/wire` in the data directory.

The separately authorized paid smoke test runs two model actions, including
thread resume, with disposable game data and the same shared budget ledger:

```sh
sudo /home/or-chess/astra-chess/web-service/.venv/bin/python tools/run_openrouter_service_check.py live --live
```

The launcher refuses this mode while `or-chess.service` is active, avoiding
concurrent players during the check. The explicit `--live` flag is required.
An audit passing on Windows does not replace these Linux namespace checks.

## Activate the hostname

After the checks pass, start the experimental application and verify its
loopback health before admitting public traffic:

```sh
sudo systemctl enable --now or-chess.service
curl --fail http://127.0.0.1:8792/health
```

The new DNS record must reach the host. Preserve the current apex and `www`
routes when adding this separate Caddy site:

```caddyfile
arcturus.astraplayschess.com {
    reverse_proxy 127.0.0.1:8792
}
```

Validate the complete candidate proxy configuration before activation, save
the previous configuration, and preserve the existing mounted file's inode
when updating it. The installed Caddy 2.11.4 supports a `SIGUSR1` config reload
for its command-line configuration even with the administration API disabled;
the planned reload needs verification on the running host. After reloading,
verify the new HTTPS hostname, the existing Astra hostname, and the Caddy
process state. Proxy changes are an operator step separate from installing the
experimental application unit.

To stop experimental traffic, stop `or-chess.service`; retain its private
game records and budget ledger for recovery. Change only the new hostname's
proxy route if rolling back the experiment. Do not reset its spending baseline.
