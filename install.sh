#!/usr/bin/env bash
# BEAR 0.3 installer: puts `bear` on your PATH. Safe to re-run.
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  case "$SOURCE" in /*) ;; *) SOURCE="$DIR/$SOURCE" ;; esac
done
REPO="$(cd -P "$(dirname "$SOURCE")" && pwd)"
BIN_DIR="$HOME/.local/bin"
LINK="$BIN_DIR/bear"
MARKER="# added by BEAR install.sh"

chmod +x "$REPO/bin/bear"
mkdir -p "$BIN_DIR"

if [ -L "$LINK" ]; then
  rm -f "$LINK"
elif [ -e "$LINK" ]; then
  echo "Refusing to overwrite $LINK: it exists and is not a symlink." >&2
  echo "Move or delete it yourself, then run ./install.sh again." >&2
  exit 1
fi
ln -s "$REPO/bin/bear" "$LINK"
echo "Linked $LINK -> $REPO/bin/bear"

NEW_TERMINAL=0
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    if ! grep -qF "$MARKER" "$HOME/.zshrc" 2>/dev/null; then
      {
        echo ""
        echo "$MARKER"
        echo 'export PATH="$HOME/.local/bin:$PATH"'
      } >> "$HOME/.zshrc"
      echo "Added ~/.local/bin to PATH in ~/.zshrc"
    fi
    NEW_TERMINAL=1
    ;;
esac

OTHER="$(command -v bear 2>/dev/null || true)"
if [ -n "$OTHER" ] && [ "$OTHER" != "$LINK" ]; then
  echo "WARNING: 'bear' currently resolves to $OTHER, which will run instead of BEAR 0.3." >&2
  echo "         Remove it or put $BIN_DIR earlier on your PATH." >&2
fi

if [ "$NEW_TERMINAL" -eq 1 ]; then
  echo "Open a NEW Terminal window so the 'bear' command is found."
fi

echo ""
"$REPO/bin/bear" check || true
echo ""
echo "Done. Type: bear"
