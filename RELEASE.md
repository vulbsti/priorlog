# Releasing priorlog

None of the go-public or publish steps below have been run. The repo is private, and nothing has
been published to PyPI or anywhere else. These are the exact steps for the owner, in order, from `~/proj/oss/priorlog`.

## 0. Private repo (done)

The private repo exists at https://github.com/vulbsti/priorlog, with `main` and the `v0.1.0` tag
pushed. Before going public, check CI (`.github/workflows/ci.yml`: ruff plus pytest on Linux and macOS, Python 3.11 to 3.13) to
pass:

```bash
GH_TOKEN=$(gh auth token -u vulbsti) gh run list --repo vulbsti/priorlog --limit 3
```

## 1. Final checks before going public

The history with personal strings is already replaced: the repo is recreated from one clean
commit, and the old history is kept private as `vulbsti/priorlog-history` (BLOCKED.md B2).

```bash
docker run --rm -v "$PWD:/r" zricethezav/gitleaks git /r
```

```bash
git log --format='%ae' | sort -u
```

The gitleaks scan must report `no leaks found`, and the only author email should be
`29302849+vulbsti@users.noreply.github.com`.

## 2. Make the repository public

```bash
GH_TOKEN=$(gh auth token -u vulbsti) gh repo edit vulbsti/priorlog --visibility public --accept-visibility-change-consequences
```

Then turn on private vulnerability reporting, which SECURITY.md points reporters to:

```bash
GH_TOKEN=$(gh auth token -u vulbsti) gh api -X PUT repos/vulbsti/priorlog/private-vulnerability-reporting
```

Add topics so people can find it:

```bash
GH_TOKEN=$(gh auth token -u vulbsti) gh repo edit vulbsti/priorlog --add-topic mcp --add-topic claude-code --add-topic codex --add-topic agent-memory --add-topic sqlite
```

## 3. GitHub release

```bash
awk '/^## \[0\.1\.0\]/{on=1} on&&/^(## \[|\[[^]]+\]: )/&&!/^## \[0\.1\.0\]/{exit} on' CHANGELOG.md > /tmp/priorlog-notes.md && GH_TOKEN=$(gh auth token -u vulbsti) gh release create v0.1.0 --repo vulbsti/priorlog --title "priorlog 0.1.0" --notes-file /tmp/priorlog-notes.md
```

## 4. Publish to PyPI

Building is safe to run any time:

```bash
uv build
```

Publishing needs a PyPI API token for the `priorlog` project. Supply it through the environment,
and never put it in a file in the repo:

```bash
UV_PUBLISH_TOKEN=<pypi-token> uv publish
```

Check that it installs from PyPI in a clean environment:

```bash
uv tool install priorlog && priorlog --version
```

After publishing, the README install line can become `uv tool install priorlog`.

## 5. Optional: list it in the MCP registry and plugin marketplaces

Not done, and not required. Do this only after the repo is public and the PyPI package exists.

## Releasing later versions

See [CONTRIBUTING.md](CONTRIBUTING.md#releases-maintainer): bump the version in `pyproject.toml` and
`src/priorlog/__init__.py`, update `CHANGELOG.md`, tag `vX.Y.Z`, push the tag, then repeat steps 3
and 4.
