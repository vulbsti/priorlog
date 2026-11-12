# Contributing to priorlog

Thanks for helping. priorlog reads private transcripts, so the bar for changes is simple:
nothing may weaken the guarantees in [SECURITY.md](SECURITY.md), and nothing private may land in
the repository. This file covers setup, tests, adding a harness adapter, fixtures and releases.

By taking part you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Development setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer, on Linux or macOS.
Windows is not supported yet (the sync lock uses `fcntl`; see [docs/ROADMAP.md](docs/ROADMAP.md)).

```bash
git clone https://github.com/vulbsti/priorlog
cd priorlog
uv sync                    # creates .venv with priorlog (editable) and the dev tools
uv run pytest              # the whole suite runs in a few seconds
uv run ruff check .        # lint
uv run ruff format .       # format (CI runs `ruff format --check .`)
uv run priorlog --help     # the CLI from your checkout
```

CI (`.github/workflows/ci.yml`) runs `uv sync --locked`, `ruff check .`, `ruff format --check .`
and `pytest` on ubuntu-latest with Python 3.11, 3.12 and 3.13. A macOS job (Python 3.13) runs only on
manual dispatch (Actions → CI → Run workflow → tick `macos`). Run the same three commands before you open a pull request.

### Trying the CLI without touching your real data

priorlog only reads transcripts, but while developing you may want a separate index and config.
Point it at a throwaway location:

```bash
export PRIORLOG_CONFIG=/tmp/pl/config.toml PRIORLOG_HOME=/tmp/pl/data
uv run priorlog init       # writes /tmp/pl/config.toml; edit the roots to point at test data
uv run priorlog sync
```

## Tests

The suite is small on purpose. Each test exercises a real path end to end (real files on disk,
the real SQLite index, the real MCP client over stdio) and checks a property a user relies on.
There are no mocks of our own code and no tests that only restate an implementation.

| File | What it protects |
| --- | --- |
| `tests/test_adapters.py` | each adapter against its synthetic fixture: what is kept, what is dropped, line ranges |
| `tests/test_sync.py` | incremental sync: no-op second run, appended lines, a growing assistant turn, partial last line, rewritten file |
| `tests/test_citations.py` | every hit has a citation that `read` opens, down to the exact source lines; filters; id resolution |
| `tests/test_redaction.py` | secrets never reach the index, search results or the source view; deny rules; policy re-check |
| `tests/test_mcp.py` | the real MCP server over stdio: tool list, context label, search then read |
| `tests/test_isolation.py` | the full CLI flow writes nothing outside priorlog's own directories |

`tests/conftest.py` copies `tests/fixtures/` into a temporary `HOME` and writes a config that
points every source there, so no test ever reads your real transcripts.

When you add behaviour, add or extend a test only if it guards something a user would notice
breaking. Prefer one assertion-rich test over many tiny ones. A bug fix should come with the
test that would have caught it.

## Adding a harness adapter

An adapter turns one transcript file into messages. It never writes to the database and never
opens a file the policy has not allowed: the sync engine checks the policy, calls the adapter,
and hands the result to `Store`, which redacts and writes it. Read
`src/priorlog/adapters/base.py` first; `adapters/pi.py` is the shortest complete example.

### 1. The contract (`src/priorlog/adapters/base.py`)

Subclass `Adapter` and set a class attribute `harness` (for example `"myagent"`). It becomes the
session id prefix (`myagent:<native id>`) and the value of the `--harness` filter.

| Method | Called | Must |
| --- | --- | --- |
| `discover() -> list[Path]` | once per sync | list candidate files under the configured roots. Only list (glob, `is_dir`); do not open files here. Files the policy denies are skipped after this. |
| `prepare(paths)` | once per sync, after `discover` | optional; see every discovered path before any parse (the Claude adapter uses it to recognise forks). |
| `parse(path, offset, line, carry) -> Batch` | per changed file | read only complete lines from `offset` with `iter_lines`, and return a `Batch`. |
| `post_sync(store, policy)` | after all files | optional; join side metadata. Call `policy.allowed(path)` before opening anything, and write only through `store.enrich_session(...)`. |

What `parse` returns, all from `base.py`:

- `Batch`: `messages`, `sessions`, `links`, `end_offset`, `end_line`, `carry`, `tail`,
  `malformed`, `unknown_types`.
- `Msg(session, role, text, ts, line_start, line_end)`: role is `user`, `assistant` or
  `system`; `line_start`/`line_end` are the 1-based file lines the message came from. They
  become the citation locator, so they must be exact.
- `SessionInfo`: get it with `batch.session(sid, harness, native_id=...)`. Set `cwd`, `branch`,
  `resume_cmd` and `parent_id` when known; call `info.seen(ts)` for every timestamp and
  `info.set_title(text, RANK_FIRST_MESSAGE)` (or a stronger rank) for titles. `None` means
  "unknown, keep what is stored".
- `TurnBuilder(batch, sid)`: merges consecutive assistant pieces into one message per turn.
  Call `add("text", value, ts, line_no, offset)` or `add("tool", name, ts, line_no, offset)`
  for each piece, `flush()` before appending a user message, and `finish()` at the end of
  input. `finish()` marks the last turn as the open `tail`, which the next sync re-reads and
  replaces (agents write one line per content block, so a turn may still be growing).
- `carry`: a small JSON-serialisable dict you return and get back on the next incremental
  parse, for state that only appears early in the file (the Codex and Pi adapters keep the
  native id and cwd there). Start with `Batch(carry=dict(carry))`.

The parse loop always looks like this:

```python
for no, pos, raw in iter_lines(path, offset, line):
    if raw == b"":  # sentinel: where the next sync starts
        b.end_line, b.end_offset = no, pos
        break
    d = loads(raw)  # None for invalid JSON or over-long lines
    if d is None:
        b.malformed += 1
        continue
    ...
turn.finish()
return b
```

Rules for what to index: user text and assistant text, with tool calls reduced to
`[tool: name]` markers. Do not index tool outputs, reasoning or harness-injected context
(`is_injected()` helps). Count line types you do not recognise in `b.unknown_types` so
`priorlog status` can report them; never fail on them.

### 2. Configuration (`src/priorlog/config.py`)

1. Add a `<name>_roots: tuple[Path, ...] = ()` field to `Config`.
2. Add it to the `Config.roots` property. **This is required**: the policy only allows files
   inside `Config.roots`, so if you skip this step every file is denied with
   "outside configured source roots".
3. Read it in `parse()` with `harness_roots("<name>")`, which honours `enabled = false`.
4. Add a `[sources.<name>]` section with `enabled = true` and the default `roots` to
   `DEFAULT_TOML`.
5. Print the root in `cmd_init` (`src/priorlog/cli.py`) so `priorlog init` shows found/not found.

### 3. Register it (`src/priorlog/sync.py`)

Add it to `build_adapters(cfg)`:

```python
if cfg.myagent_roots:
    adapters.append(MyAgentAdapter(cfg.myagent_roots))
```

### 4. Fixture and test

1. Add a small **synthetic** transcript under `tests/fixtures/<name>/...` that mirrors the real
   layout and covers: a user message, a multi-line assistant turn with a tool call, a tool
   output that must not be indexed, injected context that must be dropped, and one unknown line
   type. See the privacy rules below.
2. Point the new root at it in `write_config()` in `tests/conftest.py`.
3. Add one test to `tests/test_adapters.py` in the style of `test_pi_session`: roles in order,
   exact text, exact `(line_start, line_end)` for the assistant turn, and session `cwd`.
4. If the harness has a default location under `HOME`, add it to the copy step in
   `tests/test_isolation.py` so the full install flow covers it.
5. Document the format and defaults in `docs/configuration.md` and add a CHANGELOG entry.

## Privacy rules for fixtures and tests

- Fixtures are **synthetic only**. Never copy a real transcript, even a "harmless" one. Use
  placeholder paths (`/work/demo-app`), invented ids (`aaaaaaaa-1111-...`) and invented content.
- No real names, emails, hostnames, usernames or home directories anywhere in the repository.
- Never commit a string that looks like a secret. Build secret-shaped test values at runtime,
  the way `tests/test_redaction.py` does: split the prefix (`J(["sk-", "ant-", ...])`) and fill
  the body from a seeded `random.Random`. That keeps the gitleaks scan of the history at zero
  findings.
- If you paste output from your own machine into an issue or pull request, redact it first.

## Pull requests

- Keep changes focused; one topic per pull request.
- Run `uv run ruff check .`, `uv run ruff format --check .` and `uv run pytest`.
- Add a line under `## [Unreleased]` in `CHANGELOG.md` for anything a user would notice.
- If you change a guarantee (what is read, what is stored, what is redacted), say so in the
  pull request description and update `SECURITY.md` and `docs/architecture.md`.
- Do not add runtime dependencies without discussing it in an issue first. priorlog depends only
  on `mcp`.

## Releases (maintainer)

1. Bump the version in **both** `pyproject.toml` (`version = "X.Y.Z"`) and
   `src/priorlog/__init__.py` (`__version__ = "X.Y.Z"`).
2. Run `uv lock` so `uv.lock` records the new version (CI uses `uv sync --locked`).
3. Move the `## [Unreleased]` entries in `CHANGELOG.md` under `## [X.Y.Z] - YYYY-MM-DD` and
   update the compare links at the bottom.
4. Run the checks: `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`,
   and `uv run priorlog --version`.
5. Scan the whole history for secrets:

   ```bash
   docker run --rm -v "$PWD:/r" zricethezav/gitleaks git /r
   ```

   It must report no leaks.
6. Commit, then tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin main vX.Y.Z
   ```
