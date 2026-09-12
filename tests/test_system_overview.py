from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from archupdater.infrastructure.system_overview import SystemOverviewProvider


class SystemOverviewProviderTests(unittest.TestCase):
    def test_snapshot_reads_package_activity_mirror_and_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pacman_log = root / "pacman.log"
            pacman_log.write_text(
                "\n".join(
                    (
                        "[2026-07-28T10:00:00+0200] [ALPM] upgraded linux (1 -> 2)",
                        "[2026-07-29T20:15:00+0200] [ALPM] upgraded flatpak (1 -> 2)",
                    )
                ),
                encoding="utf-8",
            )
            pacman_conf = root / "pacman.conf"
            pacman_conf.write_text("[core]\n[cachyos]\n", encoding="utf-8")
            mirrorlist = root / "mirrorlist"
            mirrorlist.write_text(
                "Server = https://mirror.example.test/$repo/os/$arch\n",
                encoding="utf-8",
            )

            snapshot = SystemOverviewProvider(
                pacman_log=pacman_log,
                pacman_conf=pacman_conf,
                mirrorlists=(mirrorlist,),
            ).snapshot()

        self.assertEqual(
            snapshot.last_update_at.isoformat(),
            "2026-07-29T20:15:00+02:00",
        )
        self.assertEqual(snapshot.mirror, "mirror.example.test")
        self.assertEqual(snapshot.repository, "CachyOS")
        self.assertTrue(snapshot.kernel)

    def test_missing_files_return_safe_fallbacks(self) -> None:
        missing = Path("/definitely/missing/archupdater")

        snapshot = SystemOverviewProvider(
            pacman_log=missing,
            pacman_conf=missing,
            mirrorlists=(missing,),
        ).snapshot()

        self.assertIsNone(snapshot.last_update_at)
        self.assertEqual(snapshot.mirror, "Not detected")
        self.assertEqual(snapshot.repository, "Not detected")


if __name__ == "__main__":
    unittest.main()
