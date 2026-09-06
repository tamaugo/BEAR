# BEAR — Batch eBay Agentic Retrieval
#
# Sourced from ~/.zshrc. Puts you in the harness with pi running and everything
# pre-flighted. Edit this file, not ~/.zshrc — it is version controlled.
#
#   BEAR         pre-flight, then launch pi in the harness (inside tmux)
#   BEAR check   pre-flight only, do not launch
#   BEAR raw     launch pi without tmux

BEAR_HOME="/Users/tamaugo/Desktop/ebay-pipeline"
BEAR_HARNESS="$BEAR_HOME/harness"

_bear_preflight() {
  local ok=1
  print -P "%F{cyan}BEAR%f — Batch eBay Agentic Retrieval"
  print ""

  # 1. harness present
  if [[ -d "$BEAR_HARNESS/.pi/agents" ]]; then
    local n=$(ls -1 "$BEAR_HARNESS/.pi/agents"/*.md 2>/dev/null | wc -l | tr -d ' ')
    print -P "  %F{green}OK%f   harness found, $n agent files"
  else
    print -P "  %F{red}FAIL%f harness missing at $BEAR_HARNESS"; ok=0
  fi

  # 2. eBay credentials — presence and length only, never the values
  if [[ -n "$EBAY_APP_ID" && -n "$EBAY_CERT_ID" ]]; then
    print -P "  %F{green}OK%f   eBay creds set (App ID ${#EBAY_APP_ID} chars, Cert ID ${#EBAY_CERT_ID} chars)"
    [[ ${#EBAY_APP_ID} -lt 38 ]] && print -P "  %F{yellow}WARN%f App ID looks short — the Dev ID is 36 chars and is NOT the App ID"
    [[ "$EBAY_CERT_ID" != PRD-* ]] && print -P "  %F{yellow}WARN%f Cert ID does not start PRD- — sandbox keys fail against production"
  else
    print -P "  %F{red}FAIL%f eBay creds not set in THIS shell. Agent 2 will fail on every lookup."
    print    "       export EBAY_APP_ID=\"...\" && export EBAY_CERT_ID=\"...\""
    print    "       (they must be set before pi starts — child agents inherit its environment)"
    ok=0
  fi

  # 3. the output-token cap, without which every Agent 2/3 call 402s
  if grep -q '"maxTokens"' ~/.pi/agent/models.json 2>/dev/null; then
    print -P "  %F{green}OK%f   models.json output-token cap present"
  else
    print -P "  %F{red}FAIL%f ~/.pi/agent/models.json missing the muse-spark-1.3 maxTokens cap."
    print    "       Without it OpenRouter rejects every Agent 2 and Agent 3 call with a 402."
    print    "       Reference copy: harness/pi-config-reference/models.json"
    ok=0
  fi

  # 4. the extension-collision fix, without which subagents die silently
  if grep -q 'pi-interactive-subagents' "$BEAR_HARNESS/.pi/settings.json" 2>/dev/null; then
    print -P "  %F{green}OK%f   subagent extension collision fix present"
  else
    print -P "  %F{red}FAIL%f .pi/settings.json missing the pi-interactive-subagents disable entry."
    print    "       Without it every spawned agent dies with '(no output)'."
    ok=0
  fi

  print ""
  return $(( ! ok ))
}

BEAR() {
  case "$1" in
    check) ( cd "$BEAR_HARNESS" 2>/dev/null; _bear_preflight ); return $? ;;
  esac

  cd "$BEAR_HARNESS" || { print -P "%F{red}Cannot cd to $BEAR_HARNESS%f"; return 1 }

  if ! _bear_preflight; then
    print -P "%F{yellow}Pre-flight failed. Fix the above, or run anyway with: pi%f"
    return 1
  fi

  print -P "  Then type %F{cyan}/run-pipeline%f inside pi."
  print -P "  %F{242}No flags: -ne strips the subagent tool, --tools disables read/write.%f"
  print ""

  # plain `pi`, no flags — see .pi/prompts/run-pipeline.md for why
  if [[ "$1" == "raw" ]] || ! command -v tmux >/dev/null 2>&1; then
    pi
  else
    tmux new-session -A -s bear "pi"
  fi
}
