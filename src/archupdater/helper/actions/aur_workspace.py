from __future__ import annotations

import os
import pwd
import re
import secrets
import select
import shlex
import shutil
import signal
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from archupdater.domain.aur import (
    AurPkgbuildReview,
)
from archupdater.helper.actions import validation

MAX_AUR_ARTIFACT_BYTES = 8 * 1024 * 1024 * 1024


COPY_CHUNK_BYTES = 1024 * 1024


SYSTEMD_RUN_PATH = Path("/usr/bin/systemd-run")
SYSTEMCTL_PATH = Path("/usr/bin/systemctl")
GPG_PATH = Path("/usr/bin/gpg")
BASH_PATH = Path("/usr/bin/bash")
# DynamicUser= keeps StateDirectory= below the root-only /var/lib/private, so
# processes of the desktop user cannot reach the build or its packages.
AUR_STATE_NAME = "archupdater-aur"
AUR_STATE_ROOT = Path("/var/lib/private") / AUR_STATE_NAME
AUR_STATE_LINK_ROOT = Path("/var/lib") / AUR_STATE_NAME
AUR_UNIT_PREFIX = "archupdater-aur-"
BUILD_INPUT_MOUNT = "/run/archupdater-aur-input"
BUILD_UNIT_TIMEOUT_SECONDS = 6 * 60 * 60
BUILD_TOKEN_RE = re.compile(r"^[0-9a-f]{12}$")
PGP_FINGERPRINT_RE = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})$")
MAKEFLAGS_TOKEN_RE = re.compile(
    r"^(?:-j[1-9][0-9]{0,3}|--jobs=[1-9][0-9]{0,3}"
    r"|-l[0-9]{1,4}(?:\.[0-9]{1,2})?|--load-average=[0-9]{1,4}(?:\.[0-9]{1,2})?)$"
)
MAX_USER_HELPER_OUTPUT_BYTES = 1024 * 1024
PROXY_VARIABLES = (
    "http_proxy", "https_proxy", "ftp_proxy", "no_proxy",
    "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "NO_PROXY",
)

BUILD_PHASE_FULL = "full"
# A development package is built in two units: "fetch" only downloads and checks
# sources, root then verifies the approved Git commits, and "build" compiles from
# those mirrors without fetching again.
BUILD_PHASE_FETCH = "fetch"
BUILD_PHASE_BUILD = "build"
BUILD_PHASES = (BUILD_PHASE_FULL, BUILD_PHASE_FETCH, BUILD_PHASE_BUILD)

# Runs inside the transient unit as its dynamic user. The reviewed checkout, the
# generated makepkg.conf and the exported public keys are bind-mounted read-only.
BUILD_UNIT_SCRIPT = r"""
set -euo pipefail
umask 022
work="$STATE_DIRECTORY"
input="$ARCHUPDATER_INPUT"
phase="$ARCHUPDATER_PHASE"
case "$phase" in
    full|fetch)
        mkdir -p "$work/home" "$work/build" "$work/logs" "$work/packages" "$work/sources" \
            "$work/source-packages" "$work/tmp"
        mkdir -m 0700 "$work/gnupg"
        cp -R --no-preserve=ownership -- "$input/checkout" "$work/checkout"
        chmod -R u+w -- "$work/checkout"
        if [[ -s "$input/pgp-keys" ]]; then
            gpg --homedir "$work/gnupg" --batch --quiet --import "$input/pgp-keys"
        fi
        ;;
    build)
        [[ -d "$work/checkout" ]]
        ;;
    *)
        echo "Unknown build phase: $phase" >&2
        exit 2
        ;;
esac
export HOME="$work/home" GNUPGHOME="$work/gnupg" TMPDIR="$work/tmp"
export BUILDDIR="$work/build" LOGDEST="$work/logs" PKGDEST="$work/packages"
export SRCDEST="$work/sources" SRCPKGDEST="$work/source-packages"
export MAKEPKG_CONF="$input/makepkg.conf"
cd "$work/checkout"
case "$phase" in
    # --verifysource downloads (Git sources as mirrors) and checks integrity, then
    # exits before extraction: no prepare(), pkgver() or build() runs.
    fetch) exec /usr/bin/makepkg --verifysource --noconfirm --noprogressbar ;;
    # --holdver keeps the verified mirrors; the working copy is created from them
    # before prepare() runs any upstream code.
    build) exec /usr/bin/makepkg --holdver --force --noconfirm --noprogressbar ;;
    full) exec /usr/bin/makepkg --force --noconfirm --noprogressbar ;;
esac
"""

# Reads the desktop user's makepkg overrides as that user, after the system files,
# matching makepkg's own order. Only validated values are used by the build.
USER_MAKEPKG_CONFIG_SCRIPT = r"""
conf="$HOME/.config/pacman/makepkg.conf"
[[ -r $conf ]] || conf="$HOME/.makepkg.conf"
[[ -r $conf ]] || exit 0
{
    source /etc/makepkg.conf
    for system_conf in /etc/makepkg.conf.d/*.conf; do
        [[ -r $system_conf ]] && source "$system_conf"
    done
    source "$conf"
} >/dev/null 2>&1 </dev/null
printf '%s\0%s\0' "${MAKEFLAGS-}" "${PACKAGER-}"
"""


@dataclass(frozen=True, slots=True)
class AurBuildSandbox:
    token: str

    @classmethod
    def create(cls) -> AurBuildSandbox:
        return cls(secrets.token_hex(6))

    def unit(self, phase: str) -> str:
        if phase not in BUILD_PHASES:
            raise ValueError(phase)
        suffix = "" if phase == BUILD_PHASE_FULL else f"-{phase}"
        return f"{AUR_UNIT_PREFIX}{self.token}{suffix}"

    def units(self) -> list[str]:
        return [f"{self.unit(phase)}.service" for phase in BUILD_PHASES]

    @property
    def state_directory(self) -> Path:
        return AUR_STATE_ROOT / self.token


@dataclass(frozen=True, slots=True)
class AurBuildUser:
    name: str
    uid: int
    gid: int
    home: Path


def _seal_aur_build_checkout(
    review: AurPkgbuildReview,
    *,
    build_root: Path,
) -> Path:
    checkout_path = build_root / f"{review.package_name}-{review.digest[:16]}"
    checkout_path.mkdir(mode=0o700)
    directories: set[Path] = {checkout_path}
    for reviewed_file in review.files:
        destination = checkout_path.joinpath(*Path(reviewed_file.path).parts)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        current = destination.parent
        while current != checkout_path.parent:
            directories.add(current)
            if current == checkout_path:
                break
            current = current.parent
        with destination.open("xb") as handle:
            handle.write(reviewed_file.content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        destination.chmod(0o555 if reviewed_file.executable else 0o444)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        directory.chmod(0o555)
    return checkout_path


def resolve_aur_build_user(raw_uid: str | None = None) -> AurBuildUser:
    uid_text = raw_uid if raw_uid is not None else os.environ.get("PKEXEC_UID", "")
    try:
        uid = int(uid_text, 10)
    except (TypeError, ValueError) as exc:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not identify the unprivileged user for the AUR build.",
            )
        ) from exc
    if uid <= 0:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR packages must not be built as root.",
            )
        )
    try:
        account = pwd.getpwuid(uid)
    except KeyError as exc:
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Could not identify the unprivileged user for the AUR build.",
            )
        ) from exc
    home = Path(account.pw_dir)
    if not home.is_absolute() or not home.is_dir():
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "The AUR build user has no usable home directory.",
            )
        )
    return AurBuildUser(
        name=account.pw_name,
        uid=account.pw_uid,
        gid=account.pw_gid,
        home=home,
    )


def prepare_build_input(
    review: AurPkgbuildReview,
    input_directory: Path,
    *,
    build_user: AurBuildUser,
    emit_log: Callable[[str], None],
) -> None:
    """Create the read-only tree mounted into the build unit."""
    input_directory.mkdir(mode=0o755)
    sealed = _seal_aur_build_checkout(review, build_root=input_directory)
    sealed.rename(input_directory / "checkout")
    makeflags, packager = _user_makepkg_overrides(build_user, emit_log=emit_log)
    lines = [
        "# Generated by ArchUpdater for an isolated AUR build.",
        "source /etc/makepkg.conf",
        "for archupdater_conf in /etc/makepkg.conf.d/*.conf; do",
        '    [[ -r $archupdater_conf ]] && source "$archupdater_conf"',
        "done",
        "unset archupdater_conf",
    ]
    if makeflags:
        lines.append(f"MAKEFLAGS={shlex.quote(makeflags)}")
    if packager:
        lines.append(f"PACKAGER={shlex.quote(packager)}")
    _write_read_only(input_directory / "makepkg.conf", ("\n".join(lines) + "\n").encode())
    keys = _export_user_pgp_keys(build_user, _declared_pgp_fingerprints(review))
    _write_read_only(input_directory / "pgp-keys", keys)


def build_unit_command(
    sandbox: AurBuildSandbox,
    input_directory: Path,
    phase: str = BUILD_PHASE_FULL,
) -> list[str]:
    command = [
        str(SYSTEMD_RUN_PATH),
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        "--service-type=exec",
        f"--unit={sandbox.unit(phase)}",
        "--property=DynamicUser=yes",
        f"--property=StateDirectory={AUR_STATE_NAME}/{sandbox.token}",
        "--property=StateDirectoryMode=0700",
        # systemd mounts DynamicUser= state noexec; builds run configure scripts and
        # reviewed helpers from it. nosuid and nodev stay in effect.
        f"--property=ExecPaths={sandbox.state_directory}",
        f"--property=BindReadOnlyPaths={input_directory}:{BUILD_INPUT_MOUNT}",
        "--property=ProtectHome=yes",
        "--property=PrivateTmp=yes",
        "--property=ProtectSystem=strict",
        "--property=NoNewPrivileges=yes",
        "--property=KillMode=control-group",
        f"--property=RuntimeMaxSec={BUILD_UNIT_TIMEOUT_SECONDS}",
        "--setenv=PATH=/usr/local/bin:/usr/bin:/bin",
        "--setenv=LANG=C.UTF-8",
        "--setenv=LC_ALL=C.UTF-8",
        f"--setenv=ARCHUPDATER_INPUT={BUILD_INPUT_MOUNT}",
        f"--setenv=ARCHUPDATER_PHASE={phase}",
    ]
    for variable in PROXY_VARIABLES:
        value = os.environ.get(variable)
        if value and "\n" not in value:
            command.append(f"--setenv={variable}={value}")
    return [*command, "--", str(BASH_PATH), "-c", BUILD_UNIT_SCRIPT, "archupdater-aur-build"]


def stop_build_unit(sandbox: AurBuildSandbox) -> None:
    # systemd-run --wait does not stop the unit when it is itself interrupted.
    try:
        subprocess.run(
            [str(SYSTEMCTL_PATH), "stop", "--", *sandbox.units()],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=60, check=False, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        pass


def remove_build_state(token: str) -> None:
    if not BUILD_TOKEN_RE.fullmatch(token):
        return
    link = AUR_STATE_LINK_ROOT / token
    if link.is_symlink():
        link.unlink(missing_ok=True)
    shutil.rmtree(AUR_STATE_ROOT / token, ignore_errors=True)


def remove_stale_build_states() -> None:
    """Remove state left by a helper that was killed before it could clean up."""
    try:
        tokens = [entry.name for entry in AUR_STATE_ROOT.iterdir()]
    except OSError:
        return
    for token in tokens:
        if BUILD_TOKEN_RE.fullmatch(token) and not _build_unit_is_running(token):
            remove_build_state(token)


def verified_state_directory(path: Path) -> Path:
    # The unit has stopped, so nothing can swap these paths any more; still refuse
    # symlinks planted by the build itself.
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR build output is not a valid regular package file.",
            )
        )
    return path


def _build_unit_is_running(token: str) -> bool:
    try:
        result = subprocess.run(
            [str(SYSTEMCTL_PATH), "is-active", "--", *AurBuildSandbox(token).units()],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=30, check=False, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        return True
    running_states = {"active", "activating", "deactivating", "reloading"}
    return any(state.strip() in running_states for state in result.stdout.splitlines())


def _write_read_only(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
    path.chmod(0o444)


def _declared_pgp_fingerprints(review: AurPkgbuildReview) -> list[str]:
    srcinfo = next((file.content for file in review.files if file.path == ".SRCINFO"), "")
    fingerprints: list[str] = []
    for raw_line in srcinfo.splitlines():
        key, separator, value = raw_line.strip().partition("=")
        value = value.strip()
        if (
            separator
            and key.strip() == "validpgpkeys"
            and PGP_FINGERPRINT_RE.fullmatch(value)
            and value.upper() not in fingerprints
        ):
            fingerprints.append(value.upper())
    return fingerprints


def _export_user_pgp_keys(build_user: AurBuildUser, fingerprints: list[str]) -> bytes:
    # Only public keys named by the reviewed .SRCINFO leave the user's keyring;
    # makepkg still checks each signature against those exact fingerprints.
    if not fingerprints or not GPG_PATH.exists():
        return b""
    output = _run_as_user(
        build_user,
        [str(GPG_PATH), "--batch", "--export", "--export-options", "export-minimal",
         "--", *fingerprints],
        timeout_seconds=60,
    )
    return output or b""


def _user_makepkg_overrides(
    build_user: AurBuildUser,
    *,
    emit_log: Callable[[str], None],
) -> tuple[str, str]:
    output = _run_as_user(
        build_user, [str(BASH_PATH), "-c", USER_MAKEPKG_CONFIG_SCRIPT], timeout_seconds=10,
    )
    if not output:
        return "", ""
    values = output.decode("utf-8", errors="replace").split("\0")
    if len(values) < 2:
        return "", ""
    raw_makeflags, raw_packager = values[0].strip(), values[1].strip()
    makeflags = raw_makeflags if all(
        MAKEFLAGS_TOKEN_RE.fullmatch(token) for token in raw_makeflags.split()
    ) else ""
    if raw_makeflags and not makeflags:
        # Other make options (for example --eval) could run code inside the build.
        emit_log(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "Ignoring MAKEFLAGS from makepkg.conf: only -j and -l are allowed for isolated AUR builds.",
            )
        )
    packager = raw_packager if len(raw_packager) <= 256 and raw_packager.isprintable() else ""
    return makeflags, packager


def _run_as_user(
    build_user: AurBuildUser,
    command: list[str],
    *,
    timeout_seconds: float,
) -> bytes | None:
    try:
        process = subprocess.Popen(
            command,
            user=build_user.uid,
            group=build_user.gid,
            extra_groups=[],
            cwd=build_user.home,
            env={
                "HOME": str(build_user.home),
                "USER": build_user.name,
                "LOGNAME": build_user.name,
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return None
    return _bounded_output(process, timeout_seconds=timeout_seconds)


def _bounded_output(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
) -> bytes | None:
    # User configuration may hang or leave children holding stdout open: bound
    # both the time and the amount of output, then kill the whole session.
    assert process.stdout is not None
    deadline = time.monotonic() + timeout_seconds
    chunks: list[bytes] = []
    size = 0
    completed = False
    try:
        file_descriptor = process.stdout.fileno()
        os.set_blocking(file_descriptor, False)
        while size <= MAX_USER_HELPER_OUTPUT_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select([file_descriptor], [], [], min(remaining, 0.1))
            if not readable:
                continue
            try:
                chunk = os.read(file_descriptor, 64 * 1024)
            except BlockingIOError:
                continue
            if not chunk:
                completed = True
                break
            chunks.append(chunk)
            size += len(chunk)
        if completed:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
    except (OSError, subprocess.TimeoutExpired):
        completed = False
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.wait()
        process.stdout.close()
    if not completed or process.returncode != 0 or size > MAX_USER_HELPER_OUTPUT_BYTES:
        return None
    return b"".join(chunks)


def _copy_untrusted_artifact(
    source: Path,
    destination: Path,
) -> Path:
    source_stat = source.lstat()
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR artifact is not a regular non-symlink file: {path}",
            ).format(path=source)
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(source, flags)
    copied_size = 0
    try:
        opened_stat = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_dev != source_stat.st_dev
            or opened_stat.st_ino != source_stat.st_ino
        ):
            raise validation.PrivilegedUpdateValidationError(
                QCoreApplication.translate(
                    "PrivilegedHelper",
                    "AUR artifact changed while it was being opened.",
                )
            )
        with os.fdopen(file_descriptor, "rb", closefd=False) as source_handle:
            with destination.open("xb") as destination_handle:
                while chunk := source_handle.read(COPY_CHUNK_BYTES):
                    copied_size += len(chunk)
                    if copied_size > MAX_AUR_ARTIFACT_BYTES:
                        raise validation.PrivilegedUpdateValidationError(
                            QCoreApplication.translate(
                                "PrivilegedHelper",
                                "AUR artifact exceeds the allowed size.",
                            )
                        )
                    destination_handle.write(chunk)
                destination_handle.flush()
                os.fsync(destination_handle.fileno())
    finally:
        os.close(file_descriptor)

    final_stat = source.lstat()
    if (
        final_stat.st_dev != source_stat.st_dev
        or final_stat.st_ino != source_stat.st_ino
        or final_stat.st_size != source_stat.st_size
        or final_stat.st_mtime_ns != source_stat.st_mtime_ns
        or final_stat.st_ctime_ns != source_stat.st_ctime_ns
        or copied_size != source_stat.st_size
    ):
        raise validation.PrivilegedUpdateValidationError(
            QCoreApplication.translate(
                "PrivilegedHelper",
                "AUR artifact changed while it was being copied.",
            )
        )
    return destination
