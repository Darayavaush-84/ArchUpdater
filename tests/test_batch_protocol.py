from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.domain.enums import UpdateSource
from archupdater.domain.update_plan import (
    UpdatePlan,
    UpdatePlanAction,
    UpdatePlanItem,
)
from archupdater.application.update_session.protocol import (
    MAX_UPDATE_PLAN_BYTES,
    UPDATE_PLAN_SCHEMA_VERSION,
    deserialize_update_plan_payload,
    serialize_update_plan,
    deserialize_update_plan_json,
)


class BatchProtocolTests(unittest.TestCase):
    def test_update_plan_round_trip(self) -> None:
        items = [
            UpdatePlanItem(UpdateSource.SYSTEM, "linux", expected_version="6.9-1"),
            UpdatePlanItem(
                UpdateSource.AUR,
                "libfoo",
                package_name="libfoo",
                package_base="foo",
                expected_version="2.0-1",
            ),
            UpdatePlanItem(
                UpdateSource.FLATPAK,
                "app/org.example.App/x86_64/stable",
                installation_scope="user",
                expected_version="2.0",
            ),
            UpdatePlanItem(
                UpdateSource.FLATPAK,
                "user",
                action=UpdatePlanAction.CLEANUP,
                installation_scope="user",
            ),
            UpdatePlanItem(UpdateSource.FIRMWARE, "device-1", expected_version="1.2.0"),
            UpdatePlanItem(
                UpdateSource.PLASMA_WIDGET,
                "123",
                package_name="widget.zip",
                package_kind="Plasma/Applet",
                plugin_id="org.example.widget",
                expected_version="1.2.0",
            ),
        ]
        plan = UpdatePlan(items=items)

        payload = serialize_update_plan(plan)

        self.assertEqual(payload["schema_version"], UPDATE_PLAN_SCHEMA_VERSION)
        self.assertEqual(set(payload), {"schema_version", "items"})
        self.assertEqual(payload["items"][1]["package_base"], "foo")
        self.assertEqual(payload["items"][1]["expected_version"], "2.0-1")
        self.assertEqual(deserialize_update_plan_payload(payload), plan)

    def test_update_plan_payload_rejects_missing_fields(self) -> None:
        with self.assertRaises(ValueError):
            deserialize_update_plan_payload({"schema_version": UPDATE_PLAN_SCHEMA_VERSION})

    def test_update_plan_payload_rejects_invalid_target_shapes(self) -> None:
        payload = serialize_update_plan(UpdatePlan())
        payload["items"] = ["not-a-target"]

        with self.assertRaises(ValueError):
            deserialize_update_plan_payload(payload)

    def test_update_plan_payload_rejects_empty_and_duplicate_plans(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one"):
            deserialize_update_plan_payload(serialize_update_plan(UpdatePlan()))

        item = UpdatePlanItem(UpdateSource.SYSTEM, "linux", expected_version="6.9-1")
        payload = serialize_update_plan(UpdatePlan([item, item]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            deserialize_update_plan_payload(payload)

    def test_update_plan_payload_rejects_extra_fields_and_control_characters(self) -> None:
        payload = serialize_update_plan(
            UpdatePlan([UpdatePlanItem(UpdateSource.SYSTEM, "linux", expected_version="6.9-1")])
        )
        payload["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "unsupported"):
            deserialize_update_plan_payload(payload)

        payload = serialize_update_plan(
            UpdatePlan(
                [UpdatePlanItem(UpdateSource.SYSTEM, "linux\nspoof", expected_version="6.9-1")]
            )
        )
        with self.assertRaisesRegex(ValueError, "unsafe"):
            deserialize_update_plan_payload(payload)

    def test_update_plan_payload_requires_complete_aur_identity(self) -> None:
        payload = serialize_update_plan(
            UpdatePlan(
                [
                    UpdatePlanItem(
                        UpdateSource.AUR,
                        "example",
                        package_name="example",
                        expected_version="1.0-1",
                    )
                ]
            )
        )

        with self.assertRaisesRegex(ValueError, "name, base, and version"):
            deserialize_update_plan_payload(payload)

    def test_dynamic_aur_update_round_trip_requires_current_version_and_marker(self) -> None:
        item = UpdatePlanItem(
            UpdateSource.AUR,
            "example-git",
            package_name="example-git",
            package_base="example-git",
            expected_version="latest-commit",
            current_version="r1.aaaaaaa-1",
            dynamic_version=True,
        )
        payload = serialize_update_plan(UpdatePlan([item]))

        self.assertEqual(deserialize_update_plan_payload(payload).items, [item])

        payload["items"][0]["expected_version"] = "r2.bbbbbbb-1"
        with self.assertRaisesRegex(ValueError, "latest-commit"):
            deserialize_update_plan_payload(payload)

    def test_update_plan_payload_rejects_flatpak_option_injection(self) -> None:
        for target_id in ("--assumeyes", "app/org.example.App/../../etc"):
            with self.subTest(target_id=target_id):
                payload = serialize_update_plan(
                    UpdatePlan(
                        [
                            UpdatePlanItem(
                                UpdateSource.FLATPAK,
                                target_id,
                                installation_scope="user",
                            )
                        ]
                    )
                )

                with self.assertRaisesRegex(ValueError, "reference is invalid"):
                    deserialize_update_plan_payload(payload)

    def test_update_plan_payload_rejects_inconsistent_cleanup_item(self) -> None:
        payload = serialize_update_plan(
            UpdatePlan(
                [
                    UpdatePlanItem(
                        UpdateSource.FLATPAK,
                        "unexpected-target",
                        action=UpdatePlanAction.CLEANUP,
                        installation_scope="user",
                    )
                ]
            )
        )

        with self.assertRaisesRegex(ValueError, "inconsistent"):
            deserialize_update_plan_payload(payload)

    def test_update_plan_item_queries(self) -> None:
        items = [
            UpdatePlanItem(UpdateSource.SYSTEM, "linux"),
            UpdatePlanItem(UpdateSource.AUR, "paru", package_base="paru"),
            UpdatePlanItem(
                UpdateSource.FLATPAK,
                "app/org.example.App/x86_64/stable",
                installation_scope="user",
            ),
            UpdatePlanItem(
                UpdateSource.FLATPAK,
                "system",
                action=UpdatePlanAction.CLEANUP,
                installation_scope="system",
            ),
            UpdatePlanItem(UpdateSource.FIRMWARE, "device-1"),
            UpdatePlanItem(
                UpdateSource.PLASMA_WIDGET,
                "123",
                package_name="widget.zip",
                package_kind="Plasma/Applet",
                plugin_id="org.example.widget",
            ),
        ]

        plan = UpdatePlan(items=items)

        self.assertEqual(plan.items, items)
        self.assertTrue(plan.has_any)
        self.assertTrue(plan.has_source(UpdateSource.FLATPAK))
        self.assertEqual(plan.target_ids(UpdateSource.SYSTEM), ["linux"])
        self.assertEqual(plan.update_items(UpdateSource.AUR)[0].package_base, "paru")
        self.assertEqual(plan.flatpak_refs("user"), ["app/org.example.App/x86_64/stable"])
        self.assertEqual(plan.cleanup_scopes(UpdateSource.FLATPAK), ["system"])

    def test_update_plan_has_no_arbitrary_512_item_limit(self) -> None:
        plan = UpdatePlan(
            [
                UpdatePlanItem(
                    UpdateSource.SYSTEM,
                    f"package-{index}",
                    expected_version=f"2.0-{index}",
                )
                for index in range(2_000)
            ]
        )

        self.assertEqual(len(deserialize_update_plan_payload(serialize_update_plan(plan)).items), 2_000)

    def test_update_plan_rejects_oversized_json_before_parsing(self) -> None:
        oversized = " " * (MAX_UPDATE_PLAN_BYTES + 1)

        with self.assertRaisesRegex(ValueError, "safety limit"):
            deserialize_update_plan_json(oversized)


if __name__ == "__main__":
    unittest.main()
