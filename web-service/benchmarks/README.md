# Laptop and Lightsail capacity assessment

Measured September 9, 2026, before deployment. The existing Lightsail instance is
a reasonable first-alpha target with one active Astra worker. Its engine runs
about half as fast as the laptop, but the two tested time-limited positions
completed the same depth and returned the same completed answers on both hosts.
This is a capacity sample, not a playing-strength or sustained-load benchmark.

## Hardware inspected

| | Development laptop | Existing Lightsail server |
| --- | --- | --- |
| CPU | Intel Core i7-13850HX | Intel Xeon Platinum 8175M @ 2.50 GHz |
| Exposed processors | 20 cores / 28 logical processors | 2 vCPUs; guest reports 1 core / 2 threads |
| Memory visible to OS | 31.7 GiB | 7.64 GiB (8 GB plan) |
| Available memory at inspection | 4.8 GiB | 5.08 GiB |
| OS | Windows 11 Pro, build 26200 | Amazon Linux 2023.9.20251208, x86-64 |
| Benchmark Python | CPython 3.12.14 | CPython 3.11.14, already installed |

The laptop is a Dell Precision 7680. The server's non-secret IMDSv2 metadata
reports `t3.large` in `us-west-2`. Its root filesystem has about 105.45 GiB free;
load averages were 0.00 / 0.00 / 0.00 at initial inspection. Several existing
Python and Emacs processes were resident but nearly idle. Swap was absent.
Hardware inventory used Windows CIM and read-only SSH commands. No credentials,
private process arguments or unrelated application content were collected.

The server's default `python3` is 3.9.25, so use the explicitly installed
`python3.11` for the service. `codex` and `node` were absent from ec2-user's PATH.
The bridge currently requires the audited Codex CLI 0.153.4 protocol; matching
Linux binary availability and its effective configuration remain deployment
checks. OpenAI documents [native Linux CLI installation](https://learn.chatgpt.com/docs/codex/cli#install-codex);
no installation was performed during this assessment.

## Identical fixed-work engine searches

Each case ran twice, sequentially within one process on each host. Times below
are arithmetic means. Source hashes, completed depths, node counts and answer
hashes matched across hosts and repetitions; no fixed-work case timed out.

| Case from the first human game | Depth (plies) | Nodes | Laptop seconds | Lightsail seconds | Slowdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| Opening, after 1.e4 | 4 | 5,849 | 0.446 | 0.845 | 1.90x |
| Middlegame, before 10...Nb4 | 4 | 67,190 | 5.070 | 9.631 | 1.90x |
| Forced mate after 24...Rad8 | 6 | 30,636 | 1.373 | 2.708 | 1.97x |

The queries retain the recorded FEN, repetition history, hypothetical moves,
candidate count and search options. Only the depth ceilings and generous time
caps change for fixed-work comparison. The runner calls the same core search
functions, excluding the wrapper's post-search UI diagnostics and file I/O.
It loads the repository's unchanged rules/search/diagnostics source into memory.
No external chess tools, model calls, remote files or installations are used.

These measure the complete available CPU/Python/OS stacks, not isolated CPU
microarchitecture: Python versions differ. They are short tests with the host
mostly idle, not a measurement after CPU burst capacity has been exhausted.

## Current time allowance

Two further tests requested depth 8 with `time_limit=14.5`, leaving approximately
14 seconds of actual search after its reserve. This matches the usual core
search allowance in the live service's 15-second diagnostic query.

| Case | Laptop completed depth / nodes | Lightsail completed depth / nodes |
| --- | --- | --- |
| Opening after 1.e4 | 5 / 183,498 | 5 / 101,537 |
| Middlegame before 10...Nb4 | 4 / 165,453 | 4 / 98,260 |

Both hosts reached the time limit, discarded unfinished deeper iterations and
returned identical completed answers. That does not establish equal depth in
every position: searches near an iteration boundary may finish one fewer ply on
the slower host. Roughly doubling a query's time allowance is a useful starting
estimate for matching laptop work, within the existing turn/clock limits; no
service defaults or clocks were changed here.

The server process peaked at 19.05 MiB in fixed-work tests and 22.30 MiB in the
timed tests. These are whole-process high-water RSS values, cumulative across
the cases in each run. They exclude FastAPI, Codex and long conversation state,
and do not establish a maximum for longer searches. The move-ordering cache can
grow with visited positions. The production supervisor launches a fresh engine
process for each query, releasing its search memory on exit.
Windows and Linux memory figures are not directly comparable: their reporting
APIs differ, and the local driver additionally imports CLI/build helpers that
the emitted remote program does not need. The measurements do not justify
dividing available RAM by 22 MiB to predict player capacity.

## Observed game workload and concurrency

The saved human game contains 43 queries: 41 ordinary analyses and 2 mate probes.
Its ordinary analyses completed depths 4 (7 queries), 5 (28), 6 (5), and 7 (1).
All requested depth 8 and reached their time limit; none returned an unevaluated
fallback. Unrestricted actual-position analyses reached depth 4 or 5; the deeper
results came from restricted or hypothetical searches.

Recorded searches total 565.889 seconds, about 9 minutes 26 seconds, and
7,848,695 nodes. Search per Astra move averaged 20.96 seconds (median 15.39).
Among the 25 reply intervals of at most 120 seconds, search occupied 32.26% of
elapsed time. This is a wall-time duty proxy, not process CPU accounting. Long
interruptions make the whole-game duty fraction misleadingly low.

The engine is single-threaded. The current global `max_workers=1` means one
active model/engine response, with other games queued; idle human turns consume
very little compute. More vCPUs help concurrency rather than the depth of one
unmodified search. The example systemd unit caps the entire service at
`CPUQuota=100%` and `MemoryMax=2G`; revisit these aggregate limits before raising
worker concurrency. Neither the unit nor the running server was modified.

AWS documents a 30% average CPU baseline for the 2-vCPU/8-GB Lightsail plan,
equivalent to 0.6 continuously busy vCPU. One fully busy vCPU is approximately
50% of the instance, above that baseline, but pauses for API reasoning and human
turns let capacity recover. See [AWS's baseline table](https://docs.aws.amazon.com/lightsail/latest/userguide/baseline-cpu-performance.html)
and [burst metrics](https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-viewing-instance-health-metrics.html).
The actual current burst-capacity balance was not inspected; SSH CPU idleness
does not establish that balance. Check it in the Lightsail console during the
first live alpha session, alongside existing services' CPU use.

Recommendation: start with the existing server and one active Astra worker.
Memory and storage appear ample; no GPU is needed because model inference uses
the remote OpenAI API, while this server hosts the CLI, application and tactical
engine. Linux CLI compatibility, long-context RSS and performance under real
concurrent traffic remain untested. Prioritize faster sustained single-core
performance if measurements later require an upgrade, rather than RAM alone.

## Reproduce and inspect

From `web-service`, using the existing development virtual environment. The
fixed-work commands use a 30-second cap per case and two repetitions:

```powershell
./.venv/Scripts/python.exe tools/benchmark_engine.py
./.venv/Scripts/python.exe tools/benchmark_engine.py --emit | ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes ec2-user@lightsail 'timeout 120s python3.11 -B -'
```

For the timed comparison, add these options before `--emit` when applicable:

```text
--case opening-after-e4 --case middlegame-before-Nb4 --depth 8 --seconds 14.5 --repeats 1
```

Raw evidence: [cases](capacity-cases.json),
[laptop fixed-work](laptop-2026-09-09.jsonl),
[Lightsail fixed-work](lightsail-2026-09-09.jsonl),
[laptop timed](laptop-timed-2026-09-09.jsonl),
[Lightsail timed](lightsail-timed-2026-09-09.jsonl).
The JSONL includes runtime versions, exact source hashes, completed depths,
node counts, CPU/wall times, peak memory and answer hashes. Search findings
remain benchmark evidence and do not replace the original in-game evaluations.
