#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${ARCHUPDATER_INSTALL_ROOT:-/opt/archupdater}"
SYSTEM_BIN_DIR="/usr/local/bin"
HELPER_DIR="/usr/lib/archupdater"
HELPER_WRAPPER="${HELPER_DIR}/archupdater-helper"
POLICY_SRC="${PROJECT_ROOT}/resources/polkit/io.github.archupdater.policy"
POLICY_DIR="/usr/share/polkit-1/actions"
POLICY_DEST="${POLICY_DIR}/io.github.archupdater.policy"
DESKTOP_TEMPLATE="${PROJECT_ROOT}/resources/desktop/io.github.archupdater.desktop"
DESKTOP_DIR="/usr/share/applications"
DESKTOP_DEST="${DESKTOP_DIR}/io.github.archupdater.desktop"
UNINSTALL_SRC="${PROJECT_ROOT}/uninstall.sh"
APP_LAUNCHER="${SYSTEM_BIN_DIR}/archupdater"
UNINSTALL_LAUNCHER="${SYSTEM_BIN_DIR}/archupdater-uninstall"
APP_EXECUTABLE_NAME="archupdater"
RELEASES_DIR=""
CURRENT_LINK=""
UNINSTALL_DEST=""
SOURCE_BUILD_DIR=""
STAGING_RELEASE=""

cleanup_temporary_paths() {
    if [[ -n "${SOURCE_BUILD_DIR}" && -d "${SOURCE_BUILD_DIR}" ]]; then
        rm -rf -- "${SOURCE_BUILD_DIR}"
    fi
    if [[ \
        -n "${STAGING_RELEASE}" \
        && -n "${RELEASES_DIR}" \
        && "${STAGING_RELEASE}" == "${RELEASES_DIR}"/* \
        && -d "${STAGING_RELEASE}" \
    ]]; then
        rm -rf -- "${STAGING_RELEASE}"
    fi
}

trap cleanup_temporary_paths EXIT

validate_install_root() {
    local raw_path="$1"
    local normalized_path

    [[ "${raw_path}" = /* ]] || {
        echo "Error: ARCHUPDATER_INSTALL_ROOT must be an absolute path."
        exit 1
    }
    normalized_path="$(realpath -m -- "${raw_path}")"
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
    if [[ "${normalized_path##*/}" != "archupdater" ]]; then
        echo "Error: ARCHUPDATER_INSTALL_ROOT must name a dedicated 'archupdater' directory."
        exit 1
    fi
    INSTALL_ROOT="${normalized_path}"
    RELEASES_DIR="${INSTALL_ROOT}/releases"
    CURRENT_LINK="${INSTALL_ROOT}/current"
    UNINSTALL_DEST="${INSTALL_ROOT}/uninstall.sh"
}

ensure_not_symlink() {
    local path="$1"
    if [[ -L "${path}" ]]; then
        echo "Error: refusing to use symlink path: ${path}"
        exit 1
    fi
}

tree_is_root_locked() {
    local path="$1"
    local insecure_path

    [[ -e "${path}" ]] || return 0
    insecure_path="$(
        find "${path}" \
            \( ! -user 0 -o \( ! -type l -perm /022 \) \) \
            -print -quit
    )"
    [[ -z "${insecure_path}" ]]
}

secure_tree() {
    local path="$1"

    [[ -e "${path}" ]] || return 0
    chown -R root:root "${path}"
    chmod -R go-w "${path}"
}

validate_current_link() {
    local target

    if [[ ! -e "${CURRENT_LINK}" && ! -L "${CURRENT_LINK}" ]]; then
        return 0
    fi
    if [[ ! -L "${CURRENT_LINK}" ]]; then
        echo "Error: ${CURRENT_LINK} must be a symlink managed by ArchUpdater."
        exit 1
    fi
    target="$(realpath -m -- "${CURRENT_LINK}")"
    case "${target}" in
        "${RELEASES_DIR}"/*) ;;
        *)
            echo "Error: refusing current release link outside ${RELEASES_DIR}."
            exit 1
            ;;
    esac
}

require_commands() {
    local command
    for command in install tar realpath mktemp mv ln date; do
        command -v "${command}" >/dev/null 2>&1 || {
            echo "${command} is required."
            exit 1
        }
    done
}

require_supported_python() {
    python3 - <<'PY'
import sys

if sys.version_info < (3, 12):
    raise SystemExit("Error: ArchUpdater requires Python 3.12 or newer.")
PY
}

ensure_system_dependencies() {
    local required_packages=(git python pacman-contrib fakeroot polkit qt6-svg)
    local missing_packages=()
    local package

    if ! command -v pacman >/dev/null 2>&1; then
        echo "Error: this installer requires an Arch-based system with Pacman."
        return 1
    fi
    for package in "${required_packages[@]}"; do
        if ! pacman -Q "${package}" >/dev/null 2>&1; then
            missing_packages+=("${package}")
        fi
    done
    if [[ "${#missing_packages[@]}" -eq 0 ]]; then
        return 0
    fi

    echo "Installing missing system dependencies: ${missing_packages[*]}"
    echo "Pacman will also perform a full system upgrade to keep packages compatible."
    echo "Review and confirm the Pacman transaction below to continue."
    if ! pacman -Syu --needed "${missing_packages[@]}"; then
        echo "Error: dependency installation was cancelled or failed. ArchUpdater was not installed."
        return 1
    fi
    for package in "${required_packages[@]}"; do
        if ! pacman -Q "${package}" >/dev/null 2>&1; then
            echo "Error: required system package is still missing: ${package}"
            return 1
        fi
    done
}

prepare_clean_source_tree() {
    SOURCE_BUILD_DIR="$(mktemp -d -t archupdater-source.XXXXXXXX)"
    tar \
        --exclude='./.git' \
        --exclude='./.codex' \
        --exclude='./.venv' \
        --exclude='./venv' \
        --exclude='./build' \
        --exclude='./dist' \
        --exclude='./.pytest_cache' \
        --exclude='./__pycache__' \
        --exclude='*.egg-info' \
        --exclude='*.pyc' \
        -C "${PROJECT_ROOT}" -cf - . \
        | tar -C "${SOURCE_BUILD_DIR}" -xf -
}

stop_running_archupdater() {
    local matched_pids=()
    local pid
    local cmdline
    local waited=0

    if ! command -v pgrep >/dev/null 2>&1; then
        return 0
    fi

    while IFS= read -r pid; do
        [[ -n "${pid}" ]] || continue
        cmdline="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
        case "${cmdline}" in
            *"/archupdater"*) matched_pids+=("${pid}") ;;
        esac
    done < <(pgrep -x "${APP_EXECUTABLE_NAME}" || true)

    if [[ "${#matched_pids[@]}" -eq 0 ]]; then
        return 0
    fi

    echo "Stopping running ArchUpdater instance(s): ${matched_pids[*]}"
    kill "${matched_pids[@]}" 2>/dev/null || true

    while [[ "${waited}" -lt 10 ]]; do
        local still_running=()
        for pid in "${matched_pids[@]}"; do
            if kill -0 "${pid}" 2>/dev/null; then
                still_running+=("${pid}")
            fi
        done
        if [[ "${#still_running[@]}" -eq 0 ]]; then
            return 0
        fi
        matched_pids=("${still_running[@]}")
        sleep 1
        waited=$((waited + 1))
    done

    echo "Force stopping ArchUpdater instance(s): ${matched_pids[*]}"
    kill -KILL "${matched_pids[@]}" 2>/dev/null || true
}

install_executable_text() {
    local destination="$1"
    local temporary_path="$2"

    chown root:root "${temporary_path}"
    chmod 0755 "${temporary_path}"
    mv -fT -- "${temporary_path}" "${destination}"
}

cleanup_obsolete_releases() {
    local current_release="$1"
    local previous_release="$2"
    local candidate
    local resolved

    for candidate in "${RELEASES_DIR}"/*; do
        [[ -d "${candidate}" && ! -L "${candidate}" ]] || continue
        resolved="$(realpath -m -- "${candidate}")"
        [[ "${resolved}" != "${current_release}" ]] || continue
        [[ -z "${previous_release}" || "${resolved}" != "${previous_release}" ]] || continue
        case "${resolved}" in
            "${RELEASES_DIR}"/*) rm -rf -- "${resolved}" ;;
        esac
    done
}

if [[ "${EUID}" -ne 0 ]]; then
    echo "This installer must run as root."
    echo "Use: sudo ./install.sh"
    exit 1
fi

require_commands
validate_install_root "${INSTALL_ROOT}"

for path in \
    "${INSTALL_ROOT}" \
    "${RELEASES_DIR}" \
    "${APP_LAUNCHER}" \
    "${UNINSTALL_LAUNCHER}" \
    "${HELPER_DIR}" \
    "${HELPER_WRAPPER}" \
    "${POLICY_DEST}" \
    "${DESKTOP_DEST}"
do
    ensure_not_symlink "${path}"
done
validate_current_link

if [[ -e "${INSTALL_ROOT}" ]] && ! tree_is_root_locked "${INSTALL_ROOT}"; then
    echo "Error: existing install root is not fully root-owned and non-writable by other users."
    exit 1
fi

ensure_system_dependencies
require_supported_python

PACKAGE_VERSION="$(
    python3 - "${PROJECT_ROOT}/pyproject.toml" <<'PY'
import pathlib
import sys
import tomllib

print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text())["project"]["version"])
PY
)"
if [[ ! "${PACKAGE_VERSION}" =~ ^[0-9]+([.][0-9]+)+$ ]]; then
    echo "Error: unsupported package version: ${PACKAGE_VERSION}"
    exit 1
fi

echo "Staging ArchUpdater ${PACKAGE_VERSION} for ${INSTALL_ROOT}"
install -d -o root -g root -m 0755 \
    "${INSTALL_ROOT}" \
    "${RELEASES_DIR}" \
    "${SYSTEM_BIN_DIR}" \
    "${HELPER_DIR}" \
    "${POLICY_DIR}" \
    "${DESKTOP_DIR}"

release_suffix="$(date -u +%Y%m%dT%H%M%SZ)-$$"
FINAL_RELEASE="${RELEASES_DIR}/${PACKAGE_VERSION}-${release_suffix}"
install -d -o root -g root -m 0755 "${FINAL_RELEASE}"
STAGING_RELEASE="${FINAL_RELEASE}"
STAGING_VENV="${STAGING_RELEASE}/venv"
python3 -m venv --system-site-packages "${STAGING_VENV}"
prepare_clean_source_tree
"${STAGING_VENV}/bin/pip" install --upgrade "${SOURCE_BUILD_DIR}"
"${STAGING_VENV}/bin/python" - "${PACKAGE_VERSION}" <<'PY'
import sys
import archupdater

if archupdater.__version__ != sys.argv[1]:
    raise SystemExit(
        f"Installed version mismatch: expected {sys.argv[1]}, found {archupdater.__version__}"
    )
PY
for entrypoint in archupdater archupdater-helper; do
    [[ -x "${STAGING_VENV}/bin/${entrypoint}" ]] || {
        echo "Error: staged entrypoint is missing: ${entrypoint}"
        exit 1
    }
done
chmod 0755 "${STAGING_RELEASE}"
secure_tree "${STAGING_RELEASE}"

previous_release=""
if [[ -L "${CURRENT_LINK}" ]]; then
    previous_release="$(realpath -m -- "${CURRENT_LINK}")"
fi

stop_running_archupdater

next_link="${INSTALL_ROOT}/.current-${release_suffix}"

app_launcher_tmp="$(mktemp "${SYSTEM_BIN_DIR}/.archupdater.XXXXXXXX")"
cat > "${app_launcher_tmp}" <<EOF
#!/usr/bin/env bash
unset PYTHONPATH PYTHONHOME
exec "${CURRENT_LINK}/venv/bin/archupdater" "\$@"
EOF
install_executable_text "${APP_LAUNCHER}" "${app_launcher_tmp}"

helper_wrapper_tmp="$(mktemp "${HELPER_DIR}/.archupdater-helper.XXXXXXXX")"
cat > "${helper_wrapper_tmp}" <<EOF
#!/usr/bin/env bash
unset PYTHONPATH PYTHONHOME
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
exec "${CURRENT_LINK}/venv/bin/archupdater-helper" "\$@"
EOF
install_executable_text "${HELPER_WRAPPER}" "${helper_wrapper_tmp}"

uninstall_tmp="$(mktemp "${INSTALL_ROOT}/.uninstall.XXXXXXXX")"
install -o root -g root -m 0755 "${UNINSTALL_SRC}" "${uninstall_tmp}"
mv -fT -- "${uninstall_tmp}" "${UNINSTALL_DEST}"

uninstall_launcher_tmp="$(mktemp "${SYSTEM_BIN_DIR}/.archupdater-uninstall.XXXXXXXX")"
cat > "${uninstall_launcher_tmp}" <<EOF
#!/usr/bin/env bash
exec "${UNINSTALL_DEST}" "\$@"
EOF
install_executable_text "${UNINSTALL_LAUNCHER}" "${uninstall_launcher_tmp}"

policy_tmp="$(mktemp "${POLICY_DIR}/.io.github.archupdater.policy.XXXXXXXX")"
install -o root -g root -m 0644 "${POLICY_SRC}" "${policy_tmp}"
mv -fT -- "${policy_tmp}" "${POLICY_DEST}"

desktop_tmp="$(mktemp "${DESKTOP_DIR}/.io.github.archupdater.desktop.XXXXXXXX")"
python3 - "${DESKTOP_TEMPLATE}" "${desktop_tmp}" "${APP_LAUNCHER}" <<'PY'
import pathlib
import sys

template = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
desktop = template.replace("@ARCHUPDATER_EXEC@", sys.argv[3])
pathlib.Path(sys.argv[2]).write_text(desktop, encoding="utf-8")
PY
chown root:root "${desktop_tmp}"
chmod 0644 "${desktop_tmp}"
mv -fT -- "${desktop_tmp}" "${DESKTOP_DEST}"

# Switch the active release only after every generated integration file is ready.
ln -s "releases/${FINAL_RELEASE##*/}" "${next_link}"
mv -fT -- "${next_link}" "${CURRENT_LINK}"
STAGING_RELEASE=""

secure_tree "${INSTALL_ROOT}"
secure_tree "${HELPER_DIR}"

legacy_venv="${INSTALL_ROOT}/venv"
if [[ -d "${legacy_venv}" && ! -L "${legacy_venv}" ]] && tree_is_root_locked "${legacy_venv}"; then
    rm -rf -- "${legacy_venv}"
fi
cleanup_obsolete_releases "${FINAL_RELEASE}" "${previous_release}"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "${DESKTOP_DIR}" >/dev/null 2>&1 || true
fi

echo
echo "ArchUpdater ${PACKAGE_VERSION} installed successfully."
echo "Active release: ${FINAL_RELEASE}"
echo "Launcher: ${APP_LAUNCHER}"
echo "Desktop entry: ${DESKTOP_DEST}"
echo "Privileged helper: ${HELPER_WRAPPER}"
echo "Uninstaller: ${UNINSTALL_LAUNCHER}"
