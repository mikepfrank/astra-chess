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
work does not modify the original Astra service, Caddy or any recorded game.

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

Final candidate validation and idle activation are pending. Record the deployed
commit, effective limits and state-preservation receipt here after activation.
Only Arcturus may be restarted.
