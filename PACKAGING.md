# Local package and GitHub handoff

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

## Tomorrow's GitHub handoff

The local branch is currently `master`. No remote is configured, and nothing
has been pushed. After Mike creates the GitHub repository and supplies its
actual URL, inspect the remote state before adding `origin` and pushing the
current branch. If the remote starts empty, the intended operations are:

```text
git remote add origin REPOSITORY_URL
git push -u origin HEAD
```

`REPOSITORY_URL` is a placeholder, not a configured destination. If the new
repository has an initial README or other commits, reconcile those before
pushing; do not force-push or rename the local branch without a reason agreed
with Mike. A public/private selection and license have not been chosen here;
no `LICENSE` was added on Mike's behalf. The package preserves historical
paths and the existing Git author identity rather than rewriting the record.

The next playing experiment is separate from publication. Implement/test the
selected future time control first; choose the stronger opponent with Mike
when he is ready to watch. No new game or scheduled reminder was started tonight.
