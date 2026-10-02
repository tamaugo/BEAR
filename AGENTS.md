# Rules for anyone (human or AI) working on this repo

## `main` must always hold the latest version

`main` is the default branch and the version people see. Work left on a side
branch is invisible, and that already happened once: BEAR 0.2 sat unmerged on
`bear2` for days while `main` showed the old version.

- Small changes: commit and push straight to `main`.
- Bigger changes: a branch plus a pull request is fine, but **merge the PR into
  `main` before you finish the session** (`gh pr merge <n> --merge`). Don't end
  with an open PR or an unmerged branch unless the owner explicitly asks you to.
- Before you finish, check that nothing has been left behind:
  `git fetch --all && git branch -r --no-merged origin/main` should print nothing.
- After a PR merges, GitHub deletes its branch automatically, so don't keep or
  reuse old branches. Start new work from an up-to-date `main`.
