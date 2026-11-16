# GPT-2 private sandbox image: assessment and inactive candidate

Prepared November 16, 2026. This work created a separate candidate Docker image
and disposable no-key test containers. It did **not** change the production
image tag, launcher, service, application state, network or firewall rules.
There were no paid/model calls, emails, production mounts or credentials.

## Findings and candidate

| Component | Live image | Inactive candidate |
|---|---|---|
| Node.js | 22.23.3 | 22.23.5, same supported major line |
| Codex | 0.154.0 | 0.154.0; every file in the `@openai` package tree and entrypoint symlink identical |
| Debian release | Bookworm | Bookworm; 15 installed binary packages updated |
| Brotli | 1.0.9-2+b6 | 1.0.9-2+deb12u1 |
| CA certificates | 20250419~deb12u1 | 20250419~deb12u2 |
| OpenSSL/libssl3 | 3.0.22-1~deb12u1 | 3.0.22-1~deb12u2 |
| Python 3.11 packages | 3.11.2-6+deb12u8 | 3.11.2-6+deb12u9 |
| Expat | 2.5.0-1+deb12u4 | 2.5.0-1+deb12u5 |
| Other updated packages | Older apt, PCRE2, SASL, timezone data | Current signed Bookworm packages at build time; exact list in manifest |

The [Node October advisory](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)
includes High-severity issues affecting Node 22, including the Brotli decoder
memory-corruption flaw. The [November security release](https://nodejs.org/en/blog/vulnerability/november-2026-security-releases)
adds further High fixes and supplies Node 22.23.5. This is a package-level need;
the lab does not expose a public Node HTTP server, and this review does not claim
each listed server CVE is reachable through its Codex wrapper.

The [Debian Brotli tracker](https://security-tracker.debian.org/tracker/CVE-2026-111497)
confirms Bookworm's fix in `1.0.9-2+deb12u1`. Updating Node alone would leave the
system Brotli library unchanged, so both layers were addressed.

Candidate tag: `gpt2-codex-security:20261116-node22.23.5`.
Candidate ID:
`sha256:cd4677302c525c03f02fefe65da2944ec07c6d4bb52aa0bf611a54dc504e71d1`.
Production remains `gpt2-codex-runtime:0.154.0`, ID
`sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb`.

The official Node image was pulled then pinned by digest
`node@sha256:e9f565d32859f0cbfb52125eafe8be39390f24dac302dc3cdf566e8ba3ab21ee`.
The build installs/upgrades through signed Debian repositories and copies the
existing complete Codex npm package tree, avoiding an untested CLI migration.
Docker verified downloaded content digests; no separate publisher signature
verification is claimed. Build limits: 0.5 CPU, 1 GiB RAM/no added swap.

## Validation and scope limits

Both baseline and candidate passed the same isolated probes with UID/GID
1015:1018, the installed custom seccomp profile, read-only root, all capabilities
dropped, no-new-privileges, 768-MiB memory/no added swap, 96-PID ceiling and no
network or host-data mounts:

- Root writes denied (`EROFS`); no effective capabilities or inherited API keys.
- Unprivileged nested Bubblewrap user/network namespace and filesystem command.
- The actual Codex 0.154 command `codex sandbox -- /bin/true`.
- Strict-config app-server initialization over stdio, without starting a turn.
- 305 generated protocol-schema files, identical combined hash:
  `bf9a67cadaa925dc1c8690874b17d39e17abc364b56b9e8cbd3dd074e3255e6c`.

Earlier probe designs failed equally on both images: mounting a new `/proc`
was disallowed, `/tmp` is unsuitable for Codex helper aliases, and this Codex
version does not take a `linux` subcommand after `sandbox`. The final probe uses
an isolated tmpfs home outside `/tmp`, existing supported namespace operations,
and the actual CLI syntax. No production sandbox was relaxed to make tests pass.
Earlier diagnostic reports remain in remote staging for inspection.

The [Debian source-package comparison](gpt2-image-debian-audit.json) uses the
official tracker snapshot and Debian's own version comparator. It identified
27 source-package/CVE pairs with available Bookworm fixes in the baseline;
all 27 are absent from the candidate's remaining findings. This is **not a
zero-vulnerability scan**: 244 open/undetermined tracking entries remain
(68 unimportant, one low, 175 not-yet-assigned urgency), with no recorded fixed
Bookworm version in that snapshot. Do not interpret the empty high-urgency list
as proof none could be high: most entries have no assigned urgency. These need
separate risk/reachability triage if pursuing a fuller container audit. Native
Codex dependencies and npm toolchain dependencies were not exhaustively scanned.

The candidate is ready for gated deployment/real-unit regression testing of
the identified available fixes, with these assessment limits retained. A later
test must exercise the real isolated bridge/gateway and a designated short model
action after Docker/kernel maintenance; the no-network probes do not replace it.

## Deployment and rollback boundaries

During the approved maintenance window, after lab drain/stop and backups, record
and retain the old image ID plus installed launcher. Export/retain image rollback
material with the snapshot. Select the exact candidate image in the root-owned
launcher using the normal controlled deployment procedure; do not loosen its
argument/path checks, mounts, seccomp, network, cleanup or resource limits.
Revalidate image ID and Codex package/schema identities immediately beforehand.
No change to application Codex-version allowlists is needed for this candidate.

Do not use a global Docker prune or assume no running containers means the lab
is unused. Restore the prior launcher/image on regression while preserving
session/workspace/thread/budget state. No promotion was performed by this task.

## Artifacts

Remote staging: `/home/ec2-user/chess-security-stage-20261116/gpt2-image/`.
The 90-MB official tracker JSON and build log remain there; only relevant
sanitized evidence is copied into this repository.

- [Build manifest and artifact hashes](gpt2-image-manifest.json)
- [Baseline inventory](gpt2-image-baseline-inventory.json)
- [Candidate inventory](gpt2-image-candidate-inventory.json)
- [Pinned Dockerfile](gpt2-image-Dockerfile)
- [Debian assessment](gpt2-image-debian-audit.json)
- [Successful sandbox/protocol probes](gpt2-image-probe-results-v3.json)
- Reusable staging/audit/probe scripts in `web-service/tools/ops/gpt2_image_security_*.py`.

The staging script refuses to overwrite a sealed build. Candidate provenance
depends on the retained image and manifests; rebuilding against changing package
repositories is a new candidate that requires a new directory/tag and validation.
