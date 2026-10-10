#!/usr/bin/env bash
# EdgeTales auto-updater for a git-cloned install (e.g. Raspberry Pi).
#
# Fast-forwards the install to origin/$BRANCH, restarts the service and rolls
# back to the previous commit if the new version does not come up healthy.
# Runs as root (from edgetales-update.service); all git operations run as
# $APP_USER so file ownership in the install never changes.
#
# Untracked/ignored files (config.json, .storage_secret, users/, logs/, voices/)
# are never touched: only fast-forward merges and, on rollback, a reset of
# tracked files are performed.
#
# Settings (override in /etc/default/edgetales-update):
#   APP_DIR          install directory (git clone)      default /home/swart/edgetales
#   APP_USER         owner of the install               default: owner of APP_DIR
#   SERVICE          systemd unit of the app            default edgetales.service
#   BRANCH           branch to follow                   default main
#   PYTHON           interpreter used by the service    default python3
#   PORT             app port (else config.json/8080)
#   SKIP_IF_ACTIVE   1 = postpone while clients are connected   default 1
#   MAX_DEFER_HOURS  update anyway after this many hours        default 12
#   HEALTH_WAIT      seconds to wait after restart              default 25
set -euo pipefail

APP_DIR="${APP_DIR:-/home/swart/edgetales}"
APP_USER="${APP_USER:-$(stat -c %U "$APP_DIR")}"
SERVICE="${SERVICE:-edgetales.service}"
BRANCH="${BRANCH:-main}"
PYTHON="${PYTHON:-python3}"
SKIP_IF_ACTIVE="${SKIP_IF_ACTIVE:-1}"
MAX_DEFER_HOURS="${MAX_DEFER_HOURS:-12}"
HEALTH_WAIT="${HEALTH_WAIT:-25}"
STATE_DIR="${STATE_DIR:-/var/lib/edgetales-update}"
DEFER_FILE="$STATE_DIR/deferred_since"

log() { echo "[edgetales-update] $*"; }
as_user() { runuser -u "$APP_USER" -- "$@"; }
g() { as_user git -C "$APP_DIR" "$@"; }

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/lock"
flock -n 9 || { log "another update is running"; exit 0; }

[ -d "$APP_DIR/.git" ] || { log "ERROR: $APP_DIR is not a git clone (see deploy/README.md)"; exit 1; }

g fetch --quiet origin "$BRANCH"
OLD="$(g rev-parse HEAD)"
NEW="$(g rev-parse "origin/$BRANCH")"
if [ "$OLD" = "$NEW" ]; then
    rm -f "$DEFER_FILE"
    exit 0
fi

if ! g merge-base --is-ancestor HEAD "origin/$BRANCH"; then
    log "ERROR: local branch has diverged from origin/$BRANCH - not updating"
    exit 1
fi
if [ -n "$(g status --porcelain --untracked-files=no)" ]; then
    log "ERROR: tracked files were modified locally - not updating:"
    g status --short --untracked-files=no
    exit 1
fi

if [ -f "$STATE_DIR/bad_commit" ] && [ "$(cat "$STATE_DIR/bad_commit")" = "$NEW" ]; then
    exit 0   # this commit failed before - wait for a newer one
fi

# Port: env > config.json > 8080
if [ -z "${PORT:-}" ]; then
    PORT="$(cd "$APP_DIR" && "$PYTHON" -c 'import json
try:
    print(int(json.load(open("config.json", encoding="utf-8")).get("port", 8080)))
except Exception:
    print(8080)' 2>/dev/null || echo 8080)"
fi

# Postpone while someone is playing (open websocket connections), but not forever.
if [ "$SKIP_IF_ACTIVE" = "1" ]; then
    ACTIVE="$(ss -Htn state established "( sport = :$PORT )" 2>/dev/null | wc -l)"
    if [ "$ACTIVE" -gt 0 ]; then
        now="$(date +%s)"
        [ -f "$DEFER_FILE" ] || echo "$now" > "$DEFER_FILE"
        since="$(cat "$DEFER_FILE")"
        if [ $(( now - since )) -lt $(( MAX_DEFER_HOURS * 3600 )) ]; then
            log "update ${NEW:0:7} pending, $ACTIVE active connection(s) - postponed"
            exit 0
        fi
        log "update pending for more than ${MAX_DEFER_HOURS}h - updating despite $ACTIVE connection(s)"
    fi
fi

log "updating ${OLD:0:7} -> ${NEW:0:7}"
g --no-pager log --oneline "$OLD..$NEW" | sed 's/^/[edgetales-update]   /'
g merge --ff-only --quiet "origin/$BRANCH"

healthy() {
    systemctl is-active --quiet "$SERVICE" || return 1
    local code
    for scheme in http https; do
        code="$(curl -sk -o /dev/null -m 10 -w '%{http_code}' "$scheme://127.0.0.1:$PORT/" || true)"
        case "$code" in 2??|3??) return 0 ;; esac
    done
    return 1
}

rollback() {
    log "ERROR: $1 - rolling back to ${OLD:0:7}"
    g reset --hard --quiet "$OLD"
    systemctl restart "$SERVICE" || true
    sleep "$HEALTH_WAIT"
    if healthy; then
        log "rollback successful, still on ${OLD:0:7}"
    else
        log "ERROR: service unhealthy even after rollback - check: journalctl -u $SERVICE"
    fi
    # Remember the bad commit so the same version is not retried every few minutes.
    echo "$NEW" > "$STATE_DIR/bad_commit"
    exit 1
}

if ! (cd "$APP_DIR" && as_user "$PYTHON" -m py_compile app.py engine.py i18n.py voice.py); then
    rollback "new version does not compile"
fi

systemctl restart "$SERVICE"
sleep "$HEALTH_WAIT"
healthy || rollback "service not healthy after restart"

rm -f "$DEFER_FILE" "$STATE_DIR/bad_commit"
VER="$(grep -m1 -oP '^VERSION\s*=\s*"\K[^"]+' "$APP_DIR/engine.py" || echo '?')"
log "updated to ${NEW:0:7} (EdgeTales $VER)"
