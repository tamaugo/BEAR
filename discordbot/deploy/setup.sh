#!/usr/bin/env bash
# Sets up (or updates) the BEAR Discord bot on a Debian 13 VM. Run as root; safe to run again.
#   first time:  wget -qO setup.sh https://raw.githubusercontent.com/tamaugo/BEAR/discord-bear/discordbot/deploy/setup.sh && bash setup.sh
#   update:      bash /opt/bear/discordbot/deploy/setup.sh      (restarts the bot: check /status first)
# Installs: git + Python, a "bear" user, the code in /opt/bear (branch discord-bear), a Python venv,
# /opt/bear/.env from discordbot/deploy/env.example, the bear-bot systemd service, then runs the offline tests.
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/tamaugo/BEAR.git}"
BRANCH="${BRANCH:-discord-bear}"
DIR=/opt/bear
DATA=/var/lib/bear
as_bear() { runuser -u bear -- env HOME="$DATA" "$@"; }

[ "$(id -u)" = 0 ] || { echo "Run this as root (type: su -  then run it again)."; exit 1; }
cd /   # the bear user can't read root's home, where su - leaves us
echo "== Installing system packages"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git python3 python3-venv ca-certificates systemd-timesyncd >/dev/null
timedatectl set-ntp true 2>/dev/null || true   # a correct clock: /run times the upload wait from Discord's timestamps

echo "== bear user and folders"
id bear >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --create-home --shell /usr/sbin/nologin bear
mkdir -p "$DATA/runs"
chown -R bear:bear "$DATA"

echo "== Code in $DIR ($BRANCH)"
if [ -d "$DIR/.git" ]; then
  as_bear git -C "$DIR" fetch -q origin "$BRANCH"
  as_bear git -C "$DIR" checkout -q "$BRANCH"
  as_bear git -C "$DIR" merge -q --ff-only "origin/$BRANCH"
else
  git clone -q --branch "$BRANCH" "$REPO_URL" "$DIR"
  chown -R bear:bear "$DIR"
fi

echo "== Python packages"
[ -x "$DIR/.venv/bin/python" ] || as_bear python3 -m venv "$DIR/.venv"
as_bear "$DIR/.venv/bin/pip" install -q --upgrade pip
as_bear "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt" -r "$DIR/discordbot/requirements.txt"
as_bear "$DIR/.venv/bin/python" -c "from PIL import features; assert features.check('webp'), 'Pillow has no webp support'"

echo "== Settings file $DIR/.env"
if [ ! -f "$DIR/.env" ]; then
  install -m 600 -o bear -g bear "$DIR/discordbot/deploy/env.example" "$DIR/.env"
fi
chown bear:bear "$DIR/.env"
chmod 600 "$DIR/.env"

echo "== Offline tests (no network, no credits)"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_names_offline.py"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_discord_offline.py"
as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_discord_look_offline.py"
if ! as_bear "$DIR/.venv/bin/python" "$DIR/tests/test_discord_flow_offline.py" >"$DATA/flow-test.log" 2>&1; then
  tail -n 25 "$DATA/flow-test.log"
  echo "The Discord flow test failed (full output: $DATA/flow-test.log). Nothing was started."
  exit 1
fi
tail -n 1 "$DATA/flow-test.log"

echo "== Service"
install -m 644 "$DIR/discordbot/deploy/bear-bot.service" /etc/systemd/system/bear-bot.service
systemctl daemon-reload
systemctl enable -q bear-bot
if grep -q '=PASTE_HERE' "$DIR/.env"; then
  systemctl stop bear-bot 2>/dev/null || true
  echo
  echo "Almost done. Fill in the PASTE_HERE lines:   nano $DIR/.env"
  echo "then start the bot:                          systemctl restart bear-bot"
else
  systemctl restart bear-bot
  echo
  echo "Bot (re)started. Check it:  systemctl status bear-bot    log:  journalctl -u bear-bot -f"
fi
