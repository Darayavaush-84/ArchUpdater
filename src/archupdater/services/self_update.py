"""Bounded downloads and provenance verification shared with the privileged installer."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request

from archupdater.domain.self_update import (
    MAX_BUNDLE_BYTES,
    MAX_WHEEL_BYTES,
    RELEASE_WORKFLOW,
    REPOSITORY,
    SelfUpdateRelease,
    release_version,
)


def verification_command(wheel: Path, bundle: Path, version: str) -> list[str]:
    release_version(version)
    return [
        "/usr/bin/gh",
        "attestation",
        "verify",
        str(wheel),
        "--bundle",
        str(bundle),
        "--repo",
        REPOSITORY,
        "--cert-identity",
        f"{RELEASE_WORKFLOW}@refs/tags/v{version}",
        "--source-ref",
        f"refs/tags/v{version}",
        "--deny-self-hosted-runners",
    ]


def verify_artifact(wheel: Path, bundle: Path, version: str, *, home: Path) -> None:
    # Do not inherit user tokens, GitHub CLI configuration, proxies or trust overrides.
    result = subprocess.run(
        verification_command(wheel, bundle, version),
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(home),
            "GH_CONFIG_DIR": str(home / "gh"),
            "LANG": "C.UTF-8",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise ValueError("Release authenticity verification failed.")


class ReleaseRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        url = urllib.parse.urlsplit(newurl)
        if (
            url.scheme != "https"
            or url.hostname
            not in {
                "github.com",
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or url.username
            or url.password
            or url.port not in {None, 443}
        ):
            raise ValueError("Unsafe release download redirect.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_release(release: SelfUpdateRelease, directory: Path) -> tuple[Path, Path]:
    opener = urllib.request.build_opener(ReleaseRedirectHandler())
    paths = []
    deadline = time.monotonic() + 180
    for url, name, maximum in (
        (release.wheel_url, release.wheel_name, MAX_WHEEL_BYTES),
        (release.bundle_url, release.wheel_name + ".sigstore.json", MAX_BUNDLE_BYTES),
    ):
        # Validate again even when the caller constructed a release directly.
        expected = f"https://github.com/{REPOSITORY}/releases/download/v{release_version(release.version)}/{name}"
        if url != expected:
            raise ValueError("Invalid release download URL.")
        path = directory / name
        request = urllib.request.Request(
            url, headers={"User-Agent": "ArchUpdater", "Accept": "application/octet-stream"}
        )
        with opener.open(request, timeout=30) as response, path.open("xb") as output:
            os.chmod(path, 0o600)
            total = 0
            while chunk := response.read1(64 * 1024):
                if time.monotonic() > deadline:
                    raise TimeoutError("Release download timed out.")
                total += len(chunk)
                if total > maximum:
                    raise ValueError("Release download exceeds the size limit.")
                output.write(chunk)
            if total == 0:
                raise ValueError("Empty release download.")
        paths.append(path)
    verify_artifact(*paths, release.version, home=directory)
    return paths[0], paths[1]
