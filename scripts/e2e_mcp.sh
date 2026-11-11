#!/usr/bin/env bash
# MCP end-to-end proof: a headless `claude -p` and `codex exec`, each running with a throwaway
# HOME whose only transcripts are tests/fixtures/, answer a question by calling priorlog's MCP
# tools. Raw transcripts are sanitized and written to docs/verification/ (or $1).
#
#   scripts/e2e_mcp.sh [OUT_DIR]          # needs: claude, codex, <repo>/.venv (uv sync)
#   E2E_SKIP_CODEX=1 scripts/e2e_mcp.sh   # claude only
#   E2E_KEEP_STDERR=1 ...                 # also print codex stderr (sanitized)
#
# Auth (method only, nothing is ever printed):
#   claude: $ANTHROPIC_API_KEY or $CLAUDE_CODE_OAUTH_TOKEN if set in the caller's env; otherwise a
#           copy of the claudeAiOauth access token from ~/.claude/.credentials.json WITHOUT the
#           refresh token (so the child can never rotate the real login), mode 600.
#   codex:  $OPENAI_API_KEY if set; otherwise a copy of ~/.codex/auth.json in a throwaway
#           CODEX_HOME with the refresh token blanked and last_refresh set to now (so the child
#           never refreshes/rotates the real login), mode 600.
# Copied credential files are truncated before the throwaway dir is moved to $E2E_TRASH
# (default ~/proj/TRASH). Real ~/.claude*, ~/.codex and MCP registrations are never written.
set -euo pipefail
umask 077

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:-$REPO/docs/verification}
TRASH=${E2E_TRASH:-$HOME/proj/TRASH}
REAL_HOME=$HOME
PY=$REPO/.venv/bin/python
QUESTION="Using the priorlog tools, find out which algorithm we chose for the orders API rate limiter and why, and cite the session and source lines you relied on."

[ -x "$PY" ] || { echo "missing $PY (run: uv sync)" >&2; exit 1; }
mkdir -p "$OUT" "$TRASH"

TMP=$(mktemp -d -t priorlog-e2e.XXXXXX)
H=$TMP/home              # throwaway HOME = a copy of the fixtures (like tests/conftest.py)
CREDS=()
cleanup() {
  for f in "${CREDS[@]}"; do [ -f "$f" ] && : >"$f"; done   # truncate copied credentials
  mv "$TMP" "$TRASH/$(basename "$TMP")-$(date +%Y%m%d%H%M%S)"
}
trap cleanup EXIT

cp -r "$REPO/tests/fixtures" "$H"
mkdir -p "$H/work" "$H/data"
CFG=$H/config.toml
cat >"$CFG" <<EOF
[sources.claude]
roots = ["$H/claude/projects"]
desktop_roots = ["$H/claude/desktop"]
[sources.codex]
roots = ["$H/codex/sessions"]
[sources.pi]
roots = ["$H/pi/sessions"]
[[sources.jsonl]]
name = "supportbot"
paths = ["$H/jsonl/*.jsonl"]
text = "body.text"
role = "speaker"
session = "conversation_id"
timestamp = "ts"
role_map = { customer = "user", bot = "assistant" }
[index]
db_path = "$H/data/index.sqlite3"
auto_sync_seconds = 60
EOF
# Index nothing up front: the first MCP tool call runs the auto-sync itself.

# Minimal environment for the children: no CLAUDE_CODE_* session vars, no ANTHROPIC_BASE_URL.
BASE_ENV=(PATH="$PATH" HOME="$H" TERM=dumb LANG=C.UTF-8 PRIORLOG_HOME="$H/data")

# Sanitize a raw transcript: temp path -> $TMP, repo -> <repo>, real home -> ~, account ids out.
sanitize() {
  "$PY" -I - "$1" "$2" "$TMP" "$REPO" "$REAL_HOME" <<'PYEOF'
import json, os, re, sys
src, dst, tmp, repo, home = sys.argv[1:6]
secrets = [v for k in ("CLAUDE_CODE_ACCOUNT_UUID", "CLAUDE_CODE_ORGANIZATION_UUID",
                       "CLAUDE_CODE_USER_EMAIL") if (v := os.environ.get(k))]
ACCOUNT_KEYS = re.compile(r"(account|email|org(anization)?_?(id|uuid|name)?|user_?id)$", re.I)
def scrub(o):
    if isinstance(o, dict):
        return {k: ("<redacted>" if ACCOUNT_KEYS.search(k) and isinstance(v, (str, int)) else scrub(v))
                for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o
with open(src) as f, open(dst, "w") as out:
    for line in f:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        for s in secrets:
            line = line.replace(s, "<redacted>")
        line = line.replace(tmp, "$TMP").replace(repo, "<repo>").replace(home, "~")
        try:
            line = json.dumps(scrub(json.loads(line)), ensure_ascii=False)
        except json.JSONDecodeError:
            pass
        out.write(line + "\n")
PYEOF
}

# ---------------------------------------------------------------- claude
echo "== claude $(claude --version)"
cat >"$TMP/mcp.json" <<EOF
{"mcpServers": {"priorlog": {"type": "stdio", "command": "$PY",
  "args": ["-m", "priorlog", "--config", "$CFG", "mcp"],
  "env": {"HOME": "$H", "PRIORLOG_HOME": "$H/data"}}}}
EOF
CLAUDE_ENV=("${BASE_ENV[@]}")
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  CLAUDE_ENV+=(ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"); echo "claude auth: ANTHROPIC_API_KEY env"
elif [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  CLAUDE_ENV+=(CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN"); echo "claude auth: CLAUDE_CODE_OAUTH_TOKEN env"
else
  mkdir -p "$H/.claude"; CREDS+=("$H/.claude/.credentials.json")
  "$PY" -I - "$REAL_HOME/.claude/.credentials.json" "$H/.claude/.credentials.json" <<'PYEOF'
import json, sys, time
o = json.load(open(sys.argv[1]))["claudeAiOauth"]
if o["expiresAt"] / 1000 - time.time() < 600:
    sys.exit("claude access token expires within 10 min; let your normal claude session refresh it, then retry")
keep = {k: o[k] for k in ("accessToken", "expiresAt", "scopes", "subscriptionType", "rateLimitTier") if k in o}
with open(sys.argv[2], "w") as f:
    json.dump({"claudeAiOauth": keep}, f)
PYEOF
  echo "claude auth: copied OAuth access token (no refresh token) into throwaway HOME"
fi
set +e
(cd "$H/work" && env -i "${CLAUDE_ENV[@]}" claude -p "$QUESTION" \
  --mcp-config "$TMP/mcp.json" --strict-mcp-config \
  --tools "" \
  --allowedTools mcp__priorlog__search mcp__priorlog__read mcp__priorlog__sessions mcp__priorlog__status \
  --output-format stream-json --verbose --no-session-persistence \
  >"$TMP/claude.raw.jsonl" 2>"$TMP/claude.stderr" </dev/null)
CLAUDE_RC=$?
set -e
echo "claude exit: $CLAUDE_RC"
sanitize "$TMP/claude.raw.jsonl" "$OUT/mcp-e2e-claude.jsonl"
[ "$CLAUDE_RC" = 0 ] || { sanitize "$TMP/claude.stderr" /dev/stdout | tail -20; }

# ---------------------------------------------------------------- codex
if [ -z "${E2E_SKIP_CODEX:-}" ]; then
  echo "== $(codex --version)"
  CX=$TMP/codex-home; mkdir -p "$CX"
  cat >"$CX/config.toml" <<EOF
[mcp_servers.priorlog]
command = "$PY"
args = ["-m", "priorlog", "--config", "$CFG", "mcp"]
env = { HOME = "$H", PRIORLOG_HOME = "$H/data" }
startup_timeout_sec = 30
tool_timeout_sec = 120
EOF
  # Optional: E2E_CODEX_APPROVAL_MODE=approve forces codex to approve every priorlog tool call.
  if [ -n "${E2E_CODEX_APPROVAL_MODE:-}" ]; then
    echo "default_tools_approval_mode = \"$E2E_CODEX_APPROVAL_MODE\"" >>"$CX/config.toml"
  fi
  CODEX_ENV=("${BASE_ENV[@]}" CODEX_HOME="$CX")
  if [ -n "${OPENAI_API_KEY:-}" ]; then
    CODEX_ENV+=(OPENAI_API_KEY="$OPENAI_API_KEY"); echo "codex auth: OPENAI_API_KEY env"
  else
    CREDS+=("$CX/auth.json")
    "$PY" -I - "$REAL_HOME/.codex/auth.json" "$CX/auth.json" <<'PYEOF'
import json, sys
from datetime import datetime, timezone
a = json.load(open(sys.argv[1]))
if a.get("tokens"):
    a["tokens"]["refresh_token"] = ""
a["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
with open(sys.argv[2], "w") as f:
    json.dump(a, f)
PYEOF
    echo "codex auth: copied auth.json (refresh token blanked) into throwaway CODEX_HOME"
  fi
  set +e
  (cd "$H/work" && env -i "${CODEX_ENV[@]}" codex exec --json --skip-git-repo-check \
    --sandbox read-only -c approval_policy='"never"' \
    --disable apps --disable plugins --disable memories --disable browser_use --disable computer_use \
    "$QUESTION" >"$TMP/codex.raw.jsonl" 2>"$TMP/codex.stderr" </dev/null)
  CODEX_RC=$?
  [ -n "${E2E_KEEP_STDERR:-}" ] && sanitize "$TMP/codex.stderr" /dev/stdout | tail -20
  set -e
  echo "codex exit: $CODEX_RC"
  sanitize "$TMP/codex.raw.jsonl" "$OUT/mcp-e2e-codex.jsonl"
  [ "$CODEX_RC" = 0 ] || { sanitize "$TMP/codex.stderr" /dev/stdout | tail -20; }
fi

# ---------------------------------------------------------------- checks
for f in "$OUT"/mcp-e2e-*.jsonl; do
  if grep -q -e "$REAL_HOME" -e "$TMP" "$f"; then echo "LEAK: path in $f" >&2; exit 1; fi
done
grep -q 'mcp__priorlog__search' "$OUT/mcp-e2e-claude.jsonl" && echo "claude: called mcp__priorlog__search"
grep -q 'token bucket' "$OUT/mcp-e2e-claude.jsonl" && echo "claude: answer mentions token bucket"
