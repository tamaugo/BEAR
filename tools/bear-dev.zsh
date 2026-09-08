# BEARDEV — BEAR, independent-bear branch
#
# The working demo still lives at ~/Desktop/ebay-pipeline and is still launched
# by plain `BEAR`. This file launches the SEPARATE worktree at
# ~/Desktop/independent-BEAR, so the two never touch each other and the demo
# stays runnable at all times.
#
# Use it either way:
#
#   one-off, changes nothing permanently:
#     source ~/Desktop/independent-BEAR/tools/bear-dev.zsh && BEARDEV
#
#   permanent, add to ~/.zshrc alongside the existing BEAR line:
#     source ~/Desktop/independent-BEAR/tools/bear-dev.zsh
#
#   BEARDEV         pre-flight, then launch pi in the independent-bear harness
#   BEARDEV check   pre-flight only, do not launch
#   BEARDEV raw     launch pi without tmux
#
# Credentials come from the macOS Keychain, exactly as the demo launcher does.
# They are never written to a dotfile and never printed.

BEARDEV_HOME="/Users/tamaugo/Desktop/independent-BEAR"
BEARDEV_HARNESS="$BEARDEV_HOME/harness"

_beardev_preflight() {
  local ok=1
  print -P "%F{cyan}BEARDEV%f — independent-bear branch"
  print -P "%F{242}$BEARDEV_HOME%f"
  print ""

  # 0. right worktree, right branch — the whole point of this launcher
  if [[ -d "$BEARDEV_HOME/.git" || -f "$BEARDEV_HOME/.git" ]]; then
    local br=$(git -C "$BEARDEV_HOME" rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [[ "$br" == "independent-bear" ]]; then
      print -P "  %F{green}OK%f   on branch independent-bear"
    else
      print -P "  %F{yellow}WARN%f worktree is on branch '$br', expected independent-bear"
    fi
  fi

  # 1. harness present
  if [[ -d "$BEARDEV_HARNESS/.pi/agents" ]]; then
    local n=$(ls -1 "$BEARDEV_HARNESS/.pi/agents"/*.md 2>/dev/null | wc -l | tr -d ' ')
    print -P "  %F{green}OK%f   harness found, $n agent files"
  else
    print -P "  %F{red}FAIL%f harness missing at $BEARDEV_HARNESS"; ok=0
  fi

  # 2. eBay credentials — presence and length only, never the values.
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
  if grep -q 'pi-interactive-subagents' "$BEARDEV_HARNESS/.pi/settings.json" 2>/dev/null; then
    print -P "  %F{green}OK%f   subagent extension collision fix present"
  else
    print -P "  %F{red}FAIL%f .pi/settings.json missing the pi-interactive-subagents disable entry."
    print    "       Without it every spawned agent dies with '(no output)'."
    ok=0
  fi

  # 5. NEW on this branch — the spreadsheet converter must import cleanly.
  #    Agent 3 writes text; this script turns it into the .xlsx. If it cannot
  #    run, a job completes and then produces no spreadsheet at the last step,
  #    which is the most annoying possible time to find out.
  if [[ -f "$BEARDEV_HARNESS/make_xlsx.py" ]]; then
    local mx_err
    mx_err=$(python3 "$BEARDEV_HARNESS/make_xlsx.py" 2>&1)
    if print -r -- "$mx_err" | grep -q 'ModuleNotFoundError\|ImportError'; then
      print -P "  %F{red}FAIL%f make_xlsx.py cannot import a module it needs:"
      print    "       $(print -r -- "$mx_err" | grep -m1 'ModuleNotFoundError\|ImportError')"
      ok=0
    else
      print -P "  %F{green}OK%f   xlsx converter imports cleanly"
    fi
    unset mx_err
  else
    print -P "  %F{red}FAIL%f harness/make_xlsx.py missing — no spreadsheet will be produced"; ok=0
  fi

  print ""
  return $(( ! ok ))
}

BEARDEV() {
  case "$1" in
    check) ( cd "$BEARDEV_HARNESS" 2>/dev/null; _beardev_preflight ); return $? ;;
  esac

  cd "$BEARDEV_HARNESS" || { print -P "%F{red}Cannot cd to $BEARDEV_HARNESS%f"; return 1 }

  if ! _beardev_preflight; then
    print -P "%F{yellow}Pre-flight failed. Fix the above, or run anyway with: pi%f"
    return 1
  fi

  print -P "  Then type %F{cyan}/run-pipeline%f inside pi."
  print ""
  print -P "  %F{242}This version will ask you for the vehicle string, e.g.%f"
  print -P "  %F{242}  MAZDA 6 MK2 2008 SEDAN 2.5 PETROL%f"
  print -P "  %F{242}Photos: one per part, each showing a part number.%f"
  print -P "  %F{242}Location goes in the filename — img_2225_OSF.JPEG%f"
  print -P "  %F{242}Codes: _NSF _NSR _OSF _OSR. No location, no suffix.%f"
  print -P "  %F{242}Result: output/BEAR_results.xlsx%f"
  print -P "  %F{242}No flags: -ne strips the subagent tool, --tools disables read/write.%f"
  print ""

  # plain `pi`, no flags — see .pi/prompts/run-pipeline.md for why.
  # Separate tmux session name from the demo's, so the two never share a pane.
  if [[ "$1" == "raw" ]] || ! command -v tmux >/dev/null 2>&1; then
    pi
  else
    tmux new-session -A -s beardev "pi"
  fi
}
