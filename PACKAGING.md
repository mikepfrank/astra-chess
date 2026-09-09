# Source packages and GitHub updates

The source ZIP and Git bundle are generated from committed Git data. They
include the tools, skills, game evidence, replay pages and notes; they exclude
installed dependencies, caches, logs, temporary clocks and generated packages.
The source ZIP is sufficient to inspect/run the project with [SETUP.md](SETUP.md).
The bundle also preserves the local commit history and refs for restoration.

From a clean committed checkout with Python and Git available:

```text
python package_repo.py
```

This writes `dist/astra-chess-<commit>.zip`, `.bundle`, `.manifest.json`, and
`.sha256`. The manifest records the full source commit, every source file's
SHA-256, both archive hashes and the bundle's refs. The script checks the
bundle and refuses to package an uncommitted working tree. `dist/` is ignored
to avoid committing archives back into themselves.

To restore the history, use the generated filename in place of `FILE.bundle`:

```text
git clone FILE.bundle restored-astra-chess
```

The ZIP contains a single source directory and no `.git` directory. The bundle
is a transport/backup artifact; it does not install Python or browser tools.
Neither packaging nor restoring pushes to a remote or starts a game.

## Configured GitHub remote

The repository is published at
[mikepfrank/astra-chess](https://github.com/mikepfrank/astra-chess), with local
branch `main` tracking `origin/main`. The configured `origin` is
`https://github.com/mikepfrank/astra-chess.git`. The initial handoff is complete;
do not add another remote or rename the branch for routine updates.

After reviewing and committing the intended changes, inspect and push with:

```text
git status --short
git remote -v
git push origin main
```

If the remote has diverged, fetch and reconcile its commits before pushing;
do not force-push. No `LICENSE` file has been added. The package preserves
historical paths and the existing Git author identity.

The current inventory includes 11 session games, nine standalone replay archives,
and four engine-assisted trials, through game 11's draw against Li (2000).
See the [game list](README.md#replay-collection) and
[equipment inventory](REPRODUCIBILITY.md#what-is-preserved). Run `package_repo.py`
again from a clean new commit to include subsequent changes; existing bundles
and ZIPs retain the exact earlier commit named in their manifests.

GitHub pushes and local packaging do not deploy Netlify pages. Mike publishes
each standalone replay and the collection index separately. The staged own-time
control is implemented and was used in game 11; any next playing experiment
remains separate from this publication workflow.
