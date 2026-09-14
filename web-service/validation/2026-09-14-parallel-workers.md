# Arcturus two-worker trial, September 14, 2026

## Change and boundaries

One existing web supervisor can admit two distinct game actions concurrently.
Each action retains its own Codex process, home, thread and gateway. The
supervisor still serializes work within each game. OpenRouter configuration
permits one or two workers; other profiles and local defaults are unchanged.
The Arcturus unit selects two workers and raises its aggregate CPU ceiling from
50% to 200%. Its task/thread cap rises from 64 to 128, as required by the
native Linux test below; the 2 GiB memory cap and lower scheduling priority
remain. This does not create a second web process or a second database owner.

The shared OpenRouter budget check waits up to 30 seconds for the existing
cross-process lock, retrying every 50 ms. Acquisition is bounded; the existing
telemetry request has its own HTTP timeout. Only the usage read/check/write is
serialized, not model inference. An exhausted lock wait fails closed. The
existing $50 usage-delta guard and $5 reserve remain, with the same limitation
that provider usage can lag requests already in flight. Daily token admission
and settlement remain transactional across the two active games.

Max reasoning, 32,768 output tokens, 250,000-token compaction, the 200-million
daily allowance and the soft 120-second own-turn target are unchanged. This
work does not modify the original Astra service or any recorded game. The
deployment briefly gated only Arcturus at Caddy, then restored its exact original
configuration bytes and inode without restarting Caddy.

## Local validation

Windows: 92 focused tests passed across `test_openrouter_setup.py` (29),
`test_parallel_workers.py` (6), `test_player_profiles.py` (25),
`test_openrouter_service_checks.py` (6), and `test_openrouter_gateway.py` (26).

The new scheduler tests exercise simultaneous games and synthetic queries,
per-game proof/context isolation, a third queued game with no running clock,
same-game coalescing, independent cancellation/provider failure, and token
reservation/settlement when another game is active. Budget tests exercise
actual cross-process lock contention, delayed acquisition and timeout without
a provider fetch or ledger mutation.

`tests/audit_parallel_codex.py` passed with native Windows Codex
`0.154.0-alpha.6.2`. Two native processes met at overlapping mocked upstream
requests both before and after restarting and resuming their separate threads.
Distinct homes, threads, process IDs, gateway ports and gateway credentials
were checked; case-specific tool results and reasoning survived the restart.
Eight mocked requests were made, with no external provider contact, real
credentials or live game data. This validates process/protocol isolation, not
live provider throughput or peak tactical-search memory use.

## Linux and activation

Staged candidate `a85311f` passed 151 focused Linux tests with no skips or
failures. In addition to the five suites above, these covered service behavior,
compaction clocks, retry refunds, supervisor limits, daily allowances and
OpenRouter resource accounting.

The native Codex 0.154.0 audit exposed a real blocker under the original
64-task cap: two CLIs exhausted it, and the gateway could not start a Python
thread for its mocked budget check. The kernel reported `pids.current=64` and
53 task-limit hits. No live service or game was changed.

Repeating the same test in an isolated transient service with 128 tasks passed
both concurrent-request rendezvous and all eight mocked requests, including
same-thread restart. Kernel `pids.peak` was 96, with zero task-limit hits;
`memory.peak` was 80,175,104 bytes (about 76.5 MiB). The CPU and memory ceilings
were 200% and 2 GiB. The final candidate therefore also raises `TasksMax` to 128.
This observed memory peak is for a small mocked context, not full live games.

Final candidate `565c057d2da396f88965db186cf96254231de115` passed the six affected
service checks on Windows and Linux after the task-cap correction. Its native
Linux audit used the exact candidate unit limits with no override. Both
concurrent-request rendezvous, all eight mocked requests, isolated histories
and same-thread restart passed. Kernel task peak was 84, task-limit hits zero,
and synthetic memory peak 77,963,264 bytes (about 74.4 MiB). The private receipt
is bound to the full candidate commit. All live service PIDs were unchanged
during staging tests, and transient units were stopped and collected.

The queue was idle at 21:11:30 UTC. Deployment then validated and temporarily
installed an Arcturus-only HTTP 503 gate with `Retry-After: 30`, verified the
original Astra routes and process, rechecked idle state and the absence of child
processes, stopped only Arcturus, and created a coherent private full-data backup.
It fast-forwarded the experimental checkout and installed the three unit changes:
worker count, CPU ceiling and task cap. The namespace preflight used a named,
bounded transient unit, with explicit cleanup before application startup.

Activation succeeded at the **21:12 UTC / 16:12 CDT** checkpoint. Actual running
process environment selected two workers; actual cgroup limits were
`cpu.max=200000 100000`, `memory.max=2147483648`, and `pids.max=128`. The preflight
confirmed Max, 32,768 output, 250,000 compaction and 200-million daily tokens.
All **13** saved game documents, every database table digest, and private-file
hashes including the shared budget matched before/after deployment. Original
Astra/Caddy PIDs and unit definitions were unchanged. Caddy retained its inode
and PID; the gate restored every original configuration byte.

At 21:12:44 UTC, canonical Arcturus, its legacy alias, and original Astra all
returned HTTPS health 200. There were nine unfinished games, all waiting for
humans, and no active responses, replay builds or reserved tokens. No paid model
request, live chess action, clock refund, or saved player-profile migration was
performed by the deployment. Live provider throughput and memory use with two
long contexts remain observations for normal beta play, not claims from the mock.

Private receipts are retained on the host: the backup set is
`parallel-workers-20260914T211203Z`; the restored maintenance-gate receipt is
`gate-079ouu4l`; native audit receipts are under
`operator-checks/parallel-native-565c057/`. These contain operator evidence and
are not public replay artifacts.

The successfully used maintenance gate is preserved as
`tools/ops/arcturus_maintenance_gate.py`, resolving the reviewed activation
primitives from its sibling module. Five additional offline Windows tests
passed: Arcturus-only edits, unexpected-layout rejection, exact restoration
after a failed deployment body, no mutation on validation failure, and
preservation of unrelated concurrent edits with a manual recovery receipt.
The versioned helper has no standalone apply action; the operations guide
describes its required place around drain, update and restart cleanup.

## Subsequent chat timeout

A read-only inventory at 21:17:44 UTC found a new worker error on an existing
game during the human's turn. The user confirmed sending a sidebar comment.
That action began at approximately 21:15:56, after deployment finished, and
ended at 21:17:15 with `TimeoutError: Player response deadline reached`.
The existing human-turn chat allowance remains 60 seconds; the recorded
compaction pause was 18.897 seconds, explaining the approximately 79-second
wall interval. It did not change the board or create a chess-clock charge.
The live service's task peak was 39 with zero task-limit hits, and memory events
showed no limit hit or OOM. The separate chat timeout policy was left unchanged;
this is an observed remaining behavior, not evidence of a two-worker capacity
failure. The service and all saved games remained available.
