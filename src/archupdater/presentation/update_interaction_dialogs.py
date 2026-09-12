from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import PurePosixPath

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox, QWidget

from archupdater.domain.aur import AurPkgbuildReview, AurReviewFile, AurVcsSource
from archupdater.presentation.aur_pkgbuild_review_dialog import confirm_aur_pkgbuild_review


_HEX_DIGEST_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
_MAX_REVIEW_BYTES = 16 * 1024 * 1024


def handle_question_request(
    *,
    parent: QWidget,
    payload: object,
    submit_response: Callable[[str, object], None],
    cancel_question: Callable[[str], None],
) -> None:
    data = payload if isinstance(payload, dict) else {}
    question_id = str(data.get("question_id") or "")
    if data.get("question_type") == "pacman_confirmation":
        message = data.get("message")
        if not question_id or not isinstance(message, str) or not message.strip() or len(message) > 16384:
            cancel_question(question_id)
            return
        answer = QMessageBox.question(
            parent,
            QCoreApplication.translate("UpdateInteractionDialogs", "Pacman confirmation"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        submit_response(question_id, answer == QMessageBox.StandardButton.Yes)
        return
    if data.get("question_type") == "transaction_change":
        _handle_transaction_change(
            parent=parent,
            data=data,
            question_id=question_id,
            submit_response=submit_response,
            cancel_question=cancel_question,
        )
        return
    if data.get("question_type") != "aur_pkgbuild_review":
        cancel_question(question_id)
        return

    review = _review_from_payload(data)
    if not question_id or review is None:
        cancel_question(question_id)
        return

    accepted = confirm_aur_pkgbuild_review(
        parent,
        review,
    )
    submit_response(question_id, accepted)


def _handle_transaction_change(
    *,
    parent: QWidget,
    data: dict[object, object],
    question_id: str,
    submit_response: Callable[[str, object], None],
    cancel_question: Callable[[str], None],
) -> None:
    title = data.get("title")
    message = data.get("message")
    raw_versions = data.get("versions")
    if (
        not question_id
        or not isinstance(title, str)
        or not isinstance(message, str)
        or not isinstance(raw_versions, dict)
        or not raw_versions
    ):
        cancel_question(question_id)
        return
    versions: list[str] = []
    for name, version in sorted(raw_versions.items(), key=lambda item: str(item[0])):
        if not isinstance(name, str) or not isinstance(version, str) or not name or not version:
            cancel_question(question_id)
            return
        versions.append(f"{name}: {version}")
    answer = QMessageBox.warning(
        parent,
        title,
        "\n".join((message, "", *versions)),
        QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Cancel,
    )
    submit_response(question_id, answer is QMessageBox.StandardButton.Ok)


def _review_from_payload(data: dict[object, object]) -> AurPkgbuildReview | None:
    package_name = data.get("package_name")
    package_base = data.get("package_base")
    pkgbuild = data.get("pkgbuild")
    commit = data.get("commit")
    digest = data.get("digest")
    raw_files = data.get("files")
    raw_vcs_sources = data.get("vcs_sources", [])
    if (
        not isinstance(package_name, str)
        or not package_name
        or not isinstance(package_base, str)
        or not package_base
        or not isinstance(pkgbuild, str)
        or not pkgbuild.strip()
        or not isinstance(commit, str)
        or _COMMIT_RE.fullmatch(commit) is None
        or not isinstance(digest, str)
        or _HEX_DIGEST_RE.fullmatch(digest) is None
        or not isinstance(raw_files, list)
        or not raw_files
        or not isinstance(raw_vcs_sources, list)
    ):
        return None

    reviewed_files: list[AurReviewFile] = []
    seen_paths: set[str] = set()
    total_size = 0
    tree_digest = hashlib.sha256()
    for raw_file in raw_files:
        if not isinstance(raw_file, dict) or set(raw_file) != {
            "path",
            "sha256",
            "size",
            "content",
        }:
            return None
        path = raw_file["path"]
        sha256 = raw_file["sha256"]
        size = raw_file["size"]
        content = raw_file["content"]
        if (
            not isinstance(path, str)
            or not path
            or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or PurePosixPath(path).as_posix() != path
            or path in seen_paths
            or not isinstance(sha256, str)
            or _HEX_DIGEST_RE.fullmatch(sha256) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(content, str)
        ):
            return None
        raw_content = content.encode("utf-8")
        if len(raw_content) != size or hashlib.sha256(raw_content).hexdigest() != sha256.lower():
            return None
        total_size += size
        if total_size > _MAX_REVIEW_BYTES:
            return None

        seen_paths.add(path)
        reviewed_files.append(
            AurReviewFile(path=path, sha256=sha256.lower(), size=size, content=content)
        )
        tree_digest.update(path.encode("utf-8"))
        tree_digest.update(b"\0")
        tree_digest.update(str(size).encode("ascii"))
        tree_digest.update(b"\0")
        tree_digest.update(sha256.lower().encode("ascii"))
        tree_digest.update(b"\0")

    if [reviewed_file.path for reviewed_file in reviewed_files] != sorted(seen_paths):
        return None
    reviewed_pkgbuild = next(
        (
            reviewed_file.content
            for reviewed_file in reviewed_files
            if reviewed_file.path == "PKGBUILD"
        ),
        None,
    )
    if reviewed_pkgbuild != pkgbuild or tree_digest.hexdigest() != digest.lower():
        return None

    vcs_sources: list[AurVcsSource] = []
    seen_source_names: set[str] = set()
    for raw_source in raw_vcs_sources:
        if not isinstance(raw_source, dict) or set(raw_source) != {
            "name",
            "url",
            "branch",
            "commit",
        }:
            return None
        name = raw_source["name"]
        url = raw_source["url"]
        branch = raw_source["branch"]
        source_commit = raw_source["commit"]
        if (
            not isinstance(name, str)
            or not name
            or name in seen_source_names
            or not isinstance(url, str)
            or not url
            or (branch is not None and not isinstance(branch, str))
            or not isinstance(source_commit, str)
            or _COMMIT_RE.fullmatch(source_commit) is None
        ):
            return None
        seen_source_names.add(name)
        vcs_sources.append(AurVcsSource(name, url, branch, source_commit.lower()))

    return AurPkgbuildReview(
        package_name=package_name,
        package_base=package_base,
        pkgbuild=pkgbuild,
        commit=commit.lower(),
        digest=digest.lower(),
        files=tuple(reviewed_files),
        vcs_sources=tuple(vcs_sources),
    )
