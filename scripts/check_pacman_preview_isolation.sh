#!/usr/bin/env bash
set -euo pipefail

command -v checkupdates >/dev/null 2>&1 || {
    echo "checkupdates is required."
    exit 1
}

preview_db="$(mktemp -d -t archupdater-preview-db.XXXXXXXX)"
before_snapshot="$(mktemp -t archupdater-pacman-before.XXXXXXXX)"
after_snapshot="$(mktemp -t archupdater-pacman-after.XXXXXXXX)"

cleanup() {
    rm -rf -- "${preview_db}"
    rm -f -- "${before_snapshot}" "${after_snapshot}"
}
trap cleanup EXIT

snapshot_sync_db() {
    if [[ -d /var/lib/pacman/sync ]]; then
        find /var/lib/pacman/sync -maxdepth 1 -type f -printf '%f\t%s\t%T@\n' | sort
    fi
}

snapshot_sync_db > "${before_snapshot}"
set +e
CHECKUPDATES_DB="${preview_db}" checkupdates --nocolor >/dev/null
status=$?
set -e
if [[ "${status}" -ne 0 && "${status}" -ne 2 ]]; then
    echo "checkupdates failed with exit code ${status}."
    exit "${status}"
fi
snapshot_sync_db > "${after_snapshot}"
cmp --silent "${before_snapshot}" "${after_snapshot}" || {
    echo "The isolated preview modified the live Pacman sync database."
    exit 1
}
find "${preview_db}/sync" -maxdepth 1 -type f -name '*.db' -print -quit | grep -q . || {
    echo "The isolated preview did not create private sync databases."
    exit 1
}

echo "Pacman preview stayed inside ${preview_db}."
