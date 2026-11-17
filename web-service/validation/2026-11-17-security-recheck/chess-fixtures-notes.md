# Post-OS chess candidate fixtures

Both full suites passed using the final, unused Python 3.12.16 candidate venvs:

| Suite | Result | Elapsed | Source files matched to retained git archive |
|---|---|---|---|
| Astra | 282 tests: 279 passed, 3 Windows-only skips | 118.38 seconds | 912 |
| Arcturus | 594 tests: 591 passed, 3 Windows-only skips | 169.91 seconds | 1,017 |

The three skips per suite are Windows job-object cleanup and two Windows DPAPI
tests. There were no errors or failures. The test source matches the retained
archives of deployed revisions `60bc178f3b442a2c333ed35dc304a99e17106b00`
(Astra) and `a98784cdafacbe5e6616cc55b0e94a34e8056bf2` (Arcturus).

Tests ran sequentially as their service identities with 50% CPU, 2 GiB memory,
128 tasks, nice 10, private network/home/tmp and a clean environment. Fresh
source copies were owned by the respective users and bound read-only; final
candidate venvs/runtimes were also read-only. Production state/credential paths
were inaccessible, and no real model call or email was possible through the
private network. The source copies were necessary because original staging
trees are ec2-user-owned mode 0700; original source permissions were preserved.

The initial invocation halted before executing tests because its `exists()`
guard rejected the unreadable file placeholder created by systemd's
`InaccessiblePaths`. Only the diagnostic guard changed, to check actual read
access. The successful runs used unchanged candidates and source. The initial
guard-only report remains under
`/var/tmp/chess-security-fixtures-20261117-nr1nca1g`; successful logs and the
original report remain under `/var/tmp/chess-security-fixtures-20261117-ajyas3tb`.
Earlier November 15 fixture evidence was not overwritten.

[Sanitized results](chess-fixtures-postos.json) verify unchanged identities and
restart counts for all four live applications and Caddy. Both disposable
fixture units are unloaded/inactive with PID 0. No production service, gate,
runtime, configuration, source checkout, ledger or credential was modified.

[The test launcher](../../tools/ops/recheck_chess_candidate_fixtures.py) creates
unique disposable copies/results and never promotes a runtime. These isolated
fixture results do not replace actual app/notifier namespace and live-provider
checks after the later authorized activation.
