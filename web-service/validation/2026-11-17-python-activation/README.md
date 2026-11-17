# Python and certificate environment activation — complete, paused

Mike confirmed the fresh manual snapshot
`MPF_Lightsail_16GB-pre-runtime-2026-11-17`, restart of the same instance, and
SSH access. Screenshot confirms static IPv4 `16.145.194.176`; the prior snapshot
is retained. No AWS configuration was changed by Codex.

Post-boot checks at 18:59 UTC (12:59 America/Chicago) passed: AL2023
`2023.12.20261112`, kernel `6.1.190-237.442.amzn2023.x86_64`, no failed units,
all four apps and both chess timers inactive/boot-disabled, retained stopped
checkpoints, expected HTTPS gates, active Caddy, active-exited GPT-2 network
unit. Internal Docker network/IPv6/ICC policy and allow-8902-then-drop firewall
rules remain correct. Astra's independent new-game pause remains present.

This stage promotes only the tested private chess Python/venvs and shared GPT-2
certificate environment, keeping originals under unique rollback names. Actual
app/notifier services remain stopped, and gates stay in place. Validation uses
service-equivalent temporary sandboxes without application startup hooks.
Caddy and the GPT-2 container image remain for the next stage; full gated
application startup and integrated provider/generation checks follow those
changes. Codex migration remains a separate audit.

Dependency-only source commits, both based on the exact deployed revisions:

- Astra: `60bc178f3b442a2c333ed35dc304a99e17106b00` ->
  `995a587063bb6a7719f53965f85a4dacfeac5f9c`, branch
  `codex/astra-security-20261115`.
- Arcturus: `a98784cdafacbe5e6616cc55b0e94a34e8056bf2` -> `fa184ab`, branch
  `codex/arcturus-security-20261117`.

Both change only `web-service/requirements.txt`: certifi 2026.7.22 ->
2026.10.23 plus an explanatory comment. They are pushed and were fast-forwarded
onto the two deployed checkouts only after exact base/target/content checks.
Tracked files remain clean. One initial source guard refused before either
merge because the two explanatory comments differ; each exact comment was
reviewed and the corrected checks passed. No application code was changed.

Retain `/var/backups/chess-security/20261117T174804Z` and the prior backup.
Do not invoke up/reopen helpers until the remaining gated checks and agreed
reopening checkpoint. Preserve game/session data, pending inputs, clocks,
budgets, notification delivery state, personas and model settings.

## Applied changes and rollback

| Application | Selected environment | Preserved original |
|---|---|---|
| Astra | `/home/astra/.local/share/astra-chess-runtime/venvs/security-20261115` | `/home/astra/astra-chess/web-service/.venv-pre-security-20261117` |
| Arcturus | `/home/or-chess/.local/share/or-chess-runtime/venvs/security-20261115` | `/home/or-chess/astra-chess/web-service/.venv-pre-security-20261117` |
| Both GPT-2 services | `/home/gpt-2/.venvs/gpt2-public-security-20261116` | `/home/gpt-2/.venvs/gpt2-public-pre-security-20261117` |

The original service-facing venv paths are now symlinks to the existing tested
candidates. Candidates were not moved or rebuilt. Chess selects private Python
3.12.16/OpenSSL 3.5.9/SQLite 3.53.1/Expat 2.10.0/pip 26.3; all four apps select
certifi 2026.10.23. GPT-2 retains OS Python 3.12.16/OpenSSL 3.5.8, Torch
2.14.1+cpu and its other existing packages. Astra's old unversioned Python alias
still resolves to 3.12.14 for rollback. Local deployment `.git/info/exclude`
entries protect the new `.venv` symlinks and rollback directories from accidental
tracking; no repository-wide ignore policy was changed.

The staged guarded activation scripts preserve originals, refuse unexpected
states/collisions, validate service-account runtime identities and package sets,
and restore exact original paths on a post-switch failure only while scoped
services remain stopped. GPT-2 also rehashed all 20,634 original and 20,635
candidate non-bytecode inventory entries and verified their ownership. See
[GPT-2 activation](gpt2-activation.json) and [final paths/state](final-state.json).
The chess check's staged manifests match the prior sealed digests; this stage
does not repeat the earlier full Python-archive/installed-RECORD file audit.

Helpers staged under `/home/ec2-user/chess-security-stage-20261116/ops/`:

- `activate_chess_python_security.py`: SHA256 `a3680612a42b8361199c658ce58ff5693e10e622c18ad3847895262eff399d07`.
- `activate_gpt2_security_runtime.py`: SHA256 `2eae1bd03acdea6857450beb85d14b69f49e8a8a200c066c2529fd3599bb5e00`.
- `check_promoted_python_sandboxes.py`: SHA256 `b6136ec42c71bca7d9ebc2b2fd80efbe39bcc3d72684f6aa6bdd1ae71dabf4a6`.

The chess activation helper is deliberately one-shot and requires original
source HEADs/ordinary venv directories; do not rerun `--apply` after promotion.
For manual rollback, first reverify all apps/jobs/timers stopped. Remove only
each verified symlink and rename its recorded original directory back; never
delete either candidate or data. Dependency source rollback, if needed, must be
limited to the certifi-only commits. Do not reset newer game or budget data.

## Validation passed

- 24 new local guard/rollback/unit-replication tests: nine chess activation,
  nine GPT-2 activation, six sandbox-launcher tests. Existing candidate fixture
  evidence (1,457 passes) remains in the earlier recheck directory; no unnecessary
  full-suite repeat was performed for these path switches.
- All four service-equivalent runtime sandboxes verify the new original-path
  symlinks, runtime versions and certificate-backed TLS context construction.
  Both GPT-2 probes additionally pass tiny Torch operations. Probe units omit
  application lifecycle hooks/credential environments, so no app/model loads or
  lab cleanup/recovery runs. They are removed after validation.
- Astra's full installed preflight passes with both EnvironmentFile directives
  preserved separately, including its monitor drop-in. Arcturus's installed
  preflight passes every account, configuration, budget-presence, filesystem,
  password hashing, Codex and resource-limit check. Temporary write probes use
  disposable directories, not real game data.
- Arcturus's mock-provider wire audit passes using retained Codex 0.154.0,
  the real local gateway, seven canonical chess tools, Max effort and 32,768
  output tokens. The fixture's HTTP 400 is its intentional terminal response,
  not a production failure. No external provider or real credentials were used.
- Final state at 19:10 UTC (13:10 America/Chicago): all four apps and both timers
  remain stopped/disabled; gates and retained checkpoints pass; original
  environments exist; Astra admission pause remains; no failed units.
- A final comparison against the retained pre-runtime backup confirms all three
  primary databases, all three maintenance checkpoints and Caddyfile remain
  byte-identical. This is selected-file verification, not a full archive rehash.

See individual JSON reports in this directory. These tests validate deployed
paths and copied service restrictions; they do not replace real-process startup,
generation/provider, notifier dry-run and HTTPS regression checks after the
remaining updates. No paid API calls or test emails occurred this stage.

## Next stage and backup-helper follow-up

Pause at the user-requested major-stage checkpoint. Next activate the staged
Caddy security binary and GPT-2 sandbox image, preserving old artifacts and
isolation controls. Then perform gated integrated regressions and pause before
reopening. Do not start production GPT-2 yet: its lifecycle helper transitions
checkpoints to `started`, so complete stopped-state image/path swaps first.

**Before any new post-runtime application backup, refresh a versioned producer/
verifier bundle.** The November 16 producer's GPT-2 ROOTS entry names only the
former ordinary live venv directory. Tar preserves that path as a symlink now,
so a new backup would omit its target. Include the parent `.venvs` directory or
the explicit live/candidate/rollback set and add a symlink-target coverage test;
do not globally dereference symlinks. Its Docker guard/tag/ID must also be updated
when the image changes. Update dependent helper hash pins as a new reviewed
bundle, retaining the historical scripts. The existing pre-runtime archive is
valid (original venv was an ordinary directory); the whole-instance snapshot
also contains the candidate. Chess runtime roots already cover both candidates.
