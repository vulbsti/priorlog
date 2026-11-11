# Configuration

priorlog reads one TOML file. `priorlog init` writes a commented default; until a file exists,
the same defaults are used built in, so `priorlog sync` works without running `init` first.

```bash
priorlog init            # writes the default config and lists which roots exist
priorlog init --force    # overwrite an existing config with the default
priorlog --config ./other.toml status   # use a different file for one command
```

Every path in the config is opened read-only. priorlog writes only its config file and its data
directory (see [Where files live](#where-files-live)).

## Where files live

| What | Default | Override |
| --- | --- | --- |
| Config file | `~/.config/priorlog/config.toml` | `--config PATH`, then `$PRIORLOG_CONFIG`, then `$XDG_CONFIG_HOME/priorlog/config.toml` |
| Data directory | `~/.local/share/priorlog/` | `$PRIORLOG_HOME` (used as the directory itself), then `$XDG_DATA_HOME/priorlog/` |
| Index | `<data dir>/index.sqlite3` (mode `0600`, plus SQLite `-wal`/`-shm` files) | `[index] db_path` |
| Sync lock | `index.lock` next to the index | follows `db_path` |

The same defaults apply on macOS (`~/.config`, `~/.local/share`); only the Claude desktop app
root differs by OS.

### Environment variables

| Variable | Effect |
| --- | --- |
| `PRIORLOG_CONFIG` | Path of the config file. Ignored when `--config` is given. |
| `PRIORLOG_HOME` | Data directory. The index is `$PRIORLOG_HOME/index.sqlite3` unless `db_path` is set. |
| `XDG_CONFIG_HOME` | Base for the config file when `PRIORLOG_CONFIG` is unset (default `~/.config`). |
| `XDG_DATA_HOME` | Base for the data directory when `PRIORLOG_HOME` is unset (default `~/.local/share`). |

All of them accept `~`. A throwaway setup for experiments:

```bash
export PRIORLOG_CONFIG=/tmp/pl/config.toml PRIORLOG_HOME=/tmp/pl/data
priorlog init
```

## Rules for the file

- Unknown keys are ignored. Invalid values (a path list that is not a list of strings, an invalid
  regex, a JSONL source without `name`, `paths` or `text`, a non-boolean `emails`/`high_entropy`/
  `enabled`, a non-integer `auto_sync_seconds`) produce `config error: ...` and exit code 2.
- **A harness is indexed only if its section is present.** Inside a present section, an omitted
  `roots` (or `desktop_roots`) falls back to the default location listed below. If there is no
  config file at all, all four default sections apply. A config file that leaves out
  `[sources.codex]` entirely does not index Codex. Start from `priorlog init` and edit.
- `enabled = false` turns a harness off while keeping its roots in the file. For
  `[sources.claude]` it turns off both `roots` and `desktop_roots`.
- Paths may use `~`. Other relative paths (roots, JSONL `paths`, `db_path`) are resolved against
  the folder that holds the config file (see `examples/demo/config.toml`). Roots must be directories; missing ones are skipped (`init` reports them as
  "not found (skipped)").

## Keys

### `[sources.claude]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | |
| `roots` | list of paths | `["~/.claude/projects"]` | Claude Code CLI transcripts: `<root>/<project-dir>/<uuid>.jsonl` and `<root>/<project-dir>/<uuid>/subagents/agent-<id>.jsonl`. The desktop app's Code sessions are written here too. |
| `desktop_roots` | list of paths | Linux: `["~/.config/Claude/claude-code-sessions"]`, macOS: `["~/Library/Application Support/Claude/claude-code-sessions"]` | Claude desktop app session files `<root>/*/*/local_*.json`. Used only for titles, the desktop id (`local_...`), cwd and start time of the CLI session each one points at. |

Example: index a second machine's transcripts that you copy to a local folder.

```toml
[sources.claude]
enabled = true
roots = ["~/.claude/projects", "~/mirrors/buildbox/projects"]
desktop_roots = ["~/.config/Claude/claude-code-sessions"]
```

Session ids carry no machine name (`claude:<uuid>`); the locator path shows which folder a hit
came from.

### `[sources.codex]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | |
| `roots` | list of paths | `["~/.codex/sessions"]` | Every `*.jsonl` below each root (Codex writes `YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`). |

### `[sources.pi]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | bool | `true` | |
| `roots` | list of paths | `["~/.pi/agent/sessions"]` | Every `*.jsonl` below each root (Pi writes `--<cwd>--/<timestamp>_<uuid>.jsonl`). |

### `[[sources.jsonl]]` (repeatable)

Any other JSONL log, one message per line, mapped field by field. Only files matching `paths`
are read; nothing is guessed.

| Key | Type | Required | Notes |
| --- | --- | --- | --- |
| `name` | string | yes | Letters, digits, `_`, `.`, `-`. The harness becomes `jsonl:<name>`. |
| `paths` | string or list of strings | yes | Files or globs; `**` matches any depth. |
| `text` | dotted path | yes | Field holding the message text. A non-string value is stored as JSON. Lines where it is missing or empty are skipped. |
| `role` | dotted path | no | Field holding the speaker. If not set, or missing on a line, the role is `user`. |
| `role_map` | table | no | Maps your speaker values to `user`, `assistant` or `system`. Values that end up as anything else become `system`. |
| `session` | dotted path | no | Field holding a conversation id. If not set, or missing on a line, the whole file is one session named after the file stem. |
| `timestamp` | dotted path | no | Field holding the time. Use ISO 8601 (`2026-10-12T08:00:00Z`): `--after`, `--before`, `--since` and sorting compare timestamps as strings. |

Dotted paths walk nested objects and lists: `body.text`, `messages.0.content`, `meta.user.id`.

Session ids and timestamps from the log are stored only when they are plainly ids and times: an
id must use letters, digits and `._:+-`, match no deny rule and be left unchanged by redaction;
otherwise the session is named `jsonl:<name>:h-<hash>`, a stable SHA-256 prefix. That way a
`session` field holding a customer email never shows up in a citation. A timestamp that does not
look like ISO 8601 is dropped. The same rule applies to Codex and Pi session ids, to Claude desktop
`local_…` ids, and to the ids an adapter keeps in its per-file sync state. A session whose id was
replaced has no resume command, since that command would contain the original id. Names of
unfamiliar transcript line types, which `status` reports, are kept only when they are
type names made of lowercase letters and `_ . -` that match no deny rule; anything else is counted as `other`.

Each line becomes one message (there is no turn merging). A session's title is taken from its
first user message that was actually indexed (a message dropped by `deny_content` never becomes a
title). JSONL sessions have no cwd, so `--project` matches their title only.

#### Worked example

A support bot writes `~/logs/mybot/2026-10.jsonl`:

```json
{"conversation_id": "c-101", "speaker": "human", "ts": "2026-10-12T08:00:00Z", "body": {"text": "The nightly export job failed with a timeout again"}}
{"conversation_id": "c-101", "speaker": "bot", "ts": "2026-10-12T08:00:04Z", "body": {"text": "Raised the export timeout to 120 s and split it into batches of 5k rows."}}
{"conversation_id": "c-102", "speaker": "operator", "ts": "2026-10-13T09:00:00Z", "body": {"text": "Escalated to on-call"}}
```

Config (this is the commented example in the default file, uncommented):

```toml
[[sources.jsonl]]
name = "mybot"
paths = ["~/logs/mybot/*.jsonl"]
text = "body.text"
role = "speaker"
session = "conversation_id"
timestamp = "ts"
role_map = { human = "user", bot = "assistant" }
```

Result after `priorlog sync`:

- two sessions, `jsonl:mybot:c-101` (a user and an assistant message) and `jsonl:mybot:c-102`;
- `operator` is not in `role_map`, so that message has role `system`;
- citations look like `jsonl:mybot:c-101#1` with locator `~/logs/mybot/2026-10.jsonl:L2`;
- filter with `--harness jsonl:mybot`, or `--harness jsonl` for all JSONL sources.

```text
$ priorlog search export timeout
2 hit(s) for `export timeout` (2 matching messages in 1 session).

[1] The nightly export job failed with a timeout again · jsonl:mybot · 2026-10-12 08:00 · user
    > The nightly «export» job failed with a «timeout» again
    cite: jsonl:mybot:c-101#0   source: ~/logs/mybot/2026-10.jsonl:L1
[2] The nightly export job failed with a timeout again · jsonl:mybot · 2026-10-12 08:00 · assistant
    > Raised the «export timeout» to 120 s and split it into batches of 5k rows.
    cite: jsonl:mybot:c-101#1   source: ~/logs/mybot/2026-10.jsonl:L2
```

### `[policy]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `deny_paths` | list of globs | `[]` | Added to the built-in list below. |
| `deny_content` | list of regexes | `[]` | A message matching any of them is dropped. |

#### `deny_paths`

Before any file is opened, its path is resolved (symlinks followed) and must be inside a
configured root or match a configured JSONL glob. Then every deny glob is tested against the path
**and each of its parent directories**, case-insensitively, with `fnmatch` rules (`*` also
matches `/`). A rule that matches a directory therefore denies everything below it.

Built-in list (always active, cannot be removed):

```
*/.ssh/*            */.gnupg/*          */.aws/*            */.azure/*
*/.kube/*           */.docker/*         */.config/gcloud/*  */.config/gh/*
*/.env              */.env.*            */.netrc            */.pypirc
*/.npmrc            */.credentials.json */credentials.json  */auth.json
*/token.json        */cookies*          */login data*       *.pem
*.key               */id_rsa*           */id_ed25519*
```

This covers the harnesses' own sign-in files (Claude Code's `.credentials.json`, Codex's
`auth.json`), so a misconfigured root can never pull a token into the index.

Example: keep one client project out of the index entirely.

```toml
[policy]
deny_paths = ["*/-work-client-acme*", "*/client-acme/*"]
```

Claude Code names project folders after the cwd with `/` replaced by `-`, so
`/work/client-acme` becomes `~/.claude/projects/-work-client-acme`. Denied files are counted in
the `sync` summary (`N denied`).

#### `deny_content`

Python regular expressions, tested with `re.search` against each message's text before it is
redacted or stored. A match drops the whole message; it is never indexed, and
`priorlog status` counts it under "dropped by deny_content". The same rules apply to session
titles (from any source: first message, `ai-title`, custom titles, desktop app titles, subagent
descriptions), working directories, git branches and resume commands: a matching value is not
stored. In `read --source`, a raw line is shown as `[line withheld: matches a deny_content rule]`
when the line, or any string value inside its JSON, matches. That includes non-message lines
that fall inside a cited assistant turn's line range.

Transcript **file paths** are not filtered. They are the citation locators, and for Claude Code
the project folder name encodes the working directory. To keep a project out entirely, add it to
`deny_paths`. Its files are then never opened, and a denied Claude session takes its subagent
transcripts with it.

`^` anchors at the start of the message and at the start of each of its text blocks (a
message's content blocks, or an assistant turn's parts, are joined with blank lines and each one
is tested too). Add `(?m)` for every line start and `(?i)` to ignore case. Titles are tested at
full length before they are shortened for display. IDE context blocks such as
`<ide_opened_file>…</ide_opened_file>` are stripped from Claude prompts before indexing.

Rules apply when a message is written. Adding a rule (or a `deny_paths` glob, or a redaction
pattern) later does not change rows that are already indexed. To apply it to old data, move the
index file away (`priorlog status` shows its path) and run `priorlog sync` again. In
TOML, prefer single-quoted literal strings for regexes so backslashes need no escaping.

```toml
[policy]
deny_content = ['^PRIVATE:', '(?i)\bdo not index\b']
```

### `[redaction]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `emails` | bool | `true` | Mask email addresses. |
| `high_entropy` | bool | `false` | Also mask long random-looking strings. See below. |
| `custom` | list of `{ name, pattern }` tables | `[]` | Extra regexes, masked as `[REDACTED:custom_<name>]`. |

Redaction runs inside the store on every message, session title, working directory and resume
command before anything is written, and again on raw lines shown by `read --source`. Each match
is replaced by `[REDACTED:<kind>]`; only per-kind counts are kept (see `priorlog status`). Raw
transcript files are never modified. Rules run in the order below, and an existing placeholder is
never re-masked.

#### Built-in kinds

| Kind | Catches |
| --- | --- |
| `private_key` | PEM blocks from `-----BEGIN ... PRIVATE KEY-----` (including `PGP PRIVATE KEY BLOCK`) to the matching END line, or to the end of the text if the END line is missing |
| `anthropic_key` | `sk-ant-` followed by 10 or more key characters |
| `openai_key` | `sk-`, `sk-proj-`, `sk-svcacct-`, `sk-admin-` followed by 20 or more key characters |
| `github_token` | `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_` tokens and `github_pat_` fine-grained tokens |
| `gitlab_token` | `glpat-` personal access tokens |
| `aws_access_key` | access key ids `AKIA...` / `ASIA...` (16 more characters). Secret access keys are caught by `secret_assignment` when they appear as `aws_secret_access_key=...`. |
| `google_api_key` | `AIza` followed by 35 characters |
| `slack_token` | `xoxa-`, `xoxb-`, `xoxp-`, `xoxr-`, `xoxs-` tokens |
| `stripe_key` | `sk_live_`, `sk_test_`, `rk_live_`, `rk_test_` keys |
| `huggingface_token` | `hf_` followed by 30 or more characters |
| `jwt` | three dot-separated base64url segments starting with `eyJ` |
| `bearer_token` | the value after `Bearer ` (12+ characters); the word `Bearer` is kept |
| `basic_auth` | the value after `Authorization: Basic `; the header name is kept |
| `url_credentials` | the password in `scheme://user:password@host`; scheme and user are kept |
| `cookie` | the value of a line starting with `Cookie:` or `Set-Cookie:` |
| `secret_assignment` | `KEY=value` or `KEY: value` (also quoted, as in JSON/YAML/.env) when the key name **ends** in `api_key`/`apikey`, `secret`, `secret_key`, `token`, `password`/`passwd`/`pwd`, `credential`, `private_key` or `access_key` (optionally plural), and the value is at least 6 characters and not a plain number. The key is kept. So `DB_PASSWORD=...` is masked, while `max_tokens: 100000` and `tokenizer = 'trigram'` are not. |
| `email` | email addresses (when `emails = true`) |
| `custom_<name>` | your `custom` patterns |
| `high_entropy` | long random-looking strings (when `high_entropy = true`) |

#### Custom patterns

```toml
[redaction]
custom = [
  { name = "ticket", pattern = 'ACME-[0-9]{6}' },
  { name = "internal_host", pattern = '\b[a-z0-9-]+\.corp\.example\.com\b' },
]
```

The whole match is replaced, for example `[REDACTED:custom_ticket]`. Use lowercase letters,
digits and `_` in `name`. An invalid regex is a config error.

#### `high_entropy`, and why it is off

When on, any run of 32 or more characters from `A-Z a-z 0-9 + / _ -` (optionally ending in `=`
padding) that contains upper case, lower case and digits and has a Shannon entropy of at least 4
bits per character is masked as `[REDACTED:high_entropy]`. That catches secrets in formats no
named pattern knows about.

It is off by default because it also masks long mixed-case identifiers that people search for:
base64 blobs, long message or object ids, generated file names and some URL path segments. Once
masked, those strings can no longer be found. Lower-case hex values such as git commit hashes and
canonical UUIDs do not meet the mixed-case test and are left alone. Turn it on if you would rather
lose some searchability than risk an unknown secret format; existing messages are not re-redacted
until they are re-indexed (for example by deleting the index and running `priorlog sync`).

### `[index]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `auto_sync_seconds` | integer | `300` | Before `search`, `read` and `sessions` (CLI) and before every MCP tool call, run an incremental sync if the last one is at least this many seconds old. `0` turns it off; then run `priorlog sync` yourself. |
| `db_path` | path | `<data dir>/index.sqlite3` | Where the index lives. Not in the default file; add it if you need it. |

## Complete default file

This is what `priorlog init` writes on Linux (on macOS `desktop_roots` points at
`~/Library/Application Support/Claude/claude-code-sessions`):

```toml
# priorlog configuration. Every path is opened read-only.
# Docs: https://github.com/vulbsti/priorlog/blob/main/docs/configuration.md

[sources.claude]
enabled = true
roots = ["~/.claude/projects"]
# Claude desktop app session files (local_*.json): titles and desktop ids for CLI sessions.
desktop_roots = ["~/.config/Claude/claude-code-sessions"]

[sources.codex]
enabled = true
roots = ["~/.codex/sessions"]

[sources.pi]
enabled = true
roots = ["~/.pi/agent/sessions"]

# Any other JSONL log, mapped field by field (dotted paths). Example:
# [[sources.jsonl]]
# name = "mybot"
# paths = ["~/logs/mybot/*.jsonl"]
# text = "body.text"
# role = "speaker"
# session = "conversation_id"
# timestamp = "ts"
# role_map = { human = "user", bot = "assistant" }

[policy]
# Extra path globs never to read (added to the built-in list of credential files).
deny_paths = []
# Regexes: a message matching any of these is dropped entirely and never indexed.
deny_content = []

[redaction]
emails = true
# Also mask long random-looking mixed-case strings (32+ chars). Off by default: it can
# hide legitimate base64 data and identifiers you may want to search for.
high_entropy = false
# Extra patterns, e.g. { name = "ticket", pattern = "ACME-[0-9]{6}" }
custom = []

[index]
# search/read run a quick incremental sync first when the index is older than this.
# 0 turns it off (then run `priorlog sync` yourself).
auto_sync_seconds = 300
```
