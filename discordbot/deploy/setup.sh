#!/usr/bin/env bash
# Sets up (or updates) the BEAR Discord bot on a Debian 13 VM. Run as root; safe to run again.
#   first time:  wget -qO setup.sh https://raw.githubusercontent.com/tamaugo/BEAR/discord-bear/discordbot/deploy/setup.sh && bash setup.sh
#   update:      bash /opt/bear/discordbot/deploy/setup.sh      (restarts the bot: check /status first)
#                or type /update in Discord: the bot leaves a note, systemd (bear-update.path) runs this script as root
# Installs: git + Python, a "bear" user, the code in /opt/bear (branch discord-bear), a Python venv,
# /opt/bear/.env from discordbot/deploy/env.example, the bear-send command, the bear-bot systemd service, then runs the offline tests.
# The error channel hears about it (discordbot/heartbeat.py): the outside monitor says "down" just before
# the bot restarts and "up" once it is back; an update that stops part way says which step failed.
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/tamaugo/BEAR.git}"
BRANCH="${BRANCH:-discord-bear}"
DIR=/opt/bear
DATA=/var/lib/bear
as_bear() { runuser -u bear -- env HOME="$DATA" "$@"; }

[ "$(id -u)" = 0 ] || { echo "Run this as root (type: su -  then run it again)."; exit 1; }
cd /   # the bear user can't read root's home, where su - leaves us
notify() { [ -f "$DIR/discordbot/heartbeat.py" ] && python3 "$DIR/discordbot/heartbeat.py" "$@" >/dev/null 2>&1 || true; }
STEP="starting"
step() { STEP="$1"; echo "== $1"; }
# An update that stops before its tests have passed puts the code back as it was. The bot keeps
# running, and it starts every /run from the files on disk: left alone, the next folder would run
# on code that just failed its tests, and so would the bot itself after its next restart.
OLD=""   # the commit the code was on before this update; blank once the new code has passed its tests
undo() {
  [ -n "$OLD" ] || return 0
  [ "$(as_bear git -C "$DIR" rev-parse HEAD 2>/dev/null)" != "$OLD" ] || return 0
  if as_bear git -C "$DIR" reset -q --keep "$OLD"; then echo "The code was put back as it was before this update."
  else echo "The code could NOT be put back: $DIR holds the new, untested code. Fix it by hand before the next /run."; STEP="$STEP (and the code could not be put back: the server holds untested code)"
  fi
}
trap 'rc=$?; [ "$rc" = 0 ] || { undo; notify failed "$STEP"; }' EXIT
step "Installing system packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git python3 python3-venv ca-certificates systemd-timesyncd >/dev/null
timedatectl set-ntp true 2>/dev/null || true   # a correct clock: /run times the upload wait from Discord's timestamps

step "bear user and folders"
id bear >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin bear
mkdir -p "$DATA/runs"
chown -R bear:bear "$DATA"

step "Code in $DIR ($BRANCH)"
if [ -d "$DIR/.git" ]; then
  OLD="$(as_bear git -C "$DIR" rev-parse HEAD)"
  as_bear git -C "$DIR" fetch -q origin "$BRANCH"
  as_bear git -C "$DIR" checkout -q "$BRANCH"
  as_bear git -C "$DIR" merge -q --ff-only "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO_URL" "$DIR"
  chown -R bear:bear "$DIR"
fi

step "Python packages"
[ -x "$DIR/.venv/bin/python" ] || as_bear python3 -m venv "$DIR/.venv"
as_bear "$DIR/.venv/bin/pip" install -q --upgrade pip
as_bear "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt" -r "$DIR/discordbot/requirements.txt"
as_bear "$DIR/.venv/bin/python" -c "from PIL import features; assert features.check('webp'), 'Pillow has no webp support'"

step "Settings file $DIR/.env"
if [ ! -f "$DIR/.env" ]; then
  install -m 600 -o bear -g bear "$DIR/discordbot/deploy/env.example" "$DIR/.env"
fi
chown bear:bear "$DIR/.env"
chmod 600 "$DIR/.env"

step "Offline tests (no network, no credits)"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_names_offline.py"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_discord_offline.py"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_discord_look_offline.py"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_partid_offline.py"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_agent3_validator.py"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_no_number_offline.py"
if ! as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_discord_flow_offline.py" >"$DATA/flow-test.log" 2>&1; then
  tail -n 25 "$DATA/flow-test.log"
  echo "The Discord flow test failed (full output: $DATA/flow-test.log). Nothing was started."
  exit 1
fi
tail -n 1 "$DATA/flow-test.log"
OLD=""   # the new code passed: it stays, whatever happens next

step "bear-send command"
install -m 755 "$DIR/discordbot/deploy/bear-send" /usr/local/bin/bear-send
ln -sf bear-send /usr/local/bin/bear-send:   # so "bear-send: my message @channel" works as typed

step "Service"
install -m 644 "$DIR/discordbot/deploy/bear-bot.service" /etc/systemd/system/bear-bot.service
install -m 644 "$DIR/discordbot/deploy/bear-update.service" /etc/systemd/system/bear-update.service
install -m 644 "$DIR/discordbot/deploy/bear-update.path" /etc/systemd/system/bear-update.path
systemctl daemon-reload
systemctl enable -q bear-bot
systemctl enable -q --now bear-update.path   # /update in Discord runs this script (no-op if it is already watching)
if grep -q '=PASTE_HERE' "$DIR/.env"; then
  systemctl stop bear-bot 2>/dev/null || true
  echo
  echo "Almost done. Fill in the PASTE_HERE lines:   nano $DIR/.env"
  echo "then start the bot:                          systemctl restart bear-bot"
else
  notify down
  systemctl restart bear-bot
  echo
  echo "Bot (re)started. Check it:  systemctl status bear-bot    log:  journalctl -u bear-bot -f"
fi
