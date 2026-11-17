# GPT-2 candidate recheck after OS upgrade

November 17, 2026, approximately 06:55–07:00 UTC (00:55–01:00 Chicago).
Preparation only; the candidate remains inactive and both live services kept
their original PIDs (public 3982, private 4373), active state and zero restarts.
No production state, routes, units, runtime links, model settings or credentials
were changed. No real model generation, provider calls or emails ran.

## Artifact checks

[Integrity report](gpt2-artifact-integrity.json): every recorded non-bytecode
file/symlink/mode is unchanged in the live venv (20,634 entries) and candidate
(20,635). Inventory digests also match the prior **committed** preparation
report. The staged certifi 2026.10.23 wheel hash matches its recorded provenance;
`pip check` reports no broken requirements. The candidate remains the same
ordinary directory at its final tested path, with expected service-account
ownership throughout.

The copied and currently deployed selected source trees match the sealed
source manifest, including checking for additions: 41 public and 75 private
files, zero differences. Bytecode/cache files remain excluded as in the original
inventory; no broader claim is made about unrelated files outside those source
directories or runtime paths.

## Isolated post-OS fixtures

[Fixture report](gpt2-postos-fixtures.json): **206 public tests and 381 private
lab tests passed**, with zero failures, errors or skips. The original excluded
operator-only suites remain excluded (36 public/51 lab); these are application
runtime tests, not a recertification of legacy root-owned deployment scripts.

Both suites exercised OS Python **3.12.16**, OpenSSL **3.5.8**, and the candidate
certifi **2026.10.23**. Torch **2.14.1+cpu**, Transformers **5.18.0**, tokenizers
**0.23.2** and httpx **0.28.1** are unchanged. Compiled tiny-tensor operations,
certificate-backed SSL context construction and offline HTTP-client setup pass.
No GPT-2 model weights were loaded.

Suites ran sequentially at **50% of one CPU**, **2 GiB RAM**, 128 tasks, nice 10,
and a ten-minute runtime ceiling in disposable systemd units. The environment
was cleared; networking, HOME and temporary directories were isolated. Only
the candidate, copied source, fixture runner and tokenizer-only cache were
available read-only; real application state, provider credentials and model
cache were not bound into the namespaces.

New host evidence is under:
`/home/gpt-2/.local/share/gpt2-security-stage/20261116/python/recheck-20261117T065759Z/`.
Its fresh results directory was bind-mounted over the runner's expected results
path **inside the temporary namespaces only**, so no runner edit or old-results
overwrite was needed. Hashes confirm all prior result files are unchanged.
Raw fixture logs stay on-host; only sanitized summaries were copied here.

This supports later activation of the prepared certifi venv against the upgraded
OS. Actual production symlink visibility and integrated generation/provider
checks still belong to the later gated activation stage. Before then, retain
the original venv, candidate, manifests and prior evidence; do not rebuild or
relocate the sealed candidate.
