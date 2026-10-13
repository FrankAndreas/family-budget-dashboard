#!/bin/bash
# Nightly auto-update for a Family Budget Docker deployment (e.g. on a Synology NAS).
#
# Pulls the app images (backend, frontend) and, only if a newer image was
# published, backs up the SQLite database, recreates the app containers and waits
# until the backend is healthy. The compose/.env configuration is never
# changed by this script.
#
# Usage:   nas-update.sh [--force] [APP_DIR]
#   APP_DIR  folder containing the compose file (compose.yaml, docker-compose.yml, ...)
#            (default: the folder this script is in)
#   --force  recreate the app containers even if no new image was pulled
#            (e.g. after editing the compose file)
#
# Exit codes: 0 = up to date or updated successfully, 1 = failure.
# See README_DOCKER.md ("Automatic Updates") for the Task Scheduler setup.

set -uo pipefail

# Task Scheduler runs with a minimal PATH; Docker lives in /usr/local/bin on DSM
export PATH="$PATH:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

APP_SERVICES="backend frontend"
BACKUP_KEEP=5        # always keep at least the newest 5 backups
BACKUP_MIN_DAYS=7    # and every backup younger than 7 days
HEALTH_TIMEOUT=300

FORCE=0
APP_DIR=""
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) APP_DIR="$arg" ;;
    esac
done
APP_DIR="${APP_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$APP_DIR" || { echo "Cannot cd to $APP_DIR"; exit 1; }

LOG_DIR="$APP_DIR/logs"
BACKUP_DIR="$APP_DIR/db-backups"
mkdir -p "$LOG_DIR" "$BACKUP_DIR"
LOG_FILE="$LOG_DIR/update.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG_FILE"; }
fail() { log "FAILED: $*"; exit 1; }

# Only one run at a time (mkdir is atomic; flock isn't available everywhere)
LOCK_DIR="$APP_DIR/.update.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    log "Another update is running (remove $LOCK_DIR if it is stale)"
    exit 1
fi
trap 'rmdir "$LOCK_DIR"' EXIT

compose_file=""
for f in compose.yaml compose.yml docker-compose.yaml docker-compose.yml; do
    [ -f "$f" ] && { compose_file=$f; break; }
done
[ -n "$compose_file" ] || fail "no compose file (compose.yaml or docker-compose.yml) in $APP_DIR"

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    fail "neither 'docker compose' nor 'docker-compose' found"
fi

# Reuse the project name of the running stack, so a project created in the
# Container Manager UI isn't duplicated under the folder name
if [ -z "${COMPOSE_PROJECT_NAME:-}" ]; then
    backend_id=$("${COMPOSE[@]}" ps -q backend 2>/dev/null | head -n1)
    [ -z "$backend_id" ] && backend_id=$(docker ps -aq --filter name='^budget-backend$' | head -n1)
    if [ -n "$backend_id" ]; then
        project=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$backend_id" 2>/dev/null)
        workdir=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$backend_id" 2>/dev/null)
        # Never take over a stack that was started from another folder
        if [ -n "$workdir" ] && [ "$(cd "$workdir" 2>/dev/null && pwd -P)" != "$(pwd -P)" ]; then
            fail "budget-backend belongs to the stack in $workdir, not $APP_DIR; run the script from that folder or set COMPOSE_PROJECT_NAME"
        fi
        [ -n "$project" ] && export COMPOSE_PROJECT_NAME="$project"
    fi
fi
compose() { "${COMPOSE[@]}" "$@"; }

# Container of a service, running or stopped (running_container_of: running only)
container_of() { compose ps -a -q "$1" 2>/dev/null | head -n1; }
running_container_of() { compose ps -q "$1" 2>/dev/null | head -n1; }

# True if the service's container is missing or runs an older image than the local tag
needs_update() {
    local service=$1 cid image running latest
    cid=$(container_of "$service")
    [ -z "$cid" ] && return 0
    image=$(docker inspect -f '{{.Config.Image}}' "$cid") || return 0
    running=$(docker inspect -f '{{.Image}}' "$cid")
    latest=$(docker image inspect -f '{{.Id}}' "$image" 2>/dev/null) || return 0
    [ "$running" != "$latest" ]
}

log "Checking for updates in $APP_DIR (project: ${COMPOSE_PROJECT_NAME:-default})"
compose pull --quiet $APP_SERVICES >>"$LOG_FILE" 2>&1 || fail "docker pull failed (network or registry login?)"

changed=""
for service in $APP_SERVICES; do
    needs_update "$service" && changed="$changed $service"
done

if [ -z "$changed" ] && [ "$FORCE" -eq 0 ]; then
    log "Up to date"
    exit 0
fi
log "Updating:${changed:- (forced)}"

# Back up the database first: a new version may change it when it starts.
# Writes the backup to stdout, using SQLite's online-backup API (a consistent
# copy even while the backend is writing), through the running backend or a
# one-off backend container if it is stopped
backup_sqlite() {
    local runner=(exec -T backend)
    [ -z "$(running_container_of backend)" ] && runner=(run --rm --no-deps -T backend)
    compose "${runner[@]}" python -c '
import os, sqlite3, sys, tempfile
path = os.environ["DATABASE_URL"].split("sqlite:///", 1)[1]
tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
tmp.close()
src = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
dst = sqlite3.connect(tmp.name)
src.backup(dst)
dst.close()
src.close()
with open(tmp.name, "rb") as f:
    sys.stdout.buffer.write(f.read())
os.unlink(tmp.name)
'
}

backend_cid=$(container_of backend)
database_url=""
[ -n "$backend_cid" ] && database_url=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$backend_cid" \
    | sed -n 's/^DATABASE_URL=//p' | head -n1)
stamp=$(date '+%Y%m%d-%H%M%S')
case "$database_url" in
    sqlite:///*)
        backup="$BACKUP_DIR/budget-$stamp.sqlite.gz"
        backup_sqlite | gzip > "$backup" && [ "$(gzip -dc "$backup" | head -c 15)" = "SQLite format 3" ] ;;
    *) backup="" ;;
esac
backup_ok=$?
if [ -z "$backup" ]; then
    log "No database to back up yet (no backend container yet)"
elif [ "$backup_ok" -eq 0 ]; then
    log "Database backup: $backup"
    # Delete a backup only if it is beyond the newest $BACKUP_KEEP and older than $BACKUP_MIN_DAYS days
    ls -1t "$BACKUP_DIR"/budget-*.gz 2>/dev/null | tail -n +$((BACKUP_KEEP + 1)) | while read -r old; do
        if [ -n "$(find "$old" -mmin +$((BACKUP_MIN_DAYS * 24 * 60)))" ]; then
            rm -f "$old" && log "Removed old backup $(basename "$old")"
        fi
    done
else
    rm -f "$backup"
    fail "database backup failed, not updating"
fi

# Keep the running images as :previous, so pruning can't remove them and a
# rollback stays possible (see "Rolling back" in README_DOCKER.md)
for service in $changed; do
    cid=$(container_of "$service")
    [ -z "$cid" ] && continue
    image=$(docker inspect -f '{{.Config.Image}}' "$cid")
    docker tag "$(docker inspect -f '{{.Image}}' "$cid")" "${image%:*}:previous" \
        && log "Kept current $service image as ${image%:*}:previous"
done

compose up -d $APP_SERVICES >>"$LOG_FILE" 2>&1 || fail "docker compose up failed"
# nginx resolves the backend's address once at startup; a recreated backend may have a new one
case "$changed" in
    *backend*) compose restart frontend >>"$LOG_FILE" 2>&1 || fail "restarting frontend failed" ;;
esac

# Wait for the backend's Docker healthcheck
deadline=$(( $(date +%s) + HEALTH_TIMEOUT ))
status=""
while [ "$(date +%s)" -lt "$deadline" ]; do
    cid=$(container_of backend)
    status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null)
    [ "$status" = "healthy" ] && break
    sleep 10
done
if [ "$status" != "healthy" ]; then
    compose logs --tail 50 backend >>"$LOG_FILE" 2>&1
    fail "backend not healthy after ${HEALTH_TIMEOUT}s (status: ${status:-unknown}); last logs in $LOG_FILE, backup in $BACKUP_DIR"
fi

# Remove superseded (dangling) images to save disk space
docker image prune -f >/dev/null 2>&1

log "Update complete, backend healthy"
