from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AurReviewFile:
    path: str
    sha256: str
    size: int
    content: str


@dataclass(frozen=True, slots=True)
class AurVcsSource:
    name: str
    url: str
    branch: str | None
    commit: str


@dataclass(frozen=True, slots=True)
class AurPkgbuildReview:
    package_name: str
    package_base: str
    pkgbuild: str
    commit: str = ""
    digest: str = ""
    files: tuple[AurReviewFile, ...] = ()
    vcs_sources: tuple[AurVcsSource, ...] = ()
    preparation_id: str = ""

    def rendered_content(self) -> str:
        metadata = [
            f"Commit: {self.commit or '-'}",
            f"Reviewed tree SHA-256: {self.digest or '-'}",
            "",
            "Tracked file manifest:",
        ]
        for reviewed_file in self.files:
            metadata.append(
                f"- {json.dumps(reviewed_file.path, ensure_ascii=True)}  "
                f"{reviewed_file.sha256}  "
                f"{reviewed_file.size} bytes  UTF-8 text"
            )
        if self.vcs_sources:
            metadata.extend(("", "Approved VCS source commits:"))
            for source in self.vcs_sources:
                ref = source.branch or "HEAD"
                metadata.append(f"- {source.name}: {source.url} ({ref}) @ {source.commit}")

        sections = ["\n".join(metadata)]
        for reviewed_file in self.files:
            sections.append(
                f"===== PATH {json.dumps(reviewed_file.path, ensure_ascii=True)} =====\n"
                f"{reviewed_file.content}"
            )
        if not self.files:
            sections.append(f"===== PKGBUILD =====\n{self.pkgbuild}")
        return "\n\n".join(sections)


@dataclass(frozen=True, slots=True)
class AurInstallTarget:
    package_name: str
    package_base: str
    version: str
    current_version: str = ""
    dynamic_version: bool = False
