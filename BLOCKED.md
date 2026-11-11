# Blocked items

Things that need the owner.

## B1. Creating the private GitHub repo: RESOLVED (2026-11-05)

The build session's `gh repo create vulbsti/priorlog --private --source . --push` was refused
twice by the Claude Code auto-mode permission classifier ("Public Data-Sharing Upload"). The
second attempt used the verbatim OSS_STANDARD command. The session did not try to work around
the refusal.

The owner then approved and created the repo: https://github.com/vulbsti/priorlog, **private**,
default branch `main`. `origin` uses HTTPS. Later commits and the `v0.1.0` tag are pushed with
`GH_TOKEN=$(gh auth token -u vulbsti) git push`.

Going public and publishing to PyPI are deliberately left to the owner;
see [RELEASE.md](RELEASE.md).

## B2. Remove personal strings from pushed history before going public: RESOLVED (2026-11-12)

Commits `1251965` and `23f6275` in the first private repo quoted the owner's work handle, employer
domain and home path. The build session could not force-push, so this was left to the owner.

It is resolved by recreating `vulbsti/priorlog` from one clean commit of the current, verified-clean
tree, without the old history. The old repo is kept private as `vulbsti/priorlog-history`. Commit
SHAs cited as evidence elsewhere (`VERIFICATION.md`, `docs/benchmarks.md`, the benchmark JSON)
refer to that old history.
