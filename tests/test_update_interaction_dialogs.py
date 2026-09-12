from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.aur import AurPkgbuildReview, AurReviewFile
from archupdater.presentation.update_interaction_dialogs import handle_question_request


class UpdateInteractionDialogsTests(unittest.TestCase):
    def test_maps_pkgbuild_review_payload_and_submits_dialog_result(self) -> None:
        responses: list[tuple[str, object]] = []
        cancellations: list[str] = []
        parent = object()
        content = "pkgbase=foo"
        file_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        tree_digest = hashlib.sha256()
        for value in ("PKGBUILD", str(len(content)), file_digest):
            tree_digest.update(value.encode("utf-8"))
            tree_digest.update(b"\0")

        with patch(
            "archupdater.presentation.update_interaction_dialogs.confirm_aur_pkgbuild_review",
            return_value=True,
        ) as confirm_review:
            handle_question_request(
                parent=parent,  # type: ignore[arg-type]
                payload={
                    "question_id": "review-1",
                    "question_type": "aur_pkgbuild_review",
                    "package_name": "libfoo",
                    "package_base": "foo",
                    "pkgbuild": content,
                    "commit": "a" * 40,
                    "digest": tree_digest.hexdigest(),
                    "files": [
                        {
                            "path": "PKGBUILD",
                            "sha256": file_digest,
                            "size": 11,
                            "content": content,
                        },
                    ],
                },
                submit_response=lambda question_id, response: responses.append(
                    (question_id, response)
                ),
                cancel_question=cancellations.append,
            )

        confirm_review.assert_called_once_with(
            parent,
            AurPkgbuildReview(
                package_name="libfoo",
                package_base="foo",
                pkgbuild=content,
                commit="a" * 40,
                digest=tree_digest.hexdigest(),
                files=(
                    AurReviewFile(
                        path="PKGBUILD",
                        sha256=file_digest,
                        size=11,
                        content=content,
                    ),
                ),
            ),
        )
        self.assertEqual(responses, [("review-1", True)])
        self.assertEqual(cancellations, [])

    def test_cancels_unsupported_legacy_question_without_opening_dialog(self) -> None:
        responses: list[tuple[str, object]] = []
        cancellations: list[str] = []

        with patch(
            "archupdater.presentation.update_interaction_dialogs.confirm_aur_pkgbuild_review"
        ) as confirm_review:
            handle_question_request(
                parent=object(),  # type: ignore[arg-type]
                payload={
                    "question_id": "legacy-1",
                    "question_type": "provider",
                    "options": [{"value": "1", "label": "provider"}],
                },
                submit_response=lambda question_id, response: responses.append(
                    (question_id, response)
                ),
                cancel_question=cancellations.append,
            )

        confirm_review.assert_not_called()
        self.assertEqual(responses, [])
        self.assertEqual(cancellations, ["legacy-1"])

    def test_cancels_malformed_review_instead_of_showing_a_partial_manifest(self) -> None:
        responses: list[tuple[str, object]] = []
        cancellations: list[str] = []

        with patch(
            "archupdater.presentation.update_interaction_dialogs.confirm_aur_pkgbuild_review"
        ) as confirm_review:
            handle_question_request(
                parent=object(),  # type: ignore[arg-type]
                payload={
                    "question_id": "review-1",
                    "question_type": "aur_pkgbuild_review",
                    "package_name": "foo",
                    "package_base": "foo",
                    "pkgbuild": "pkgname=foo",
                    "commit": "a" * 40,
                    "digest": "b" * 64,
                    "files": ["invalid-entry"],
                },
                submit_response=lambda question_id, response: responses.append(
                    (question_id, response)
                ),
                cancel_question=cancellations.append,
            )

        confirm_review.assert_not_called()
        self.assertEqual(responses, [])
        self.assertEqual(cancellations, ["review-1"])


if __name__ == "__main__":
    unittest.main()
