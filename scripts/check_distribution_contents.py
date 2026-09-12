from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "archupdater"


def expected_wheel_package_files() -> set[str]:
    expected: set[str] = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        expected.add(path.relative_to(PACKAGE_ROOT.parent).as_posix())

    package_data_patterns = (
        "i18n/resources/*.qm",
        "resources/img/logos/*",
        "resources/img/illustrations/*",
        "resources/data/*",
    )
    for pattern in package_data_patterns:
        for path in PACKAGE_ROOT.glob(pattern):
            if path.is_file():
                expected.add(path.relative_to(PACKAGE_ROOT.parent).as_posix())
    return expected


def check_wheel(path: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as archive:
        actual = {
            name
            for name in archive.namelist()
            if name.startswith("archupdater/") and not name.endswith("/")
        }

    expected = expected_wheel_package_files()
    unexpected = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unexpected:
        errors.append(
            "wheel contains files that are not present in src/archupdater:\n  "
            + "\n  ".join(unexpected)
        )
    if missing:
        errors.append("wheel is missing package files:\n  " + "\n  ".join(missing))
    return errors


def check_sdist(path: Path) -> list[str]:
    errors: list[str] = []
    with tarfile.open(path, "r:gz") as archive:
        members = [PurePosixPath(member.name) for member in archive.getmembers() if member.isfile()]

    relative_members = {
        PurePosixPath(*member.parts[1:])
        for member in members
        if len(member.parts) > 1
    }
    forbidden_parts = {
        ".codex",
        ".git",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "tests",
        "venv",
    }
    contaminated = sorted(
        str(member)
        for member in relative_members
        if forbidden_parts.intersection(member.parts)
        or member.suffix in {".pyc", ".pyo"}
    )
    if contaminated:
        errors.append("sdist contains generated or excluded files:\n  " + "\n  ".join(contaminated))

    required = {
        PurePosixPath("docs/architecture.md"),
        PurePosixPath("LICENSE"),
        PurePosixPath("MANIFEST.in"),
        PurePosixPath("README.md"),
        PurePosixPath("constraints-ci.txt"),
        PurePosixPath("install.sh"),
        PurePosixPath("uninstall.sh"),
        PurePosixPath("pyproject.toml"),
        PurePosixPath("resources/desktop/io.github.archupdater.desktop"),
        PurePosixPath("resources/polkit/io.github.archupdater.policy"),
        PurePosixPath("scripts/build_distribution.sh"),
        PurePosixPath("scripts/build_translations.sh"),
        PurePosixPath("scripts/check_distribution_contents.py"),
        PurePosixPath("scripts/check_translation_sources.py"),
        PurePosixPath("scripts/check_translations.sh"),
        PurePosixPath("scripts/validate_kde_addon_id_map.py"),
    }
    required.update(
        PurePosixPath("src") / PurePosixPath(package_path)
        for package_path in expected_wheel_package_files()
    )
    required.update(
        PurePosixPath(f"i18n/ts/archupdater_{lang}.ts")
        for lang in ("en", "it", "de", "fr", "es")
    )
    missing = sorted(str(member) for member in required - relative_members)
    if missing:
        errors.append("sdist is missing required project files:\n  " + "\n  ".join(missing))
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate ArchUpdater distribution contents.")
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--sdist", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    errors = [*check_wheel(args.wheel), *check_sdist(args.sdist)]
    if errors:
        print("\n\n".join(errors))
        return 1
    print(f"Validated {args.wheel.name} and {args.sdist.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
