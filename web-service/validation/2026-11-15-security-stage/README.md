# Security maintenance — step 1 completed

November 15, 2026 local / November 16 UTC. Mike approved the staged maintenance
plan and explicitly requested a status report and return to the session prompt
after each major step. **This checkpoint completes preparation only. Stop here
before draining, backup/snapshot, OS installation, reboot or promotion.**

## Prepared artifacts

| Component | Ready candidate | Evidence / boundary |
|---|---|---|
| OS | AL2023 `2023.12.20261112`, 274 RPMs, about 395 MB | All RPM signatures verified; checksums retained. DNF used `--downloadonly`. Installed RPM inventory unchanged. |
| Both private Pythons | Python 3.12.16, OpenSSL 3.5.9, Expat 2.10.0 | Archive digest checked against release asset metadata and published checksum file. SQLite remains 3.53.1; no critical finding established for that version in the survey. |
| Both private venvs | certifi 2026.10.23, pip 26.3; all other application pins retained | Built and dependency-checked both in isolated staging and at final unused runtime paths. Wheels verified against PyPI digests. Source-only chess 1.11.2 was built from its verified original source with recorded build-tool versions. |
| Shared proxy | Caddy 2.11.9, Go 1.27.4, x/net 0.62.0, compress 1.20.4 | Security build and isolated proxy tests passed. Full live configuration adapts identically. No live binary/config changes. |
| Codex | Complete 0.169.0 standalone bundle staged | Initial credential-free startup/schema probes passed for both profiles. Full integration audit is still required; production remains 0.154.0. |

Remote staging root: `/home/ec2-user/chess-security-stage-20261115`.
The OS package set is in `os/rpms`. Do not run `dnf clean packages` before the
planned transaction; reverify the manifest and resolved transaction before use.

Final, **inactive** private Python candidates are already installed at:

- Astra runtime: `/home/astra/.local/share/astra-chess-runtime/python/cpython-3.12.16-linux-x86_64-gnu`
- Astra venv: `/home/astra/.local/share/astra-chess-runtime/venvs/security-20261115`
- Arcturus runtime: `/home/or-chess/.local/share/or-chess-runtime/python/cpython-3.12.16-linux-x86_64-gnu`
- Arcturus venv: `/home/or-chess/.local/share/or-chess-runtime/venvs/security-20261115`

The new venvs were created at these final paths as their service users, avoiding
relocation/shebang problems. Each runtime tree also contains the verified
wheelhouse and hashed lock under `security-staging/20261115/`. Both active
repository `.venv` directories remain ordinary directories with unchanged
inodes and `pyvenv.cfg` contents. Astra's unversioned Python alias was not changed.
Production app/notifier sandbox checks of these final candidates are still
required at activation; the isolated fixture results do not substitute for them.

## Validation performed

| Suite | Result |
|---|---|
| Exact deployed Astra source, candidate Python/dependencies | 282 tests: 279 passed, 3 Windows-only skips, no failures |
| Exact deployed Arcturus source, candidate Python/dependencies | 594 tests: 591 passed, 3 Windows-only skips, no failures |
| Candidate dependency consistency | `pip check` passed for both isolated venvs and both final-path venvs |
| Caddy | Verified TLS/HTTP1/HTTP2, POST/header forwarding, SSE, gzip/zstd, redirects and WebSocket checks passed |
| Caddy vulnerability scan | Zero called-symbol or imported-package findings in the scanned database; one module-only obsolete OpenPGP alert concerns code absent from the build |
| Installed lifecycle helpers | Both `--check` entrypoints passed; current Astra admission import supported |
| Live sites at checkpoint | Both `/health` routes returned 200 and `{"ok":true}`; original app/proxy PIDs unchanged |

Fixture tests used temporary systemd units with `PrivateNetwork=yes`, private
temporary directories, inaccessible production service homes/SSH/AWS paths,
clean environments, one CPU maximum, 2 GiB memory maximum, and nice level 10.
They made no real model calls or emails and did not use live game databases.
Tests were run against archives of the actual deployed commits, not unrelated
newer branch code. The Windows-only skips cover job-object cleanup and DPAPI.

The Caddy scan discovered an additional reachable vendor-High compression
vulnerability after the initial survey; the final build includes its patch.
See [Caddy evidence](caddy-stage.md) for source advisory, full provenance,
reachability qualifications and exact binary hash. Its production configuration
was adapted without provisioning live TLS storage or contacting ACME.

## Source checkpoints and artifact retention

Arcturus preparation stays on `codex/openrouter-chess`; its only application
dependency change is the certifi pin. Astra's separate
`codex/astra-security-20261115` worktree was created from exact deployed
`60bc178f3b442a2c333ed35dc304a99e17106b00`; it likewise changes only certifi and
an explanatory comment. Main and the existing hosted development branch were
not modified. Neither source change has been deployed.

The Python staging helper now pins its build tools and refuses to overwrite a
sealed candidate. Do not rerun a build over tested artifacts. Activation must
consume the retained hashed wheel set; a new build gets a separately reviewed
directory and new test evidence. Existing cached source/runtime trees are not
claimed to be freshly reproduced merely by invoking the helper again.

Evidence files:

- [OS download-only result](os-download-result.json) and [RPM signatures/checksums](os-rpm-manifest.json)
- [Python runtime](python-runtime-manifest.json), [wheel provenance](python-wheel-manifest.json), [build tools](python-build-tool-manifest.json), and [hashed requirements](python-requirements-hashed.txt)
- [Fixture outcomes](python-fixture-results.json), [final-path candidates](python-final-path-candidates.json), and [sealed artifact identities](python-stage-seal.json)
- [Caddy build/test details](caddy-stage.md) and [complete manifest](caddy-stage.json)
- [Codex assessment and outstanding tests](codex-assessment.md)
- [Unchanged production processes, OS and health](production-unchanged.json)

## Next major step — coordinate, drain, back up and snapshot

Follow the [maintenance/recovery runbook](maintenance-runbook.md). First agree
Mike's availability and the AWS snapshot workflow. He has included
`gpt2-public.service` and `gpt2-codex.service` in scope; the
[GPT-2 deployment addendum](gpt2-maintenance-addendum.md) records the subsequent
read-only review. Finish its newly identified shared-venv certifi preparation,
container assessment and drain procedure before the outage. Public jobs/results
need a 600-second retention lead-in; the private lab uses Docker even when no
containers are running. Preserve all shared proxy routes and private lab state.

Then recheck activity, use both lifecycle down helpers, verify their stopped
checkpoints, back up private state consistently and take/confirm the fresh AWS
snapshot with Mike. **Return to the prompt at that checkpoint before applying
the OS update.** Arrange the pauses while Mike is available so maintenance does
not remain open-ended. Preserve Astra's new-game pause, all saved games and
Codex threads, notifier delivery state, credentials and the Arcturus budget.

Subsequent separately reported stages are OS update/reboot, private-runtime and
proxy activation plus regression tests, and public reopening. Codex promotion
remains separate until its full compatibility tests pass. Real AI smoke tests
are approved for the later validation stage; no real email sends are included.
