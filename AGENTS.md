# Rules for anyone (human or AI) working on this repo

## Work arrives on `main` through pull requests that the owner merges

`main` is the default branch and the version people see. Agents never change it
directly. The owner reviews and merges every change.

- **Start from an up-to-date `main`:** `git checkout main && git pull`, then
  create a new branch for your work.
- **Never push to `main`, and never merge pull requests yourself.** No
  `gh pr merge`, no pushing or merging into `main`.
- **When your work is done, open a pull request into `main`**
  (`gh pr create --base main`). Give it a plain-English title and description of
  what changed and why, then **give the owner the PR link** at the end of the
  session so they can merge it.
- **Check for unmerged work before you start.** Run
  `gh pr list --state open`. If a PR is still open, tell the owner and ask
  whether they want to merge it first. Don't quietly stack new work on top of
  an unmerged branch. This is how BEAR 0.2 once sat unmerged on `bear2` for
  days while `main` showed the old version.
- **One pull request per piece of work.** Merged branches are deleted
  automatically, so don't reuse old branches.
