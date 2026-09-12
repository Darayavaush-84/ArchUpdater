#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${ARCHUPDATER_INSTALL_ROOT:-/opt/archupdater}"
APP_LAUNCHER="/usr/local/bin/archupdater"
UNINSTALL_LAUNCHER="/usr/local/bin/archupdater-uninstall"
HELPER_DIR="/usr/lib/archupdater"
HELPER_WRAPPER="${HELPER_DIR}/archupdater-helper"
SELF_UPDATE_WRAPPER="${HELPER_DIR}/archupdater-self-update"
POLICY_DEST="/usr/share/polkit-1/actions/io.github.archupdater.policy"
DESKTOP_DIR="/usr/share/applications"
DESKTOP_DEST="${DESKTOP_DIR}/io.github.archupdater.desktop"
PURGE_USER_DATA=false

usage() {
    echo "Usage: sudo archupdater-uninstall [--purge-user-data]"
}

validate_install_root() {
    local normalized_path

    [[ "${INSTALL_ROOT}" = /* ]] || {
        echo "Error: ARCHUPDATER_INSTALL_ROOT must be an absolute path."
        exit 1
    }
    normalized_path="$(realpath -m -- "${INSTALL_ROOT}")"
    case "${normalized_path}" in
        /|/bin|/boot|/dev|/etc|/home|/lib|/lib64|/media|/mnt|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var)
            echo "Error: refusing unsafe ARCHUPDATER_INSTALL_ROOT: ${normalized_path}"
            exit 1
            ;;
    esac
    case "${normalized_path}" in
        /bin/*|/boot/*|/dev/*|/etc/*|/home/*|/lib/*|/lib64/*|/proc/*|/root/*|/run/*|/sbin/*|/sys/*|/tmp/*|/usr/*|/var/tmp/*)
            echo "Error: refusing an install root inside a sensitive system directory: ${normalized_path}"
            exit 1
            ;;
    esac
    [[ "${normalized_path##*/}" == "archupdater" ]] || {
        echo "Error: install root must name a dedicated 'archupdater' directory."
        exit 1
    }
    if [[ -L "${INSTALL_ROOT}" ]]; then
        echo "Error: refusing to remove a symlinked install root."
        exit 1
    fi
    INSTALL_ROOT="${normalized_path}"
}

tree_is_root_locked() {
    local insecure_path

    [[ -e "${INSTALL_ROOT}" ]] || return 0
    insecure_path="$(
        find "${INSTALL_ROOT}" \
            \( ! -user 0 -o \( ! -type l -perm /022 \) \) \
            -print -quit
    )"
    [[ -z "${insecure_path}" ]]
}

stop_running_archupdater() {
    local pids=()
    local pid
    local cmdline
    local waited=0

    command -v pgrep >/dev/null 2>&1 || return 0
    while IFS= read -r pid; do
        [[ -n "${pid}" ]] || continue
        cmdline="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
        case "${cmdline}" in
            *"/archupdater"*) pids+=("${pid}") ;;
        esac
    done < <(pgrep -x archupdater || true)
    [[ "${#pids[@]}" -gt 0 ]] || return 0

    kill "${pids[@]}" 2>/dev/null || true
    while [[ "${waited}" -lt 10 ]]; do
        local remaining=()
        for pid in "${pids[@]}"; do
            kill -0 "${pid}" 2>/dev/null && remaining+=("${pid}")
        done
        [[ "${#remaining[@]}" -gt 0 ]] || return 0
        pids=("${remaining[@]}")
        sleep 1
        waited=$((waited + 1))
    done
    kill -KILL "${pids[@]}" 2>/dev/null || true
}

purge_invoking_user_data() {
    local target_user="${SUDO_USER:-}"
    local passwd_entry
    local user_home

    if [[ -z "${target_user}" || "${target_user}" == "root" ]]; then
        echo "Error: --purge-user-data requires invocation through sudo by a non-root user."
        exit 1
    fi
    passwd_entry="$(getent passwd "${target_user}" || true)"
    [[ -n "${passwd_entry}" ]] || {
        echo "Error: could not resolve the invoking user."
        exit 1
    }
    IFS=: read -r _ _ _ _ _ user_home _ <<< "${passwd_entry}"
    [[ "${user_home}" = /* && "${user_home}" != "/" ]] || {
        echo "Error: refusing unsafe user home: ${user_home}"
        exit 1
    }

    rm -rf -- \
        "${user_home}/.cache/archupdater" \
        "${user_home}/.config/ArchUpdater"
    rm -f -- "${user_home}/.config/autostart/io.github.archupdater.desktop"
    echo "Removed ArchUpdater data for ${target_user}."
}

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        --purge-user-data) PURGE_USER_DATA=true ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage
            exit 2
            ;;
    esac
    shift
done

if [[ "${EUID}" -ne 0 ]]; then
    echo "This uninstaller must run as root."
    usage
    exit 1
fi

command -v realpath >/dev/null 2>&1 || {
    echo "realpath(1) is required."
    exit 1
}
validate_install_root
if [[ -e "${INSTALL_ROOT}" ]] && ! tree_is_root_locked; then
    echo "Error: refusing to remove an install root that is not root-owned and locked."
    exit 1
fi
if [[ -d "${INSTALL_ROOT}" ]]; then
    [[ ! -L "${INSTALL_ROOT}/.self-update.lock" ]] || {
        echo "Error: refusing a symlinked installation lock."
        exit 1
    }
    exec {install_lock}>"${INSTALL_ROOT}/.self-update.lock"
    flock -n "${install_lock}" || {
        echo "Error: an ArchUpdater installation or recovery is running."
        exit 1
    }
fi
stop_running_archupdater

rm -f -- \
    "${APP_LAUNCHER}" \
    "${UNINSTALL_LAUNCHER}" \
    "${HELPER_WRAPPER}" \
    "${SELF_UPDATE_WRAPPER}" \
    "${POLICY_DEST}" \
    "${DESKTOP_DEST}"
rmdir -- "${HELPER_DIR}" 2>/dev/null || true

if [[ "${PURGE_USER_DATA}" == true ]]; then
    purge_invoking_user_data
fi

if [[ -e "${INSTALL_ROOT}" ]]; then
    rm -rf -- "${INSTALL_ROOT}"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
fi

echo "ArchUpdater was removed successfully."
if [[ "${PURGE_USER_DATA}" == false ]]; then
    echo "User settings and logs were preserved."
fi
