# GPT-2 shared Python candidate — inactive

Prepared November 16, 2026, approximately 13:31–13:37 America/Chicago.
No live application environment, unit, admission, model, thread, budget or
credential changed. Both GPT-2 services retain their original PIDs (91398 and
196465), with zero restarts. No real generation, paid API calls or emails ran.

## Candidate and provenance

| Item | Result |
|---|---|
| Live shared venv | `/home/gpt-2/.venvs/gpt2-public`, unchanged ordinary directory |
| New unused candidate | `/home/gpt-2/.venvs/gpt2-public-security-20261116` |
| Candidate change | certifi `2026.7.22` → `2026.10.23`; all other package versions retained |
| Original footprint / free disk before staging | 1.2 GiB / 245 GiB |
| Source preservation | Separate `cp -a --reflink=auto` copy; no shared hard links |
| Console/activation paths | Rewritten to the candidate's final path; candidate is not relocated after testing |
| Dependency consistency | `pip check`: no broken requirements |
| Live integrity | Every non-bytecode file, symlink and mode unchanged across staging; original processes unchanged |
| Candidate integrity | All non-bytecode file changes restricted to certifi and relocated bin/activation/pyvenv paths |

Wheel reused from the previously verified chess staging set:
`certifi-2026.10.23-py3-none-any.whl`, SHA-256
`e9b54de76e530bb6cf0ccd036787103acb58fd42ba930ea8bf948ddbaa2f61d1`.
Installation was offline with `--no-index --no-deps`; no new dependency resolution.
The [maintainer Critical advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
identifies 2026.10.18 as the initial patched release. Comparing the loaded trust
sets confirms removal of emSign ECC Root CA G3, emSign Root CA C1 and emSign ECC
Root CA C3. The official patched bundle retains emSign Root CA G1; do not claim
that all roots with the emSign name were removed.

Stage and sealed preparation evidence:
`/home/gpt-2/.local/share/gpt2-security-stage/20261116/python`.
It holds `stage-manifest.json`, complete `live-files.json` and
`candidate-files.json`, copied deployed source inventories, the verified wheel,
fixture runner and test reports/logs. The staging helper refuses an existing
candidate/stage; do not overwrite or rerun it over the tested artifacts.

The live and candidate venvs use `/usr/bin/python3.12`; this preparation tested
Python 3.12.12/OpenSSL 3.2.2. The approved OS transaction changes that base
runtime. Repeat runtime/TLS/import checks and fixtures after reboot before
reopening; this evidence does not claim validation of the future OS runtime.
Torch 2.14.1+cpu, Transformers 5.18.0, tokenizers 0.23.2 and httpx 0.28.1 remain
unchanged. The complete package lists are in [the sanitized report](gpt2-python-preparation.json).

## Fixture results and limits

| Suite / check | Result |
|---|---|
| Public deployed-source application fixtures | 206 passed; no failures, errors or skips |
| Private lab deployed-source application fixtures | 381 passed; no failures, errors or skips |
| Compiled Torch import/dispatch | Tiny two-element tensor computation passed; no checkpoint loaded |
| TLS/HTTP client construction | certifi-backed SSL context and httpx client passed without sending a request |
| Real service generation / native sandbox / paid provider | Not performed in this preparation stage; later integrated checks still required |

The tests ran as `gpt-2` in transient units with `PrivateNetwork=yes`, private
temporary directories, `ProtectHome=tmpfs`, `ProtectSystem=strict`, and
`NoNewPrivileges=yes`. Only copied source, the candidate venv, runner and a
tokenizer-only cache were bound read-only; only a new results directory was
writable. Each run had one CPU, 2 GiB maximum memory, 128 tasks and nice 10.
Credentials, real application state, production model weights and other homes
were unavailable. HTTP/bridge tests used mocks or fixture processes. Some
fixture logs print generation-style messages from fake runners; these are not
production or real GPT-2 inference calls.

The initial broad public suite (239 tests, one unavailable-tokenizer class skip)
had two failures and fourteen errors in historical operator preview/promotion
fixtures because those fixtures demand root-owned temporary files. The candidate
was not changed to address them. The final runs select application fixtures and
exclude the four operator modules (`test_lightsail_preview`,
`test_lightsail_promote`, `test_lightsail_update`,
`test_gpt2_exclusive_preflight`): 36 public and 51 lab operator tests excluded.
Only the pinned tokenizer JSON was copied into the isolated fixture cache to
exercise the additional tokenizer tests without access to model weights. Both
initial and final summaries are preserved; these results do not certify the
legacy deployment scripts or replace tests of the new maintenance helper.

## Later activation and rollback

Activation remains the parent's separately coordinated maintenance step:

1. Both GPT-2 apps must be fully drained, stopped and disabled behind their
   saved maintenance checkpoint; preserve private state and take the snapshot.
2. Recheck artifact/file manifests, candidate ownership, wheel hash and source
   inventories. Use the existing final candidate path; do not move the venv.
3. Rename the ordinary live `.venvs/gpt2-public` directory to a unique verified
   rollback name, then create the original path as a symlink to the tested
   candidate. Abort on unexpected prior links or backup-name collisions.
4. Check the effective systemd sandboxes can resolve the symlink; retain source,
   model, environment, decoding settings and all unrelated packages unchanged.
   Start behind the maintenance gate and run post-OS regression/integration checks.
5. If rollback is needed while stopped, remove only the new verified symlink
   and restore the saved directory to its original path. Do not reset or restore
   old chats/budget state over newer work. Restoring this venv does not roll back
   OS Python/OpenSSL; OS rollback uses the separately retained snapshot.

The `local-gpt2-xl` installation is editable and references
`/home/gpt-2/GPT-2-tools/src`. That path remains unchanged in the candidate;
production units select the deployed source using their explicit `PYTHONPATH`.
Back up `GPT-2-tools` as well as the frozen public and private release trees so
the editable reference is also recoverable. Old renamed venv console scripts
still refer to the original path; restore that path before using them in rollback.

Reusable task sources:

- [Inactive venv builder](../../tools/ops/gpt2_python_stage.py)
- [Isolated unit launcher](../../tools/ops/gpt2_python_run_fixtures.py)
- [Application fixture runner](../../tools/ops/gpt2_python_fixture_runner.py)
