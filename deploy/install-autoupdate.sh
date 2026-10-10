#!/usr/bin/env bash
# Installs the EdgeTales auto-updater (run with sudo from the repo's deploy/ folder).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run with sudo"; exit 1; }
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$HERE")"
install -m 755 "$HERE/edgetales-update.sh" /usr/local/sbin/edgetales-update
install -m 644 "$HERE/edgetales-update.service" /etc/systemd/system/edgetales-update.service
install -m 644 "$HERE/edgetales-update.timer" /etc/systemd/system/edgetales-update.timer
if [ ! -f /etc/default/edgetales-update ]; then
    printf 'APP_DIR=%s\n# SERVICE=edgetales.service\n# BRANCH=main\n# SKIP_IF_ACTIVE=1\n# MAX_DEFER_HOURS=12\n' "$APP_DIR" \
        > /etc/default/edgetales-update
fi
systemctl daemon-reload
systemctl enable --now edgetales-update.timer
echo "Installed. Status: systemctl list-timers edgetales-update.timer"
echo "Log:    journalctl -u edgetales-update -f"
echo "Now:    sudo systemctl start edgetales-update"
