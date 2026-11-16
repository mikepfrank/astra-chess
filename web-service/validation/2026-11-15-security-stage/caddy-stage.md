# Caddy security candidate — staging completed

November 15 local / November 16 UTC, 2026. **Not deployed.** The existing Caddy
binary, Caddyfile, new-game admission fragment, services and their PIDs remain
unchanged. No active TLS storage was used or modified, no ACME requests were
made, and no model calls or email sends occurred.

## Candidate and provenance

- Remote candidate: `/home/ec2-user/chess-security-stage-20261115/caddy/bin/caddy`
- Caddy `v2.11.9`, built from checksum-database-verified Go modules with
  **Go 1.27.4**, `CGO_ENABLED=0`, `-trimpath`, and the standard module set.
- Explicit security dependency overrides: `golang.org/x/net v0.62.0` and
  `github.com/klauspost/compress v1.20.4`.
- Binary SHA-256:
  `e8903acf0e525a53d9ad7c8d72b10bc63b71392ff39f9b7786c15d51a0639d01`.
- Go archive SHA-256 was checked against the [official download metadata](https://go.dev/dl/?mode=json):
  `7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840`.
- Go module verification passed. Full module versions/checksums, compiler build
  metadata, `go.mod`, `go.sum`, and binary identity are in [caddy-stage.json](caddy-stage.json).
- This is a reproducible custom security build of Caddy 2.11.9, not an assertion
  that the stock release archive contains the later Go fixes.

The reusable [staging helper](../../tools/ops/stage_caddy_security.py) supports
`build`, `test`, `audit` as `ec2-user`, and read-only `compare` through sudo.
All caches/downloads/builds and loopback fixtures remain under the private
staging directory. Compilation used nice level 10 and two Go workers.

## Security checks

Go's pinned `govulncheck v1.9.0` source/symbol scan initially identified a
reachable compression-library finding, [GO-2026-6865 / CVE-2026-116591](https://github.com/klauspost/compress/security/advisories/GHSA-fpmh-frq8-7rj8).
This vendor-rated High panic issue is fixed from 1.20.2; the candidate now uses
the current 1.20.4 patch release. x/net 0.62.0 also covers the HTML-parser fixes
after 0.60.0's HTTP/2 fixes. Go 1.27.4 supplies the November 10 standard-library
security patches.

The final scan found **zero called-symbol findings and zero imported-package
findings**. It retained one module-level advisory:
[GO-2026-5932](https://pkg.go.dev/vuln/GO-2026-5932), concerning obsolete
`golang.org/x/crypto/openpgp` code. A separate `go list -deps` of all 1,028 build
packages confirmed no OpenPGP package is imported. No extra x/crypto upgrade was
made just to hide a warning for code absent from the binary.

The database identified its last modification as November 11, 2026. This scan
is evidence against that database snapshot, not a proof of absence of unknown
vulnerabilities. JSON-mode scanner return codes alone are insufficient: the
finding objects were examined explicitly.

## Regression results

All isolated candidate checks passed:

- Fixture configuration validation/provisioning, admin API off, automatic HTTPS
  off, and private generated certificate/storage.
- HTTP/1 POST body, custom header and forwarded-protocol handling.
- Verified-certificate TLS over HTTP/1 and negotiated HTTP/2.
- Streaming SSE over HTTP/2.
- gzip and zstd response compression/decompression round trips.
- Redirect handling and WebSocket handshake/echo through the proxy.
- All fixture listeners bound only to dynamically chosen `127.0.0.1` high ports;
  fixture processes were terminated cleanly.

Both old and candidate Caddy adapted the **entire actual live Caddyfile as the
`astra` user**. Their canonical JSON configurations were identical, including
the imported Astra new-game admission policy. All 132 existing standard modules
are retained; the candidate has 136 total, adding four upstream standard
modules. There are no missing modules.

The real configuration was **adapted, not provisioned or started**. The private
fixture separately tested provisioning and runtime behavior. Final production
namespace/TLS-storage validation remains part of the gated activation stage.

The shared proxy also serves `gpt2-chat.com`, `test.gpt2-chat.com`,
`codex-test.gpt2-chat.com`, and `gpt2-chat.arcturuschess.com`. Preserve these routes
and coordinate their short proxy interruption when activating the candidate.

## Activation handoff

Do not promote this candidate during the staging step. After backup/snapshot
and the maintenance checkpoint, verify its SHA-256 again; preserve current
binary ownership/mode and any service capability/bind-path requirements. Keep
the old executable for rollback. Validate the complete then-current shared
configuration inside the real proxy sandbox before restart, and check every
public hostname afterward. Preserve the disabled admin API and current `h1 h2`
protocol policy. Do not replace the live Caddyfile with an older captured copy.
