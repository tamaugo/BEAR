# BEAR — Batch eBay Agentic Retrieval
#
# Sourced from ~/.zshrc. Puts you in the harness with pi running and everything
# pre-flighted. Edit this file, not ~/.zshrc — it is version controlled.
#
# Credentials are read from the macOS Keychain if not already exported, so they
# never sit in plaintext in a dotfile. Store them once with:
#   security add-generic-password -a "$USER" -s ebay-app-id  -w
#   security add-generic-password -a "$USER" -s ebay-cert-id -w
#
#   BEAR         pre-flight, then launch pi in the harness (inside tmux)
#   BEAR check   pre-flight only, do not launch
#   BEAR raw     launch pi without tmux

# Self-locate the repo from this script's own path (works from any clone
# location). bear.zsh lives at <repo>/tools/bear.zsh, so the repo root is one
# level up. Falls back to the legacy Desktop path only if self-location fails
# — and the pre-flight below FAILS LOUDLY if the harness isn't there, so a
# wrong path can never silently launch pi from the wrong directory.
# (2026-09-28 fix: the old hard-coded BEAR_HOME made fresh clones cd elsewhere,
# so pi launched outside harness/ and never discovered .pi/prompts/ —
# /run-pipeline vanished and the coordinator had no instructions.)
typeset _bear_script_path="${(%):-%x}"
BEAR_HOME="${_bear_script_path:a}"      # absolute, resolves ./ and relative sources
BEAR_HOME="${BEAR_HOME:h:h}"            # strip tools/bear.zsh -> repo root
if [[ ! -d "$BEAR_HOME/harness/.pi/agents" ]]; then
  BEAR_HOME="/Users/tamaugo/Desktop/ebay-pipeline"
fi
BEAR_HARNESS="$BEAR_HOME/harness"

_bear_preflight() {
  local ok=1
  print -P "%F{cyan}BEAR%f — Batch eBay Agentic Retrieval"
  print ""
  print -P "  %F{242}repo: $BEAR_HOME%f"
  print ""

  # 1. harness present
  if [[ -d "$BEAR_HARNESS/.pi/agents" ]]; then
    local n=$(ls -1 "$BEAR_HARNESS/.pi/agents"/*.md 2>/dev/null | wc -l | tr -d ' ')
    print -P "  %F{green}OK%f   harness found, $n agent files"
  else
    print -P "  %F{red}FAIL%f harness missing at $BEAR_HARNESS"; ok=0
  fi

  # 2. eBay credentials — presence and length only, never the values.
  #    If not already exported, pull them from the macOS Keychain.
  if [[ -z "$EBAY_APP_ID" || -z "$EBAY_CERT_ID" ]]; then
    local k_app k_cert
    k_app=$(security find-generic-password -a "$USER" -s ebay-app-id -w 2>/dev/null)
    k_cert=$(security find-generic-password -a "$USER" -s ebay-cert-id -w 2>/dev/null)
    if [[ -n "$k_app" && -n "$k_cert" ]]; then
      export EBAY_APP_ID="$k_app" EBAY_CERT_ID="$k_cert"
      print -P "  %F{green}OK%f   eBay creds loaded from Keychain"
    fi
    unset k_app k_cert
  fi
  if [[ -n "$EBAY_APP_ID" && -n "$EBAY_CERT_ID" ]]; then
    print -P "  %F{green}OK%f   eBay creds set (App ID ${#EBAY_APP_ID} chars, Cert ID ${#EBAY_CERT_ID} chars)"
    [[ ${#EBAY_APP_ID} -lt 38 ]] && print -P "  %F{yellow}WARN%f App ID looks short — the Dev ID is 36 chars and is NOT the App ID"
    [[ "$EBAY_CERT_ID" != PRD-* ]] && print -P "  %F{yellow}WARN%f Cert ID does not start PRD- — sandbox keys fail against production"
  else
    print -P "  %F{red}FAIL%f No eBay credentials, in this shell or the Keychain."
    print    "       Store them once (each prompts silently, nothing hits shell history):"
    print    "         security add-generic-password -a \"\$USER\" -s ebay-app-id  -w"
    print    "         security add-generic-password -a \"\$USER\" -s ebay-cert-id -w"
    print    "       BEAR then loads them automatically in every new shell."
    print    "       Or export them by hand for one session:"
    print    "         export EBAY_APP_ID=\"...\" && export EBAY_CERT_ID=\"...\""
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
