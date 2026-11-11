#!/usr/bin/env bash
# The demo session that assets/src/demo/record.py records with `script` (util-linux).
#
# Builds a throwaway HOME from tests/fixtures (transcripts copied to where each harness keeps
# them, so paths print as ~/...), plants one extra session holding a fake API key that is
# generated here at runtime (never committed), then types and *runs* each priorlog command in
# this terminal. Setup and the cite lookup print nothing; everything on screen is the real
# output of the real commands.
#
#   DEMO_WORK=/some/empty/dir bash assets/src/demo/session.sh
#
# DEMO_WORK receives home/ and hits.json (the `search --json` hits, for the citation diagram).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK="${DEMO_WORK:?set DEMO_WORK to an empty directory}"
FIX="$REPO/tests/fixtures"
H="$WORK/home"
PLANTED_ID="dddddddd-4444-4444-8444-000000000004"

mkdir -p "$H"/{.claude,.config/Claude,.codex,.pi/agent,exports}
cp -r "$FIX/claude/projects" "$H/.claude/projects"
cp -r "$FIX/claude/desktop" "$H/.config/Claude/claude-code-sessions"
cp -r "$FIX/codex/sessions" "$H/.codex/sessions"
cp -r "$FIX/pi/sessions" "$H/.pi/agent/sessions"
cp -r "$FIX/jsonl" "$H/exports/supportbot"

mkdir -p "$H/.config/priorlog"
cat >"$H/.config/priorlog/config.toml" <<'TOML'
[sources.claude]
roots = ["~/.claude/projects"]
desktop_roots = ["~/.config/Claude/claude-code-sessions"]
[sources.codex]
roots = ["~/.codex/sessions"]
[sources.pi]
roots = ["~/.pi/agent/sessions"]
[[sources.jsonl]]
name = "supportbot"
paths = ["~/exports/supportbot/*.jsonl"]
text = "body.text"
role = "speaker"
session = "conversation_id"
timestamp = "ts"
role_map = { customer = "user", bot = "assistant" }
[index]
auto_sync_seconds = 0
TOML

# A short Claude Code session where the user pasted a key while debugging the rate limiter.
# The key is secret-shaped but fake, and built here so no key-like literal lives in the repo.
python3 - "$H/.claude/projects/-work-demo-app/$PLANTED_ID.jsonl" "$PLANTED_ID" <<'PY'
import json, random, string, sys

path, sid = sys.argv[1:]
rnd = random.Random(7)
key = "sk-" + "ant-" + "api03-" + "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(40))
base = {"sessionId": sid, "cwd": "/work/demo-app", "gitBranch": "fix/429"}
lines = [
    {**base, "type": "user", "timestamp": "2026-10-06T16:20:00Z", "message": {"role": "user",
     "content": "Staging returns 429 on the very first call, so the rate limiter is wrong. "
     f'Repro: curl -H "x-api-key: {key}" https://staging.demo.test/v1/orders'}},
    {**base, "type": "assistant", "timestamp": "2026-10-06T16:21:10Z", "message": {"role": "assistant",
     "model": "claude-x", "content": [{"type": "text", "text": "Found it: behind the load balancer "
     "every request had the same client IP, so all keys shared one bucket. The limiter now keys "
     "buckets on a hash of the API key."}]}},
    {"type": "custom-title", "customTitle": "Staging 429s", "sessionId": sid},
]
with open(path, "w") as fh:
    fh.writelines(json.dumps(x) + "\n" for x in lines)
PY

export HOME="$H"
export PRIORLOG_CONFIG="$H/.config/priorlog/config.toml"
export PRIORLOG_HOME="$H/.local/share/priorlog"
export PATH="$REPO/.venv/bin:/usr/bin:/bin"
export TERM=xterm-256color LANG=C.UTF-8 TZ=UTC COLUMNS=100 LINES=30
export PS1=$'\e[36m~\e[0m \e[32m$\e[0m '  # renders as "~ $ "
stty cols 100 rows 30 2>/dev/null || true
cd "$HOME"

prompt() { printf '%s' "$PS1"; }

# Type a command one character at a time (like VHS), press Enter, then run it for real.
run() {
	local pause="$1" hold="$2" cmd="$3" i
	sleep "$pause"
	for ((i = 0; i < ${#cmd}; i++)); do
		printf '%s' "${cmd:i:1}"
		sleep 0.04
	done
	sleep 0.35
	printf '\n'
	eval "$cmd" || [ $? -eq 3 ] # 3 = no hits, not an error
	prompt
	sleep "$hold"
}

prompt
run 0.6 1.2 "priorlog sync"
run 0.4 3.2 "priorlog status"
run 0.6 4.5 "priorlog search rate limiter"

# Off screen: open the hit that came from the planted session, so `read --source` shows redaction.
priorlog search rate limiter --json >"$WORK/hits.json"
cite="$(python3 -c 'import json,sys; print(next(h["cite"] for h in json.load(open(sys.argv[1]))["hits"] if sys.argv[2] in h["cite"]))' "$WORK/hits.json" "$PLANTED_ID")"

run 0.3 0.5 "priorlog read $cite --source --context 1"
