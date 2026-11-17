# Caddy and GPT-2 image preparation recheck

Completed November 17, 2026, with all four applications live. **Preparation
only:** no activation, service restart/reload, production configuration edit,
provider call or email. All app/proxy PIDs and restart counts were unchanged.

[Machine-readable results](caddy-image-results.json) and the
[one-time recheck source](caddy-image-recheck.py) preserve the checks. The source
expects the existing `gpt2_image_security_probe.PROBE` constant encoded into its
`__PROBE64__` placeholder before running; no candidate builders were invoked.

## Caddy

- Candidate SHA-256 remains
  `e8903acf0e525a53d9ad7c8d72b10bc63b71392ff39f9b7786c15d51a0639d01`.
- Version remains Caddy 2.11.9 with the previously reviewed Go 1.27.4 build.
  The compiler archive digest, exact embedded build metadata, `go.mod`, and
  `go.sum` match the retained provenance report.
- Both installed and candidate binaries adapted the current entire live
  configuration as `astra`. Canonical JSON is identical, all 132 existing
  modules are retained, and the candidate has 136 modules. This was adaptation
  only: the live configuration and TLS storage were never provisioned.
- Isolated post-OS fixture tests passed: configuration provisioning using a
  freshly generated private certificate; TLS HTTP/1 and HTTP/2, POST/header
  forwarding, HTTP/2 SSE, gzip/zstd round trips, redirect and WebSocket echo.
  Fixture listeners/processes exited cleanly.
- The fixture ran in a private network/home/tmp namespace, clean environment,
  no-new-privileges, 50% CPU, 768 MiB RAM, 128 tasks and nice 10. Only the
  candidate staging tree was readable; a new unique fixture directory and
  compiler cache were writable. No downloads were allowed. Caddy was not rebuilt.

## GPT-2 sandbox candidate

- Candidate image ID remains
  `sha256:cd4677302c525c03f02fefe65da2944ec07c6d4bb52aa0bf611a54dc504e71d1`.
  All five recorded image-build artifact checksums match their manifest.
- Production tag still resolves to its original
  `sha256:9d9274de90e73ba2e215935f0dfbd09eb5c2fe248ba7a6b3052e45969de496fb`.
  Codex remains the retained 0.154.0 package in the candidate.
- Candidate-only probe passed with no credentials, network or host mounts:
  UID1015, zero capabilities, no-new-privileges, custom seccomp, read-only root,
  nested Bubblewrap, Codex Linux sandbox and app-server initialization.
- The candidate's 305-file generated protocol schema exactly matches the
  previously verified baseline hash. Test limits were 0.5 CPU, 768 MiB with no
  additional swap, 96 PIDs, and private bounded tmpfs directories.

Previous staging reports, production Caddy/config/admission files, and the
production sandbox launcher/seccomp policy all retain their original hashes.
New private fixture evidence is in the uniquely named `fixture-recheck-*`
directory under the Caddy staging tree; existing reports were not overwritten.

## Still required at activation

These checks do not activate either candidate or replace checks inside the real
production mount namespace and with live TLS storage. Caddy's file bind needs
a controlled restart. Image promotion must preserve the root-owned launcher,
custom seccomp/network/resource controls and previous image for rollback, then
exercise actual gateway/provider paths in disposable state. No fresh external
vulnerability-database scan was performed here; prior scan findings and their
database-snapshot qualifications remain applicable.
