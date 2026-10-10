# Auto-update for a self-hosted install (Raspberry Pi)

The updater keeps a git-cloned EdgeTales install on the latest `main`:
a systemd timer checks GitHub every 10 minutes, fast-forwards the clone,
restarts the app service and rolls back automatically if the new version
does not come up.

## What it does

1. `git fetch` — nothing to do if `origin/main` has not moved.
2. Refuses to update if tracked files were edited locally or the local branch diverged (logged, nothing is changed).
3. **Postpones while someone is playing** (open connections on the app port), but updates anyway after `MAX_DEFER_HOURS` (default 12).
4. `git merge --ff-only`, compile check of the `.py` files, `systemctl restart`.
5. Health check after `HEALTH_WAIT` seconds: service active **and** the app answers on its port.
   Otherwise: `git reset --hard` to the previous commit, restart, and the failed commit is skipped until a newer one arrives.

Untracked and ignored files — `config.json`, `.storage_secret`, `users/`, `logs/`, `voices/` — are never touched.
New Python dependencies are **not** installed automatically; a version that needs one fails the health check and is rolled back (see the log).

## Install

The install directory must be a **git clone** (not an SFTP copy). Converting an existing install:

```bash
sudo systemctl stop edgetales
mv ~/edgetales ~/edgetales-old
git clone https://github.com/edgetales/edgetales.git ~/edgetales
cp -a ~/edgetales-old/{config.json,.storage_secret,users} ~/edgetales/
cp -a ~/edgetales-old/logs ~/edgetales-old/voices ~/edgetales/ 2>/dev/null || true
sudo systemctl start edgetales
```

(For a private repository use a read-only deploy key or a fine-grained token with read access.)

Then:

```bash
cd ~/edgetales/deploy
sudo ./install-autoupdate.sh
```

This installs `/usr/local/sbin/edgetales-update`, `edgetales-update.service` + `.timer`,
and `/etc/default/edgetales-update` with `APP_DIR` set to the clone.

## Settings

`/etc/default/edgetales-update`:

| Variable | Default | Meaning |
|---|---|---|
| `APP_DIR` | `/home/swart/edgetales` | the git clone |
| `APP_USER` | owner of `APP_DIR` | git runs as this user |
| `SERVICE` | `edgetales.service` | app unit to restart |
| `BRANCH` | `main` | branch to follow |
| `PYTHON` | `python3` | interpreter for the compile check |
| `PORT` | `port` from `config.json`, else 8080 | for the connection and health checks |
| `SKIP_IF_ACTIVE` | `1` | postpone while clients are connected |
| `MAX_DEFER_HOURS` | `12` | update anyway after this long |
| `HEALTH_WAIT` | `25` | seconds between restart and health check |

## Everyday use

```bash
journalctl -u edgetales-update -n 50          # what happened
sudo systemctl start edgetales-update         # update now (still postpones if someone plays)
sudo SKIP_IF_ACTIVE=0 /usr/local/sbin/edgetales-update   # update now, no matter what
systemctl list-timers edgetales-update.timer  # next check
sudo systemctl disable --now edgetales-update.timer      # switch off
```

Do not edit tracked files on the Pi (e.g. via SFTP upload-on-save) — the updater then stops until the changes are reverted (`git checkout -- .`).
After the install script itself changes, re-run `sudo ./install-autoupdate.sh`.
