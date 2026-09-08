# Packaging validation, September 8, 2026

The tools were validated from a true `git archive` of implementation commit
`1c86d787b4c819bf1136e4a7faa588ed63c0de40`, extracted outside the working tree.
The final documentation checkpoint adds this report; each generated package's
manifest names its exact full commit and contains checksums for every source file.

## Inventory

The pre-packaging inventory contained 573 tracked files (14.33 MB), with no
uncommitted changes or missing authored assets. The sole external visualization
matched its versioned copy. Both installed chess skills, including `agents/`
metadata, matched the canonical directories byte-for-byte. The preparation
adds setup/dependency/package files and one regression test to that inventory.

Installed dependencies, logs, Python caches, temporary clocks, scratch output,
and generated `dist/` archives are excluded. A targeted heuristic scan of tracked
text found no common private-key, API-token, bearer-token, credential-assignment
or embedded-URL-password patterns; it is not a guarantee about every possible
secret format. Existing author identity and historical machine paths remain.
No remote was configured, license selected, history rewritten, or files pushed.

## Fresh-source checks

- **140 Python tests passed** in the extracted Git archive using Python 3.12.14
  and an isolated venv containing only the existing `chess==1.11.2` rules package.
  The venv used `--without-pip`; that package was copied from the verified local
  installation. This did not test fresh network package downloads.
- Core CLI help, saved-game recovery, historical evaluation exports, a bounded
  mate proof, opening search and standalone reports ran with Python `-S`, without
  third-party site packages. Opening search reached depth 5; the mate proof
  completed in 14 reported nodes. These were example positions, not a new game.
- The engine fingerprint remains
  `96e9ed243d69eede25b24c4c22248753053ee162b51fd0eb4cc081f47a311174`.
- Exact working-tree/archive bytes match for all six engine Python files,
  291 files in `engine-games/`, 26 in `engine-output/`, and four benchmarks.
- Game 9 export reproduces all 31 rows and 35 recorded source hashes; game 10
  reproduces all 48 rows and 47 hashes. No historical score was recalculated.
- The Black replay rebuild matches embedded data exactly and the entire HTML
  after normalizing its transport line endings. The older White replay's frames
  remain identical; the current builder additionally emits `playerSide: white`
  and explicit score-perspective prose. These are presentation/schema additions,
  not altered historical moves or evaluations.
- All three offline browser suites passed with existing Node 24.19.0,
  Playwright 1.62.1 and Edge: `test_report.cjs`, `test_replay_scores.cjs`, and
  `test_replay_black.cjs`. Output was confined to the temporary checkout.
- ASCII diagram init/show passed without Pillow. Optional PNG output separately
  passed with the existing Pillow 12.3.0 installation.

The historical D3 chart checker launched with its newly configurable browser,
but this run could not finish because the sandbox denied its CDN resources.
The chart's network requirement is documented; the game replays are offline.
No macOS/Linux GUI trial or new assistant-session live game was performed.

## Packaging checks

`package_repo.py` correctly refused an uncommitted working tree. From a clean
commit it produced the source ZIP, full-history bundle, manifest and checksums.
ZIP CRC checks, archive hashes, every source-file hash and runtime-file exclusions
passed. `git bundle verify` passed, and cloning the bundle into a fresh temporary
directory restored the exact HEAD and the byte-preserved evidence. Generated
packages remain outside Git under ignored `dist/`.

The initial pre-fix archive exposed one real failure: Git had normalized
recorded CRLF JSON to LF, invalidating saved source hashes. Preserving original
evidence bytes with `.gitattributes` fixed that test without modifying any saved
hash, position, evaluation or engine algorithm. Ordinary source-text LF and PNG
binary defaults remain intact.

## Next handoff

Mike will create the GitHub repository and supply its URL. Follow `PACKAGING.md`
to inspect the remote and push the local history then. The future staged clock
in `TIME-CONTROL-NEXT.md` remains pending implementation before another game.
